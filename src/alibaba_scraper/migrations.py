# src/alibaba_scraper/migrations.py
"""Transactional SQLite schema migrations for production-operation features."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        1,
        "production_operations",
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL UNIQUE,
            key_hash TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            expires_at TEXT,
            revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);

        CREATE TABLE IF NOT EXISTS landed_cost_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            product_key TEXT,
            input_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_landed_scenarios_product
            ON landed_cost_scenarios(product_key, updated_at DESC);

        CREATE TABLE IF NOT EXISTS category_scoring_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_pattern TEXT NOT NULL UNIQUE,
            profile_id INTEGER NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_category_bindings_priority
            ON category_scoring_bindings(enabled, priority DESC, id);

        CREATE TABLE IF NOT EXISTS category_profile_scores (
            product_key TEXT PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            category TEXT,
            score REAL NOT NULL,
            price_value REAL NOT NULL,
            moq_score REAL NOT NULL,
            supplier_confidence REAL NOT NULL,
            tier_discount REAL NOT NULL,
            data_quality REAL NOT NULL,
            peer_median_price TEXT,
            reasons_json TEXT NOT NULL,
            scored_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_category_scores_rank
            ON category_profile_scores(profile_id, score DESC);

        CREATE TABLE IF NOT EXISTS alert_sinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            secret TEXT,
            headers_json TEXT NOT NULL,
            event_kinds_json TEXT NOT NULL,
            minimum_severity TEXT NOT NULL DEFAULT 'info',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL,
            sink_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempt_at TEXT,
            delivered_at TEXT,
            UNIQUE(alert_id, sink_id)
        );
        CREATE INDEX IF NOT EXISTS idx_alert_deliveries_status
            ON alert_deliveries(status, id);
        """,
    ),
    Migration(
        2,
        "operational_resilience",
        """
        ALTER TABLE api_keys ADD COLUMN kind TEXT NOT NULL DEFAULT 'persistent';
        ALTER TABLE api_keys ADD COLUMN parent_key_id INTEGER;
        ALTER TABLE api_keys ADD COLUMN rotated_from_id INTEGER;
        ALTER TABLE api_keys ADD COLUMN rotated_to_id INTEGER;

        ALTER TABLE alert_sinks ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5;
        ALTER TABLE alert_sinks ADD COLUMN base_backoff_seconds REAL NOT NULL DEFAULT 30;
        ALTER TABLE alert_sinks ADD COLUMN max_backoff_seconds REAL NOT NULL DEFAULT 3600;

        ALTER TABLE alert_deliveries ADD COLUMN next_attempt_at TEXT;
        ALTER TABLE alert_deliveries ADD COLUMN dead_lettered_at TEXT;
        CREATE INDEX IF NOT EXISTS idx_alert_deliveries_retry
            ON alert_deliveries(status,next_attempt_at,dead_lettered_at);

        CREATE TABLE IF NOT EXISTS supplier_quality_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_key TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            product_count INTEGER NOT NULL,
            scored_products INTEGER NOT NULL,
            avg_score REAL NOT NULL,
            completeness_pct REAL NOT NULL,
            changes_30d INTEGER NOT NULL,
            stability_score REAL NOT NULL,
            catalog_breadth_score REAL NOT NULL,
            quality_score REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_supplier_quality_history
            ON supplier_quality_snapshots(supplier_key,observed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_supplier_quality_rank
            ON supplier_quality_snapshots(quality_score DESC,observed_at DESC);
        """,
    ),
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version


async def migrate_database(path: Path | str) -> list[int]:
    """Apply missing migrations transactionally and return applied versions."""
    database_path = Path(path)
    await asyncio.to_thread(database_path.parent.mkdir, parents=True, exist_ok=True)
    connection = await aiosqlite.connect(database_path)
    connection.row_factory = aiosqlite.Row
    applied: list[int] = []
    try:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA journal_mode = WAL")
        await connection.execute("PRAGMA busy_timeout = 5000")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        await connection.commit()
        rows = await (await connection.execute("SELECT version FROM schema_migrations")).fetchall()
        existing = {int(row["version"]) for row in rows}
        for migration in MIGRATIONS:
            if migration.version in existing:
                continue
            applied_at = datetime.now(UTC).isoformat().replace("'", "''")
            name = migration.name.replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                + migration.sql
                + "\nINSERT INTO schema_migrations(version,name,applied_at) VALUES("
                + f"{migration.version},'{name}','{applied_at}');\nCOMMIT;"
            )
            try:
                await connection.executescript(script)
            except Exception:
                await connection.rollback()
                raise
            applied.append(migration.version)
    finally:
        await connection.close()
    return applied


async def schema_version(path: Path | str) -> int:
    """Return the highest applied migration version, or zero for an unmigrated DB."""
    database_path = Path(path)
    if not await asyncio.to_thread(database_path.exists):
        return 0
    connection = await aiosqlite.connect(database_path)
    try:
        row = await (
            await connection.execute("SELECT MAX(version) FROM schema_migrations")
        ).fetchone()
    except aiosqlite.OperationalError:
        return 0
    finally:
        await connection.close()
    return int(row[0] or 0)
