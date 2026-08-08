from pathlib import Path

import aiosqlite

from alibaba_scraper.migrations import CURRENT_SCHEMA_VERSION, migrate_database, schema_version


async def test_migrations_are_idempotent_and_versioned(tmp_path: Path) -> None:
    path = tmp_path / "migrations.sqlite3"
    assert await migrate_database(path) == [1, 2]
    assert await migrate_database(path) == []
    assert await schema_version(path) == CURRENT_SCHEMA_VERSION == 2

    async with aiosqlite.connect(path) as connection:
        rows = await (
            await connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ).fetchall()
    names = {row[0] for row in rows}
    assert "schema_migrations" in names
    assert "api_keys" in names
    assert "landed_cost_scenarios" in names
    assert "category_scoring_bindings" in names
    assert "alert_sinks" in names
    assert "supplier_quality_snapshots" in names
