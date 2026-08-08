# src/alibaba_scraper/database.py
"""Async SQLite persistence for products, history, and resumable crawl jobs."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .models import CrawlJob, CrawlSummary, ProductRecord, QueueItem

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS products (
    product_key TEXT PRIMARY KEY,
    product_id TEXT,
    source_url TEXT NOT NULL UNIQUE,
    canonical_url TEXT,
    title TEXT,
    supplier_name TEXT,
    supplier_url TEXT,
    supplier_country TEXT,
    category TEXT,
    price_min TEXT,
    price_max TEXT,
    currency TEXT,
    moq TEXT,
    moq_unit TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id);
CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_name);

CREATE TABLE IF NOT EXISTS product_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL REFERENCES products(product_key) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    price_min TEXT,
    price_max TEXT,
    currency TEXT,
    moq TEXT,
    moq_unit TEXT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_product_time
    ON product_observations(product_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    status TEXT NOT NULL,
    max_products INTEGER NOT NULL,
    max_search_pages INTEGER NOT NULL,
    next_search_page INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS crawl_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
    product_url TEXT NOT NULL,
    product_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, product_url)
);
CREATE INDEX IF NOT EXISTS idx_queue_job_status ON crawl_queue(job_id, status, id);
"""


class Database:
    """Single-connection async repository with serialized multi-statement transactions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._transaction_lock = asyncio.Lock()

    async def __aenter__(self) -> "Database":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("database is not open")
        return self._connection

    async def open(self) -> None:
        """Open and initialize the SQLite database without blocking the event loop."""
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def create_job(self, query: str, max_products: int, max_search_pages: int) -> int:
        now = _utcnow()
        cursor = await self.connection.execute(
            """
            INSERT INTO crawl_jobs(
                query, status, max_products, max_search_pages, next_search_page,
                created_at, updated_at
            ) VALUES (?, 'pending', ?, ?, 1, ?, ?)
            """,
            (query, max_products, max_search_pages, now, now),
        )
        await self.connection.commit()
        return int(cursor.lastrowid)

    async def get_job(self, job_id: int) -> CrawlJob:
        cursor = await self.connection.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"crawl job {job_id} does not exist")
        return _job_from_row(row)

    async def list_jobs(self, limit: int = 50) -> list[CrawlJob]:
        cursor = await self.connection.execute(
            "SELECT * FROM crawl_jobs ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_job_from_row(row) for row in await cursor.fetchall()]

    async def mark_job_running(self, job_id: int) -> None:
        now = _utcnow()
        await self.connection.execute(
            """
            UPDATE crawl_jobs
               SET status = 'running', updated_at = ?, completed_at = NULL
             WHERE id = ?
            """,
            (now, job_id),
        )
        await self.connection.execute(
            """
            UPDATE crawl_queue
               SET status = 'pending', updated_at = ?
             WHERE job_id = ? AND status = 'in_progress'
            """,
            (now, job_id),
        )
        await self.connection.commit()

    async def set_next_search_page(self, job_id: int, page: int) -> None:
        await self.connection.execute(
            "UPDATE crawl_jobs SET next_search_page = ?, updated_at = ? WHERE id = ?",
            (page, _utcnow(), job_id),
        )
        await self.connection.commit()

    async def enqueue(self, job_id: int, urls: list[tuple[str, str | None]]) -> int:
        if not urls:
            return 0
        now = _utcnow()
        before = self.connection.total_changes
        await self.connection.executemany(
            """
            INSERT OR IGNORE INTO crawl_queue(
                job_id, product_url, product_id, status, discovered_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            [(job_id, url, product_id, now, now) for url, product_id in urls],
        )
        await self.connection.commit()
        return self.connection.total_changes - before

    async def queue_count(self, job_id: int) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) AS count FROM crawl_queue WHERE job_id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        return int(row["count"])

    async def claim_pending(self, job_id: int, limit: int) -> list[QueueItem]:
        """Atomically claim a small batch so a crashed run can be safely resumed."""
        async with self._transaction_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self.connection.execute(
                    """
                    SELECT * FROM crawl_queue
                     WHERE job_id = ? AND status = 'pending'
                     ORDER BY id
                     LIMIT ?
                    """,
                    (job_id, limit),
                )
                rows = await cursor.fetchall()
                if not rows:
                    await self.connection.commit()
                    return []
                ids = [int(row["id"]) for row in rows]
                placeholders = ",".join("?" for _ in ids)
                now = _utcnow()
                await self.connection.execute(
                    f"""
                    UPDATE crawl_queue
                       SET status = 'in_progress', attempts = attempts + 1, updated_at = ?
                     WHERE id IN ({placeholders})
                    """,
                    (now, *ids),
                )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise

        return [
            QueueItem(
                id=int(row["id"]),
                job_id=int(row["job_id"]),
                product_url=str(row["product_url"]),
                product_id=row["product_id"],
                status="in_progress",
                attempts=int(row["attempts"]) + 1,
                last_error=row["last_error"],
            )
            for row in rows
        ]

    async def mark_queue_done(self, queue_id: int) -> None:
        await self.connection.execute(
            """
            UPDATE crawl_queue
               SET status = 'done', last_error = NULL, updated_at = ?
             WHERE id = ?
            """,
            (_utcnow(), queue_id),
        )
        await self.connection.commit()

    async def mark_queue_error(self, queue_id: int, error: str) -> None:
        await self.connection.execute(
            "UPDATE crawl_queue SET status = 'error', last_error = ?, updated_at = ? WHERE id = ?",
            (error[:2000], _utcnow(), queue_id),
        )
        await self.connection.commit()

    async def upsert_product(self, record: ProductRecord) -> str:
        """Upsert current product state and append history only when tracked values change."""
        product_key = _product_key(record)
        now = record.scraped_at.astimezone(UTC).isoformat()
        record_json = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        price_min = _string_decimal(record.price.minimum if record.price else None)
        price_max = _string_decimal(record.price.maximum if record.price else None)
        currency = record.price.currency if record.price else None
        moq = _string_decimal(record.minimum_order_quantity)

        async with self._transaction_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self.connection.execute(
                    "SELECT first_seen_at FROM products WHERE product_key = ?", (product_key,)
                )
                existing = await cursor.fetchone()
                first_seen = existing["first_seen_at"] if existing else now
                await self.connection.execute(
                    """
                    INSERT INTO products(
                        product_key, product_id, source_url, canonical_url, title,
                        supplier_name, supplier_url, supplier_country, category,
                        price_min, price_max, currency, moq, moq_unit,
                        first_seen_at, last_seen_at, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_key) DO UPDATE SET
                        product_id = excluded.product_id,
                        source_url = excluded.source_url,
                        canonical_url = excluded.canonical_url,
                        title = excluded.title,
                        supplier_name = excluded.supplier_name,
                        supplier_url = excluded.supplier_url,
                        supplier_country = excluded.supplier_country,
                        category = excluded.category,
                        price_min = excluded.price_min,
                        price_max = excluded.price_max,
                        currency = excluded.currency,
                        moq = excluded.moq,
                        moq_unit = excluded.moq_unit,
                        last_seen_at = excluded.last_seen_at,
                        record_json = excluded.record_json
                    """,
                    (
                        product_key,
                        record.product_id,
                        str(record.source_url),
                        str(record.canonical_url) if record.canonical_url else None,
                        record.title,
                        record.supplier_name,
                        str(record.supplier_url) if record.supplier_url else None,
                        record.supplier_country,
                        record.category,
                        price_min,
                        price_max,
                        currency,
                        moq,
                        record.minimum_order_unit,
                        first_seen,
                        now,
                        record_json,
                    ),
                )

                latest_cursor = await self.connection.execute(
                    """
                    SELECT price_min, price_max, currency, moq, moq_unit
                      FROM product_observations
                     WHERE product_key = ?
                     ORDER BY id DESC
                     LIMIT 1
                    """,
                    (product_key,),
                )
                latest = await latest_cursor.fetchone()
                tracked = (price_min, price_max, currency, moq, record.minimum_order_unit)
                tracked_keys = ("price_min", "price_max", "currency", "moq", "moq_unit")
                latest_tracked = tuple(latest[key] for key in tracked_keys) if latest else None
                if latest_tracked != tracked:
                    await self.connection.execute(
                        """
                        INSERT INTO product_observations(
                            product_key, observed_at, price_min, price_max,
                            currency, moq, moq_unit, record_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (product_key, now, *tracked, record_json),
                    )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise
        return product_key

    async def product_history(self, product_id_or_key: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT product_key FROM products
             WHERE product_key = ? OR product_id = ?
             ORDER BY last_seen_at DESC LIMIT 1
            """,
            (product_id_or_key, product_id_or_key),
        )
        row = await cursor.fetchone()
        if row is None:
            return []
        history_cursor = await self.connection.execute(
            """
            SELECT observed_at, price_min, price_max, currency, moq, moq_unit
              FROM product_observations
             WHERE product_key = ?
             ORDER BY id
            """,
            (row["product_key"],),
        )
        return [dict(item) for item in await history_cursor.fetchall()]

    async def summary(self, job_id: int) -> CrawlSummary:
        job = await self.get_job(job_id)
        cursor = await self.connection.execute(
            """
            SELECT
                COUNT(*) AS discovered,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                SUM(CASE WHEN status IN ('pending','in_progress') THEN 1 ELSE 0 END) AS pending
            FROM crawl_queue WHERE job_id = ?
            """,
            (job_id,),
        )
        row = await cursor.fetchone()
        return CrawlSummary(
            job_id=job.id,
            query=job.query,
            status=job.status,
            discovered=int(row["discovered"] or 0),
            completed=int(row["completed"] or 0),
            errors=int(row["errors"] or 0),
            pending=int(row["pending"] or 0),
        )

    async def finish_job(self, job_id: int) -> CrawlSummary:
        current = await self.summary(job_id)
        status = "completed_with_errors" if current.errors else "completed"
        now = _utcnow()
        await self.connection.execute(
            "UPDATE crawl_jobs SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (status, now, now, job_id),
        )
        await self.connection.commit()
        return await self.summary(job_id)

    async def fail_job(self, job_id: int) -> None:
        now = _utcnow()
        await self.connection.execute(
            """
            UPDATE crawl_jobs
               SET status = 'failed', updated_at = ?, completed_at = ?
             WHERE id = ?
            """,
            (now, now, job_id),
        )
        await self.connection.commit()


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _job_from_row(row: aiosqlite.Row) -> CrawlJob:
    return CrawlJob(
        id=int(row["id"]),
        query=str(row["query"]),
        status=row["status"],
        max_products=int(row["max_products"]),
        max_search_pages=int(row["max_search_pages"]),
        next_search_page=int(row["next_search_page"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )


def _product_key(record: ProductRecord) -> str:
    if record.product_id:
        return f"alibaba:{record.product_id}"
    canonical = str(record.canonical_url or record.source_url)
    return f"url:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _string_decimal(value: Any) -> str | None:
    return str(value) if value is not None else None
