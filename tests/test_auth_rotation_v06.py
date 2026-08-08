from pathlib import Path

import pytest

from alibaba_scraper.production import ProductionRepository


async def test_api_key_rotation_and_short_lived_tokens(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    async with ProductionRepository(path) as production:
        original = await production.create_api_key("admin", ["admin"])
        rotated = await production.rotate_api_key(original.record.id, grace_minutes=0)
        old = await production.get_api_key(original.record.id)
        assert old.enabled is False
        assert old.rotated_to_id == rotated.record.id
        assert rotated.record.rotated_from_id == original.record.id
        assert await production.authenticate(original.api_key) is None
        assert await production.authenticate(rotated.api_key) is not None

        token = await production.mint_short_lived_token(
            rotated.record.id,
            ttl_minutes=5,
            scopes=["read"],
        )
        assert token.record.kind == "token"
        assert token.record.parent_key_id == rotated.record.id
        assert token.record.expires_at is not None
        principal = await production.authenticate(token.api_key)
        assert principal is not None and principal.scopes == ["read"]

        reader = await production.create_api_key("reader", ["read"])
        with pytest.raises(ValueError, match="cannot exceed"):
            await production.mint_short_lived_token(
                reader.record.id,
                scopes=["write"],
            )
