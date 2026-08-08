# src/alibaba_scraper/resilience.py
"""Operational resilience repository: targeted retries and supplier-quality history."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .migrations import migrate_database


class ResilienceRepository:
    """Resilience operations that use a dedicated WAL connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "ResilienceRepository":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("resilience repository is not open")
        return self._connection

    async def open(self) -> None:
        await migrate_database(self.path)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA busy_timeout = 5000")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def list_failed_queue(
        self,
        job_id: int,
        *,
        error_contains: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ["job_id=?", "status='error'"]
        params: list[Any] = [job_id]
        if error_contains:
            where.append("last_error LIKE ?")
            params.append(f"%{error_contains}%")
        params.append(limit)
        rows = await (
            await self.connection.execute(
                f"""
                SELECT id,job_id,product_url,product_id,status,attempts,last_error,updated_at
                FROM crawl_queue
                WHERE {' AND '.join(where)}
                ORDER BY id
                LIMIT ?
                """,
                params,
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def retry_failed_queue(
        self,
        job_id: int,
        *,
        queue_ids: list[int] | None = None,
        error_contains: str | None = None,
        limit: int = 100,
        reset_attempts: bool = False,
    ) -> dict[str, Any]:
        """Move selected error rows back to pending when the job is not actively running."""
        now = _now()
        async with self._write_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                job = await (
                    await self.connection.execute(
                        "SELECT id,status FROM crawl_jobs WHERE id=?", (job_id,)
                    )
                ).fetchone()
                if job is None:
                    raise KeyError(f"crawl job {job_id} does not exist")
                if job["status"] == "running":
                    raise RuntimeError("cannot retry queue rows while the crawl job is running")

                where = ["job_id=?", "status='error'"]
                params: list[Any] = [job_id]
                if queue_ids:
                    placeholders = ",".join("?" for _ in queue_ids)
                    where.append(f"id IN ({placeholders})")
                    params.extend(queue_ids)
                if error_contains:
                    where.append("last_error LIKE ?")
                    params.append(f"%{error_contains}%")
                params.append(limit)
                rows = await (
                    await self.connection.execute(
                        f"SELECT id FROM crawl_queue WHERE {' AND '.join(where)} "
                        "ORDER BY id LIMIT ?",
                        params,
                    )
                ).fetchall()
                ids = [int(row["id"]) for row in rows]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    attempts_sql = ", attempts=0" if reset_attempts else ""
                    await self.connection.execute(
                        f"""
                        UPDATE crawl_queue
                        SET status='pending',last_error=NULL,updated_at=?{attempts_sql}
                        WHERE id IN ({placeholders})
                        """,
                        (now, *ids),
                    )
                    await self.connection.execute(
                        """
                        UPDATE crawl_jobs
                        SET status='pending',updated_at=?,completed_at=NULL
                        WHERE id=?
                        """,
                        (now, job_id),
                    )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise
        return {"job_id": job_id, "retried": len(ids), "queue_ids": ids}

    async def snapshot_supplier_quality(self) -> list[dict[str, Any]]:
        """Persist observed-data supplier quality snapshots; not a trust/reputation claim."""
        suppliers = await (
            await self.connection.execute(
                "SELECT supplier_key,name FROM suppliers ORDER BY supplier_key"
            )
        ).fetchall()
        snapshots: list[dict[str, Any]] = []
        async with self._write_lock:
            for supplier in suppliers:
                metrics = await self._supplier_metrics(str(supplier["supplier_key"]))
                metrics["supplier_name"] = supplier["name"]
                metrics["observed_at"] = _now()
                await self.connection.execute(
                    """
                    INSERT INTO supplier_quality_snapshots(
                        supplier_key,observed_at,product_count,scored_products,avg_score,
                        completeness_pct,changes_30d,stability_score,catalog_breadth_score,
                        quality_score
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        metrics["supplier_key"],
                        metrics["observed_at"],
                        metrics["product_count"],
                        metrics["scored_products"],
                        metrics["avg_score"],
                        metrics["completeness_pct"],
                        metrics["changes_30d"],
                        metrics["stability_score"],
                        metrics["catalog_breadth_score"],
                        metrics["quality_score"],
                    ),
                )
                snapshots.append(metrics)
            await self.connection.commit()
        return snapshots

    async def list_supplier_quality(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                """
                SELECT q.*,s.name AS supplier_name
                FROM supplier_quality_snapshots q
                JOIN suppliers s ON s.supplier_key=q.supplier_key
                WHERE q.id IN (
                    SELECT MAX(id) FROM supplier_quality_snapshots GROUP BY supplier_key
                )
                ORDER BY q.quality_score DESC,q.id DESC LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def supplier_quality_history(
        self, supplier_key: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                """
                SELECT * FROM supplier_quality_snapshots
                WHERE supplier_key=? ORDER BY id DESC LIMIT ?
                """,
                (supplier_key, limit),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def _supplier_metrics(self, supplier_key: str) -> dict[str, Any]:
        row = await (
            await self.connection.execute(
                """
                SELECT COUNT(DISTINCT p.product_key) AS product_count,
                       COUNT(DISTINCT ps.product_key) AS scored_products,
                       AVG(ps.score) AS avg_score,
                       AVG(CASE WHEN p.supplier_country IS NOT NULL
                                     AND p.category IS NOT NULL
                                     AND p.price_min IS NOT NULL
                                     AND p.moq IS NOT NULL
                                THEN 100.0 ELSE 0.0 END) AS completeness_pct
                FROM supplier_products sp
                JOIN products p ON p.product_key=sp.product_key
                LEFT JOIN product_scores ps ON ps.product_key=p.product_key
                WHERE sp.supplier_key=?
                """,
                (supplier_key,),
            )
        ).fetchone()
        changes = await (
            await self.connection.execute(
                """
                SELECT COUNT(*) AS changes
                FROM product_changes pc
                JOIN supplier_products sp ON sp.product_key=pc.product_key
                WHERE sp.supplier_key=?
                  AND datetime(pc.detected_at) >= datetime('now','-30 days')
                """,
                (supplier_key,),
            )
        ).fetchone()
        product_count = int(row["product_count"] or 0)
        scored_products = int(row["scored_products"] or 0)
        avg_score = float(row["avg_score"] or 50.0)
        completeness = float(row["completeness_pct"] or 0.0)
        changes_30d = int(changes["changes"] or 0)
        stability = max(0.0, 100.0 - (changes_30d / max(product_count, 1)) * 10.0)
        breadth = min(100.0, product_count * 10.0)
        quality = avg_score * 0.45 + completeness * 0.25 + stability * 0.20 + breadth * 0.10
        return {
            "supplier_key": supplier_key,
            "product_count": product_count,
            "scored_products": scored_products,
            "avg_score": round(avg_score, 2),
            "completeness_pct": round(completeness, 2),
            "changes_30d": changes_30d,
            "stability_score": round(stability, 2),
            "catalog_breadth_score": round(breadth, 2),
            "quality_score": round(quality, 2),
        }


class SupplierQualitySampler:
    """Periodic supplier-quality snapshot loop."""

    def __init__(self, repository: ResilienceRepository, interval_seconds: float = 3600.0) -> None:
        self.repository = repository
        self.interval_seconds = interval_seconds
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="supplier-quality-sampler")

    async def stop(self) -> None:
        if self.task is None:
            return
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    async def _run(self) -> None:
        while True:
            await self.repository.snapshot_supplier_quality()
            await asyncio.sleep(self.interval_seconds)


def _now() -> str:
    return datetime.now(UTC).isoformat()
