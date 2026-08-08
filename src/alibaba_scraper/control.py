# src/alibaba_scraper/control.py
"""Catalog browsing, alerts, and configurable scoring profiles."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field, model_validator

from .models import ProductRecord
from .scoring import ScoreWeights, score_product

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
CREATE TABLE IF NOT EXISTS scoring_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 0,
  price_weight REAL NOT NULL,
  moq_weight REAL NOT NULL,
  supplier_weight REAL NOT NULL,
  tier_weight REAL NOT NULL,
  data_quality_weight REAL NOT NULL,
  min_score_alert REAL NOT NULL DEFAULT 85,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_scores (
  profile_id INTEGER NOT NULL REFERENCES scoring_profiles(id) ON DELETE CASCADE,
  product_key TEXT NOT NULL REFERENCES products(product_key) ON DELETE CASCADE,
  job_id INTEGER,
  score REAL NOT NULL,
  price_value REAL NOT NULL,
  moq_score REAL NOT NULL,
  supplier_confidence REAL NOT NULL,
  tier_discount REAL NOT NULL,
  data_quality REAL NOT NULL,
  peer_median_price TEXT,
  reasons_json TEXT NOT NULL,
  scored_at TEXT NOT NULL,
  PRIMARY KEY(profile_id, product_key)
);
CREATE INDEX IF NOT EXISTS idx_profile_scores_rank
  ON profile_scores(profile_id, score DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  watchlist_id INTEGER,
  job_id INTEGER,
  product_key TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_unread ON alerts(read_at, id DESC);
"""


class ScoringProfileInput(BaseModel):
    """User-editable score weights and high-score alert threshold."""

    name: str = Field(min_length=1, max_length=80)
    price_weight: float = Field(default=35, ge=0)
    moq_weight: float = Field(default=20, ge=0)
    supplier_weight: float = Field(default=20, ge=0)
    tier_weight: float = Field(default=10, ge=0)
    data_quality_weight: float = Field(default=15, ge=0)
    min_score_alert: float = Field(default=85, ge=0, le=100)
    activate: bool = False

    @model_validator(mode="after")
    def validate_weights(self) -> "ScoringProfileInput":
        self.name = self.name.strip()
        if self.total_weight <= 0:
            raise ValueError("at least one scoring weight must be greater than zero")
        return self

    @property
    def total_weight(self) -> float:
        return sum(
            (
                self.price_weight,
                self.moq_weight,
                self.supplier_weight,
                self.tier_weight,
                self.data_quality_weight,
            )
        )


class ScoringProfile(BaseModel):
    id: int
    name: str
    active: bool
    price_weight: float
    moq_weight: float
    supplier_weight: float
    tier_weight: float
    data_quality_weight: float
    min_score_alert: float
    created_at: datetime
    updated_at: datetime

    def weights(self) -> ScoreWeights:
        return ScoreWeights(
            price_value=self.price_weight,
            moq=self.moq_weight,
            supplier_confidence=self.supplier_weight,
            tier_discount=self.tier_weight,
            data_quality=self.data_quality_weight,
        )


class AlertRecord(BaseModel):
    id: int
    kind: str
    severity: Literal["info", "warning", "error"]
    title: str
    message: str
    watchlist_id: int | None = None
    job_id: int | None = None
    product_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    read_at: datetime | None = None


class ControlRepository:
    """Separate WAL connection for browsing, profile scores, and alerts."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "ControlRepository":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("control repository is not open")
        return self._connection

    async def open(self) -> None:
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        if not await self.list_profiles():
            await self.create_profile(ScoringProfileInput(name="Default", activate=True))

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def create_profile(self, values: ScoringProfileInput) -> ScoringProfile:
        now = _now()
        async with self._write_lock:
            if values.activate:
                await self.connection.execute("UPDATE scoring_profiles SET active = 0")
            cursor = await self.connection.execute(
                """
                INSERT INTO scoring_profiles(
                  name, active, price_weight, moq_weight, supplier_weight,
                  tier_weight, data_quality_weight, min_score_alert, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values.name,
                    int(values.activate),
                    values.price_weight,
                    values.moq_weight,
                    values.supplier_weight,
                    values.tier_weight,
                    values.data_quality_weight,
                    values.min_score_alert,
                    now,
                    now,
                ),
            )
            if not values.activate:
                row = await (
                    await self.connection.execute(
                        "SELECT COUNT(*) AS count FROM scoring_profiles WHERE active = 1"
                    )
                ).fetchone()
                if int(row["count"] or 0) == 0:
                    await self.connection.execute(
                        "UPDATE scoring_profiles SET active = 1 WHERE id = ?",
                        (cursor.lastrowid,),
                    )
            await self.connection.commit()
        return await self.get_profile(int(cursor.lastrowid))

    async def get_profile(self, profile_id: int) -> ScoringProfile:
        row = await (
            await self.connection.execute(
                "SELECT * FROM scoring_profiles WHERE id = ?", (profile_id,)
            )
        ).fetchone()
        if row is None:
            raise KeyError(f"scoring profile {profile_id} does not exist")
        return _profile(row)

    async def list_profiles(self) -> list[ScoringProfile]:
        rows = await (
            await self.connection.execute(
                "SELECT * FROM scoring_profiles ORDER BY active DESC, name COLLATE NOCASE"
            )
        ).fetchall()
        return [_profile(row) for row in rows]

    async def active_profile(self) -> ScoringProfile:
        row = await (
            await self.connection.execute(
                "SELECT * FROM scoring_profiles WHERE active = 1 ORDER BY id LIMIT 1"
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("no active scoring profile")
        return _profile(row)

    async def activate_profile(self, profile_id: int) -> ScoringProfile:
        await self.get_profile(profile_id)
        async with self._write_lock:
            await self.connection.execute("UPDATE scoring_profiles SET active = 0")
            await self.connection.execute(
                "UPDATE scoring_profiles SET active = 1, updated_at = ? WHERE id = ?",
                (_now(), profile_id),
            )
            await self.connection.commit()
        return await self.get_profile(profile_id)

    async def rescore(self, *, profile_id: int | None = None, job_id: int | None = None) -> int:
        profile = await (
            self.get_profile(profile_id) if profile_id is not None else self.active_profile()
        )
        rows = await self._product_rows(job_id)
        records = [
            (row["product_key"], ProductRecord.model_validate_json(row["record_json"]))
            for row in rows
        ]
        medians = _currency_medians(record for _, record in records)
        async with self._write_lock:
            for key, record in records:
                currency = record.price.currency if record.price else None
                score = score_product(
                    record,
                    peer_median_price=medians.get(currency),
                    weights=profile.weights(),
                )
                await self.connection.execute(
                    """
                    INSERT INTO profile_scores(
                      profile_id, product_key, job_id, score, price_value, moq_score,
                      supplier_confidence, tier_discount, data_quality, peer_median_price,
                      reasons_json, scored_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, product_key) DO UPDATE SET
                      job_id=excluded.job_id, score=excluded.score,
                      price_value=excluded.price_value, moq_score=excluded.moq_score,
                      supplier_confidence=excluded.supplier_confidence,
                      tier_discount=excluded.tier_discount, data_quality=excluded.data_quality,
                      peer_median_price=excluded.peer_median_price,
                      reasons_json=excluded.reasons_json, scored_at=excluded.scored_at
                    """,
                    (
                        profile.id,
                        key,
                        job_id,
                        score.total,
                        score.price_value,
                        score.moq,
                        score.supplier_confidence,
                        score.tier_discount,
                        score.data_quality,
                        str(score.peer_median_price) if score.peer_median_price else None,
                        json.dumps(score.reasons, ensure_ascii=False),
                        score.scored_at.astimezone(UTC).isoformat(),
                    ),
                )
            await self.connection.commit()
        return len(records)

    async def dashboard_summary(self) -> dict[str, Any]:
        profile = await self.active_profile()
        counts = {}
        for key, sql in (
            ("products", "SELECT COUNT(*) AS n FROM products"),
            ("suppliers", "SELECT COUNT(*) AS n FROM suppliers"),
            ("watchlists", "SELECT COUNT(*) AS n FROM watchlists WHERE enabled=1"),
            ("unread_alerts", "SELECT COUNT(*) AS n FROM alerts WHERE read_at IS NULL"),
            ("running_jobs", "SELECT COUNT(*) AS n FROM crawl_jobs WHERE status='running'"),
            (
                "changes_24h",
                "SELECT COUNT(*) AS n FROM product_changes "
                "WHERE datetime(detected_at) >= datetime('now','-1 day')",
            ),
        ):
            row = await (await self.connection.execute(sql)).fetchone()
            counts[key] = int(row["n"] or 0)
        row = await (
            await self.connection.execute(
                "SELECT MAX(score) AS score FROM profile_scores WHERE profile_id = ?",
                (profile.id,),
            )
        ).fetchone()
        return {
            **counts,
            "top_score": round(float(row["score"]), 2) if row["score"] is not None else None,
            "active_profile": profile.model_dump(mode="json"),
        }

    async def list_products(
        self,
        *,
        query: str | None = None,
        supplier_key: str | None = None,
        currency: str | None = None,
        min_score: float | None = None,
        max_price: Decimal | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        profile = await self.active_profile()
        joins = ["LEFT JOIN profile_scores ps ON ps.product_key=p.product_key AND ps.profile_id=?"]
        where = ["1=1"]
        params: list[Any] = [profile.name, profile.id]
        if supplier_key:
            joins.append("JOIN supplier_products sp ON sp.product_key=p.product_key")
            where.append("sp.supplier_key=?")
            params.append(supplier_key)
        if query:
            where.append("(p.title LIKE ? OR p.product_id LIKE ? OR p.supplier_name LIKE ?)")
            params.extend([f"%{query}%"] * 3)
        if currency:
            where.append("p.currency=?")
            params.append(currency.upper())
        if min_score is not None:
            where.append("COALESCE(ps.score,s.score,0)>=?")
            params.append(min_score)
        if max_price is not None:
            where.append("CAST(p.price_min AS REAL)<=?")
            params.append(float(max_price))
        params.extend([limit, offset])
        sql = f"""
        SELECT p.product_key,p.product_id,p.title,p.supplier_name,p.supplier_country,
               p.category,p.price_min,p.price_max,p.currency,p.moq,p.moq_unit,
               p.source_url,p.last_seen_at,COALESCE(ps.score,s.score) AS score,
               CASE WHEN ps.score IS NOT NULL THEN ? ELSE 'baseline' END AS score_profile
        FROM products p {' '.join(joins)}
        LEFT JOIN product_scores s ON s.product_key=p.product_key
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(ps.score,s.score,-1) DESC,p.last_seen_at DESC
        LIMIT ? OFFSET ?
        """
        rows = await (await self.connection.execute(sql, params)).fetchall()
        return [dict(row) for row in rows]

    async def get_product(self, identifier: str) -> dict[str, Any] | None:
        profile = await self.active_profile()
        row = await (
            await self.connection.execute(
                """
                SELECT p.*,COALESCE(ps.score,s.score) AS score,
                       ps.reasons_json AS profile_reasons,s.reasons_json AS baseline_reasons
                FROM products p
                LEFT JOIN profile_scores ps
                  ON ps.product_key=p.product_key AND ps.profile_id=?
                LEFT JOIN product_scores s ON s.product_key=p.product_key
                WHERE p.product_key=? OR p.product_id=? LIMIT 1
                """,
                (profile.id, identifier, identifier),
            )
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["record"] = json.loads(data.pop("record_json"))
        reasons = data.pop("profile_reasons") or data.pop("baseline_reasons")
        data["score_reasons"] = json.loads(reasons) if reasons else []
        data["score_profile"] = profile.name
        changes = await (
            await self.connection.execute(
                "SELECT * FROM product_changes WHERE product_key=? ORDER BY id DESC LIMIT 25",
                (data["product_key"],),
            )
        ).fetchall()
        data["changes"] = [dict(change) for change in changes]
        return data

    async def create_alert(
        self,
        *,
        kind: str,
        severity: Literal["info", "warning", "error"],
        title: str,
        message: str,
        watchlist_id: int | None = None,
        job_id: int | None = None,
        product_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AlertRecord:
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO alerts(kind,severity,title,message,watchlist_id,job_id,
                  product_key,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    kind,
                    severity,
                    title,
                    message,
                    watchlist_id,
                    job_id,
                    product_key,
                    json.dumps(payload or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            await self.connection.commit()
        return await self.get_alert(int(cursor.lastrowid))

    async def get_alert(self, alert_id: int) -> AlertRecord:
        row = await (
            await self.connection.execute("SELECT * FROM alerts WHERE id=?", (alert_id,))
        ).fetchone()
        if row is None:
            raise KeyError(f"alert {alert_id} does not exist")
        return _alert(row)

    async def list_alerts(
        self, *, unread_only: bool = False, limit: int = 100
    ) -> list[AlertRecord]:
        sql = "SELECT * FROM alerts"
        if unread_only:
            sql += " WHERE read_at IS NULL"
        sql += " ORDER BY id DESC LIMIT ?"
        rows = await (await self.connection.execute(sql, (limit,))).fetchall()
        return [_alert(row) for row in rows]

    async def mark_alert_read(self, alert_id: int) -> AlertRecord:
        await self.get_alert(alert_id)
        async with self._write_lock:
            await self.connection.execute(
                "UPDATE alerts SET read_at=? WHERE id=?", (_now(), alert_id)
            )
            await self.connection.commit()
        return await self.get_alert(alert_id)

    async def alert_for_watchlist_result(
        self,
        *,
        watchlist_id: int,
        watchlist_name: str,
        job_id: int | None,
        status: str,
        changes_count: int,
    ) -> AlertRecord | None:
        if status in {"failed", "completed_with_errors"}:
            return await self.create_alert(
                kind="watchlist_error",
                severity="error" if status == "failed" else "warning",
                title=f"Watchlist {watchlist_name} needs attention",
                message=f"Run finished with status {status}.",
                watchlist_id=watchlist_id,
                job_id=job_id,
            )
        if changes_count:
            return await self.create_alert(
                kind="watchlist_change",
                severity="info",
                title=f"{changes_count} changes in {watchlist_name}",
                message="Tracked product fields changed since the previous observation.",
                watchlist_id=watchlist_id,
                job_id=job_id,
                payload={"changes_count": changes_count},
            )
        return None

    async def alert_for_high_scores(self, job_id: int) -> AlertRecord | None:
        profile = await self.active_profile()
        rows = await (
            await self.connection.execute(
                """
                SELECT ps.product_key,ps.score,p.title
                FROM profile_scores ps JOIN products p ON p.product_key=ps.product_key
                WHERE ps.profile_id=? AND ps.job_id=? AND ps.score>=?
                ORDER BY ps.score DESC LIMIT 10
                """,
                (profile.id, job_id, profile.min_score_alert),
            )
        ).fetchall()
        if not rows:
            return None
        return await self.create_alert(
            kind="high_score",
            severity="info",
            title=f"{len(rows)} high-scoring sourcing candidates",
            message=f"Job {job_id} met the {profile.name} profile alert threshold.",
            job_id=job_id,
            payload={"profile_id": profile.id, "products": [dict(row) for row in rows]},
        )

    async def _product_rows(self, job_id: int | None) -> list[aiosqlite.Row]:
        if job_id is None:
            return list(
                await (
                    await self.connection.execute(
                        "SELECT product_key,record_json FROM products ORDER BY last_seen_at DESC"
                    )
                ).fetchall()
            )
        return list(
            await (
                await self.connection.execute(
                    """
                    SELECT DISTINCT p.product_key,p.record_json
                    FROM crawl_queue q JOIN products p
                      ON p.product_id=q.product_id OR p.source_url=q.product_url
                    WHERE q.job_id=? AND q.status='done'
                    """,
                    (job_id,),
                )
            ).fetchall()
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _profile(row: aiosqlite.Row) -> ScoringProfile:
    return ScoringProfile(
        id=int(row["id"]),
        name=row["name"],
        active=bool(row["active"]),
        price_weight=float(row["price_weight"]),
        moq_weight=float(row["moq_weight"]),
        supplier_weight=float(row["supplier_weight"]),
        tier_weight=float(row["tier_weight"]),
        data_quality_weight=float(row["data_quality_weight"]),
        min_score_alert=float(row["min_score_alert"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _alert(row: aiosqlite.Row) -> AlertRecord:
    return AlertRecord(
        id=int(row["id"]),
        kind=row["kind"],
        severity=row["severity"],
        title=row["title"],
        message=row["message"],
        watchlist_id=row["watchlist_id"],
        job_id=row["job_id"],
        product_key=row["product_key"],
        payload=json.loads(row["payload_json"] or "{}"),
        created_at=datetime.fromisoformat(row["created_at"]),
        read_at=datetime.fromisoformat(row["read_at"]) if row["read_at"] else None,
    )


def _currency_medians(records: Any) -> dict[str | None, Decimal]:
    prices: dict[str | None, list[Decimal]] = {}
    for record in records:
        if record.price and record.price.minimum is not None:
            prices.setdefault(record.price.currency, []).append(record.price.minimum)
    return {currency: median(values) for currency, values in prices.items() if values}
