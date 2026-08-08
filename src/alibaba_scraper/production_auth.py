# src/alibaba_scraper/production_auth.py
"""API-key rotation and short-lived token lifecycle methods."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta

import aiosqlite

from .production_models import ApiKeyCreated, ApiKeyKind, ApiKeyRecord, ApiPrincipal, Scope


class ApiKeyMixin:
    async def create_api_key(
        self,
        name: str,
        scopes: list[Scope] | None = None,
        expires_at: datetime | None = None,
        *,
        kind: ApiKeyKind = "persistent",
        parent_key_id: int | None = None,
        rotated_from_id: int | None = None,
    ) -> ApiKeyCreated:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("API key name is required")
        normalized = _normalize_scopes(scopes or ["read", "write"])
        raw = "abs_" + secrets.token_urlsafe(32)
        prefix = raw[:12]
        digest = _key_hash(raw)
        now = _now()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO api_keys(
                    name,key_prefix,key_hash,scopes_json,enabled,created_at,expires_at,
                    kind,parent_key_id,rotated_from_id
                ) VALUES(?,?,?,?,1,?,?,?,?,?)
                """,
                (
                    clean_name,
                    prefix,
                    digest,
                    json.dumps(normalized),
                    now,
                    expires_at.astimezone(UTC).isoformat() if expires_at else None,
                    kind,
                    parent_key_id,
                    rotated_from_id,
                ),
            )
            await self.connection.commit()
        return ApiKeyCreated(record=await self.get_api_key(int(cursor.lastrowid)), api_key=raw)

    async def get_api_key(self, key_id: int) -> ApiKeyRecord:
        row = await (
            await self.connection.execute("SELECT * FROM api_keys WHERE id=?", (key_id,))
        ).fetchone()
        if row is None:
            raise KeyError(f"API key {key_id} does not exist")
        return _api_key(row)

    async def list_api_keys(self) -> list[ApiKeyRecord]:
        rows = await (
            await self.connection.execute("SELECT * FROM api_keys ORDER BY id DESC")
        ).fetchall()
        return [_api_key(row) for row in rows]

    async def revoke_api_key(self, key_id: int) -> ApiKeyRecord:
        await self.get_api_key(key_id)
        now = _now()
        async with self._write_lock:
            await self.connection.execute(
                "UPDATE api_keys SET enabled=0,revoked_at=? WHERE id=?", (now, key_id)
            )
            await self.connection.commit()
        return await self.get_api_key(key_id)

    async def rotate_api_key(
        self,
        key_id: int,
        *,
        name: str | None = None,
        grace_minutes: int = 15,
    ) -> ApiKeyCreated:
        """Create a replacement key and retire the old key after an optional grace period."""
        if grace_minutes < 0 or grace_minutes > 10080:
            raise ValueError("grace_minutes must be between 0 and 10080")
        old = await self.get_api_key(key_id)
        if not old.enabled:
            raise ValueError("cannot rotate a disabled API key")
        replacement_name = name or (
            f"{old.name}-rotated-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        )
        created = await self.create_api_key(
            replacement_name,
            old.scopes,
            old.expires_at,
            kind="persistent",
            rotated_from_id=old.id,
        )
        now = datetime.now(UTC)
        retirement = now + timedelta(minutes=grace_minutes)
        async with self._write_lock:
            if grace_minutes == 0:
                await self.connection.execute(
                    """
                    UPDATE api_keys
                    SET enabled=0,revoked_at=?,rotated_to_id=?
                    WHERE id=?
                    """,
                    (now.isoformat(), created.record.id, old.id),
                )
            else:
                existing_expiry = old.expires_at
                expiry = min(existing_expiry, retirement) if existing_expiry else retirement
                await self.connection.execute(
                    "UPDATE api_keys SET expires_at=?,rotated_to_id=? WHERE id=?",
                    (expiry.isoformat(), created.record.id, old.id),
                )
            await self.connection.commit()
        return created

    async def mint_short_lived_token(
        self,
        parent_key_id: int,
        *,
        ttl_minutes: int = 60,
        scopes: list[Scope] | None = None,
        name: str | None = None,
    ) -> ApiKeyCreated:
        """Mint an opaque short-lived token whose scopes cannot exceed its parent key."""
        if ttl_minutes < 1 or ttl_minutes > 1440:
            raise ValueError("ttl_minutes must be between 1 and 1440")
        parent = await self.get_api_key(parent_key_id)
        if not parent.enabled:
            raise ValueError("parent API key is disabled")
        requested = _normalize_scopes(scopes or parent.scopes)
        principal = ApiPrincipal(key_id=parent.id, name=parent.name, scopes=parent.scopes)
        if any(not principal.allows(scope) for scope in requested):
            raise ValueError("token scopes cannot exceed parent API key scopes")
        token_name = name or (
            f"{parent.name}-token-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-"
            f"{secrets.token_hex(2)}"
        )
        expires = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        if parent.expires_at and expires > parent.expires_at:
            expires = parent.expires_at
        return await self.create_api_key(
            token_name,
            requested,
            expires,
            kind="token",
            parent_key_id=parent.id,
        )

    async def authenticate(self, raw_key: str) -> ApiPrincipal | None:
        if not raw_key.startswith("abs_") or len(raw_key) < 20:
            return None
        prefix = raw_key[:12]
        rows = await (
            await self.connection.execute(
                "SELECT * FROM api_keys WHERE key_prefix=? AND enabled=1", (prefix,)
            )
        ).fetchall()
        digest = _key_hash(raw_key)
        now = datetime.now(UTC)
        for row in rows:
            if not hmac.compare_digest(str(row["key_hash"]), digest):
                continue
            expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
            if expires_at is not None and expires_at <= now:
                return None
            async with self._write_lock:
                await self.connection.execute(
                    "UPDATE api_keys SET last_used_at=? WHERE id=?", (now.isoformat(), row["id"])
                )
                await self.connection.commit()
            return ApiPrincipal(
                key_id=int(row["id"]),
                name=row["name"],
                scopes=_normalize_scopes(json.loads(row["scopes_json"])),
            )
        return None


def _normalize_scopes(scopes: list[str]) -> list[Scope]:
    allowed = {"read", "write", "admin"}
    normalized = list(dict.fromkeys(scope.strip().lower() for scope in scopes))
    if any(scope not in allowed for scope in normalized):
        raise ValueError("scopes must be read, write, or admin")
    return normalized  # type: ignore[return-value]


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _api_key(row: aiosqlite.Row) -> ApiKeyRecord:
    keys = set(row.keys())
    return ApiKeyRecord(
        id=int(row["id"]),
        name=row["name"],
        key_prefix=row["key_prefix"],
        scopes=_normalize_scopes(json.loads(row["scopes_json"])),
        enabled=bool(row["enabled"]),
        kind=row["kind"] if "kind" in keys else "persistent",
        parent_key_id=row["parent_key_id"] if "parent_key_id" in keys else None,
        rotated_from_id=row["rotated_from_id"] if "rotated_from_id" in keys else None,
        rotated_to_id=row["rotated_to_id"] if "rotated_to_id" in keys else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
    )
