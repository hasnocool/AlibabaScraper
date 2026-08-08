# src/alibaba_scraper/intelligence.py
"""Async supplier, change-tracking, watchlist, and sourcing-intelligence storage."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

import aiosqlite

from .models import (
    ProductChange,
    ProductRecord,
    SourcingScore,
    SupplierRecord,
    Watchlist,
    WatchlistRun,
)
from .scoring import score_product

INTELLIGENCE_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT,
    country TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

CREATE TABLE IF NOT EXISTS supplier_products (
    supplier_key TEXT NOT NULL REFERENCES suppliers(supplier_key) ON DELETE CASCADE,
    product_key TEXT NOT NULL REFERENCES products(product_key) ON DELETE CASCADE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(supplier_key, product_key)
);
CREATE INDEX IF NOT EXISTS idx_supplier_products_product ON supplier_products(product_key);

CREATE TABLE IF NOT EXISTS product_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL REFERENCES products(product_key) ON DELETE CASCADE,
    job_id INTEGER,
    detected_at TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE INDEX IF NOT EXISTS idx_product_changes_product_time
    ON product_changes(product_key, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_changes_job ON product_changes(job_id, id);

CREATE TABLE IF NOT EXISTS product_scores (
    product_key TEXT PRIMARY KEY REFERENCES products(product_key) ON DELETE CASCADE,
    job_id INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_product_scores_score ON product_scores(score DESC);

CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_minutes INTEGER NOT NULL,
    max_products INTEGER NOT NULL,
    max_search_pages INTEGER NOT NULL,
    last_run_at TEXT,
    next_run_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_watchlists_due ON watchlists(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS watchlist_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    job_id INTEGER,
    status TEXT NOT NULL,
    changes_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_watchlist_runs_watchlist
    ON watchlist_runs(watchlist_id, id DESC);
"""

TRACKED_FIELDS = (
    "title",
    "supplier_name",
    "supplier_country",
    "category",
    "price.minimum",
    "price.maximum",
    "price.currency",
    "minimum_order_quantity",
    "minimum_order_unit",
    "attributes",
)


class IntelligenceRepository:
    """Second WAL connection dedicated to derived catalog and watchlist state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "IntelligenceRepository":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("intelligence repository is not open")
        return self._connection

    async def open(self) -> None:
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(INTELLIGENCE_SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def previous_record(self, record: ProductRecord) -> ProductRecord | None:
        clauses = ["source_url = ?"]
        params: list[str] = [str(record.source_url)]
        if record.product_id:
            clauses.append("product_id = ?")
            params.append(record.product_id)
        if record.canonical_url:
            clauses.append("canonical_url = ?")
            params.append(str(record.canonical_url))
        cursor = await self.connection.execute(
            f"SELECT record_json FROM products WHERE {' OR '.join(clauses)} LIMIT 1",
            params,
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ProductRecord.model_validate_json(row["record_json"])

    async def record_product(
        self,
        record: ProductRecord,
        product_key: str,
        *,
        previous: ProductRecord | None,
        job_id: int | None,
    ) -> list[ProductChange]:
        changes = _diff_records(previous, record, product_key, job_id)
        now = record.scraped_at.astimezone(UTC).isoformat()
        async with self._write_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                await self._sync_supplier(record, product_key, now)
                if changes:
                    await self.connection.executemany(
                        """
                        INSERT INTO product_changes(
                            product_key, job_id, detected_at, field, old_value, new_value
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                change.product_key,
                                change.job_id,
                                change.detected_at.astimezone(UTC).isoformat(),
                                change.field,
                                change.old_value,
                                change.new_value,
                            )
                            for change in changes
                        ],
                    )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise
        return changes

    async def rescore_job(self, job_id: int) -> list[SourcingScore]:
        rows = await self._job_product_rows(job_id)
        records = [
            (row["product_key"], ProductRecord.model_validate_json(row["record_json"]))
            for row in rows
        ]
        medians = _currency_medians(record for _, record in records)
        scored: list[SourcingScore] = []
        async with self._write_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                for product_key, record in records:
                    currency = record.price.currency if record.price else None
                    result = score_product(record, peer_median_price=medians.get(currency))
                    result.product_key = product_key
                    result.job_id = job_id
                    await self._save_score(result)
                    scored.append(result)
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise
        return scored

    async def top_scores(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT s.*, p.product_id, p.title, p.supplier_name, p.currency,
                   p.price_min, p.price_max, p.moq, p.moq_unit, p.source_url
              FROM product_scores s
              JOIN products p ON p.product_key = s.product_key
             ORDER BY s.score DESC, p.last_seen_at DESC
             LIMIT ?
            """,
            (limit,),
        )
        return [_score_row(row) for row in await cursor.fetchall()]

    async def list_suppliers(self, limit: int = 100) -> list[SupplierRecord]:
        cursor = await self.connection.execute(
            """
            SELECT s.*, COUNT(sp.product_key) AS product_count
              FROM suppliers s
              LEFT JOIN supplier_products sp ON sp.supplier_key = s.supplier_key
             GROUP BY s.supplier_key
             ORDER BY product_count DESC, s.last_seen_at DESC
             LIMIT ?
            """,
            (limit,),
        )
        return [_supplier_row(row) for row in await cursor.fetchall()]

    async def supplier_products(self, supplier_key: str, limit: int = 100) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT p.product_key, p.product_id, p.title, p.price_min, p.price_max,
                   p.currency, p.moq, p.moq_unit, p.source_url, p.last_seen_at
              FROM supplier_products sp
              JOIN products p ON p.product_key = sp.product_key
             WHERE sp.supplier_key = ?
             ORDER BY p.last_seen_at DESC
             LIMIT ?
            """,
            (supplier_key, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_changes(
        self,
        *,
        job_id: int | None = None,
        limit: int = 100,
    ) -> list[ProductChange]:
        if job_id is None:
            cursor = await self.connection.execute(
                "SELECT * FROM product_changes ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = await self.connection.execute(
                "SELECT * FROM product_changes WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                (job_id, limit),
            )
        return [_change_row(row) for row in await cursor.fetchall()]

    async def count_job_changes(self, job_id: int) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) AS count FROM product_changes WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        return int(row["count"] or 0)

    async def create_watchlist(
        self,
        name: str,
        query: str,
        *,
        interval_minutes: int = 1440,
        max_products: int = 50,
        max_search_pages: int = 5,
    ) -> int:
        if interval_minutes < 1:
            raise ValueError("interval_minutes must be >= 1")
        now = datetime.now(UTC)
        stamp = now.isoformat()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO watchlists(
                    name, query, enabled, interval_minutes, max_products,
                    max_search_pages, next_run_at, created_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    query,
                    interval_minutes,
                    max_products,
                    max_search_pages,
                    stamp,
                    stamp,
                    stamp,
                ),
            )
            await self.connection.commit()
        return int(cursor.lastrowid)

    async def get_watchlist(self, watchlist_id: int) -> Watchlist:
        cursor = await self.connection.execute(
            "SELECT * FROM watchlists WHERE id = ?",
            (watchlist_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"watchlist {watchlist_id} does not exist")
        return _watchlist_row(row)

    async def list_watchlists(self, limit: int = 100) -> list[Watchlist]:
        cursor = await self.connection.execute(
            "SELECT * FROM watchlists ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [_watchlist_row(row) for row in await cursor.fetchall()]

    async def due_watchlists(self, limit: int = 25) -> list[Watchlist]:
        cursor = await self.connection.execute(
            """
            SELECT * FROM watchlists
             WHERE enabled = 1 AND next_run_at <= ?
             ORDER BY next_run_at, id
             LIMIT ?
            """,
            (datetime.now(UTC).isoformat(), limit),
        )
        return [_watchlist_row(row) for row in await cursor.fetchall()]

    async def set_watchlist_enabled(self, watchlist_id: int, enabled: bool) -> None:
        async with self._write_lock:
            await self.connection.execute(
                "UPDATE watchlists SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), datetime.now(UTC).isoformat(), watchlist_id),
            )
            await self.connection.commit()

    async def begin_watchlist_run(self, watchlist_id: int) -> int:
        now = datetime.now(UTC).isoformat()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO watchlist_runs(watchlist_id, status, changes_count, started_at)
                VALUES (?, 'running', 0, ?)
                """,
                (watchlist_id, now),
            )
            await self.connection.commit()
        return int(cursor.lastrowid)

    async def finish_watchlist_run(
        self,
        run_id: int,
        watchlist: Watchlist,
        *,
        job_id: int | None,
        status: str,
        changes_count: int,
    ) -> WatchlistRun:
        now = datetime.now(UTC)
        next_run = now + timedelta(minutes=watchlist.interval_minutes)
        async with self._write_lock:
            await self.connection.execute(
                """
                UPDATE watchlist_runs
                   SET job_id = ?, status = ?, changes_count = ?, completed_at = ?
                 WHERE id = ?
                """,
                (job_id, status, changes_count, now.isoformat(), run_id),
            )
            await self.connection.execute(
                """
                UPDATE watchlists
                   SET last_run_at = ?, next_run_at = ?, updated_at = ?
                 WHERE id = ?
                """,
                (now.isoformat(), next_run.isoformat(), now.isoformat(), watchlist.id),
            )
            await self.connection.commit()
        return await self.get_watchlist_run(run_id)

    async def get_watchlist_run(self, run_id: int) -> WatchlistRun:
        cursor = await self.connection.execute(
            "SELECT * FROM watchlist_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"watchlist run {run_id} does not exist")
        return _watchlist_run_row(row)

    async def _sync_supplier(self, record: ProductRecord, product_key: str, now: str) -> None:
        if not record.supplier_name:
            return
        supplier_key = _supplier_key(record)
        metadata = json.dumps(
            {
                "name": record.supplier_name,
                "url": str(record.supplier_url) if record.supplier_url else None,
                "country": record.supplier_country,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        await self.connection.execute(
            """
            INSERT INTO suppliers(
                supplier_key, name, url, country, first_seen_at, last_seen_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(supplier_key) DO UPDATE SET
                name = excluded.name,
                url = COALESCE(excluded.url, suppliers.url),
                country = COALESCE(excluded.country, suppliers.country),
                last_seen_at = excluded.last_seen_at,
                metadata_json = excluded.metadata_json
            """,
            (
                supplier_key,
                record.supplier_name,
                str(record.supplier_url) if record.supplier_url else None,
                record.supplier_country,
                now,
                now,
                metadata,
            ),
        )
        await self.connection.execute(
            """
            INSERT INTO supplier_products(supplier_key, product_key, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(supplier_key, product_key) DO UPDATE SET
                last_seen_at = excluded.last_seen_at
            """,
            (supplier_key, product_key, now, now),
        )

    async def _job_product_rows(self, job_id: int) -> list[aiosqlite.Row]:
        cursor = await self.connection.execute(
            """
            SELECT DISTINCT p.product_key, p.record_json
              FROM crawl_queue q
              JOIN products p
                ON (p.product_id = q.product_id AND q.product_id IS NOT NULL)
                OR p.source_url = q.product_url
                OR p.canonical_url = q.product_url
             WHERE q.job_id = ? AND q.status = 'done'
            """,
            (job_id,),
        )
        return list(await cursor.fetchall())

    async def _save_score(self, result: SourcingScore) -> None:
        assert result.product_key is not None
        await self.connection.execute(
            """
            INSERT INTO product_scores(
                product_key, job_id, score, price_value, moq_score,
                supplier_confidence, tier_discount, data_quality,
                peer_median_price, reasons_json, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_key) DO UPDATE SET
                job_id = excluded.job_id,
                score = excluded.score,
                price_value = excluded.price_value,
                moq_score = excluded.moq_score,
                supplier_confidence = excluded.supplier_confidence,
                tier_discount = excluded.tier_discount,
                data_quality = excluded.data_quality,
                peer_median_price = excluded.peer_median_price,
                reasons_json = excluded.reasons_json,
                scored_at = excluded.scored_at
            """,
            (
                result.product_key,
                result.job_id,
                result.total,
                result.price_value,
                result.moq,
                result.supplier_confidence,
                result.tier_discount,
                result.data_quality,
                str(result.peer_median_price) if result.peer_median_price is not None else None,
                json.dumps(result.reasons, ensure_ascii=False),
                result.scored_at.astimezone(UTC).isoformat(),
            ),
        )


def _diff_records(
    previous: ProductRecord | None,
    current: ProductRecord,
    product_key: str,
    job_id: int | None,
) -> list[ProductChange]:
    if previous is None:
        return []
    changes: list[ProductChange] = []
    now = current.scraped_at.astimezone(UTC)
    for field in TRACKED_FIELDS:
        old_value = _field_value(previous, field)
        new_value = _field_value(current, field)
        if old_value == new_value:
            continue
        changes.append(
            ProductChange(
                product_key=product_key,
                job_id=job_id,
                field=field,
                old_value=_serialize_value(old_value),
                new_value=_serialize_value(new_value),
                detected_at=now,
            )
        )
    return changes


def _field_value(record: ProductRecord, field: str) -> Any:
    value: Any = record
    for part in field.split("."):
        if value is None:
            return None
        value = getattr(value, part)
    return value


def _serialize_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _supplier_key(record: ProductRecord) -> str:
    if record.supplier_url:
        raw = str(record.supplier_url).rstrip("/").lower()
    else:
        raw = f"{record.supplier_name or ''}|{record.supplier_country or ''}".strip().lower()
    return f"supplier:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _currency_medians(records: Any) -> dict[str | None, Decimal]:
    grouped: dict[str | None, list[Decimal]] = {}
    for record in records:
        if not record.price or record.price.minimum is None:
            continue
        grouped.setdefault(record.price.currency, []).append(record.price.minimum)
    return {currency: median(values) for currency, values in grouped.items() if values}


def _supplier_row(row: aiosqlite.Row) -> SupplierRecord:
    return SupplierRecord(
        supplier_key=row["supplier_key"],
        name=row["name"],
        url=row["url"],
        country=row["country"],
        product_count=int(row["product_count"] or 0),
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
    )


def _change_row(row: aiosqlite.Row) -> ProductChange:
    return ProductChange(
        id=int(row["id"]),
        product_key=row["product_key"],
        job_id=row["job_id"],
        field=row["field"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        detected_at=datetime.fromisoformat(row["detected_at"]),
    )


def _watchlist_row(row: aiosqlite.Row) -> Watchlist:
    return Watchlist(
        id=int(row["id"]),
        name=row["name"],
        query=row["query"],
        enabled=bool(row["enabled"]),
        interval_minutes=int(row["interval_minutes"]),
        max_products=int(row["max_products"]),
        max_search_pages=int(row["max_search_pages"]),
        last_run_at=datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None,
        next_run_at=datetime.fromisoformat(row["next_run_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _watchlist_run_row(row: aiosqlite.Row) -> WatchlistRun:
    return WatchlistRun(
        id=int(row["id"]),
        watchlist_id=int(row["watchlist_id"]),
        job_id=int(row["job_id"]) if row["job_id"] is not None else None,
        status=row["status"],
        changes_count=int(row["changes_count"] or 0),
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )


def _score_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "product_key": row["product_key"],
        "product_id": row["product_id"],
        "title": row["title"],
        "supplier_name": row["supplier_name"],
        "score": row["score"],
        "price_value": row["price_value"],
        "moq_score": row["moq_score"],
        "supplier_confidence": row["supplier_confidence"],
        "tier_discount": row["tier_discount"],
        "data_quality": row["data_quality"],
        "peer_median_price": row["peer_median_price"],
        "currency": row["currency"],
        "price_min": row["price_min"],
        "price_max": row["price_max"],
        "moq": row["moq"],
        "moq_unit": row["moq_unit"],
        "source_url": row["source_url"],
        "reasons": json.loads(row["reasons_json"]),
        "scored_at": row["scored_at"],
    }
