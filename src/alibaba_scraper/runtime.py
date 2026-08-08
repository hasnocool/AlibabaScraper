# src/alibaba_scraper/runtime.py
"""In-process async task manager for live crawl and watchlist controls."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .control import ControlRepository
from .database import Database
from .intelligence import IntelligenceRepository
from .pipeline import CrawlPipeline
from .scraper import AlibabaScraper
from .watchlists import WatchlistService

TaskKind = Literal["crawl", "watchlist"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass
class RuntimeTask:
    """One live in-process control-plane task."""

    key: str
    kind: TaskKind
    target_id: int
    status: TaskStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "target_id": self.target_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "result": self.result,
        }


class RuntimeManager:
    """Own live asyncio tasks while durable crawl/watch progress stays in SQLite."""

    def __init__(
        self,
        database: Database,
        intelligence: IntelligenceRepository,
        control: ControlRepository,
        scraper: AlibabaScraper,
    ) -> None:
        self.database = database
        self.intelligence = intelligence
        self.control = control
        self.scraper = scraper
        self._states: dict[str, RuntimeTask] = {}
        self._lock = asyncio.Lock()

    async def create_crawl(
        self,
        query: str,
        *,
        max_products: int = 50,
        max_search_pages: int = 5,
    ) -> RuntimeTask:
        job_id = await self.database.create_job(query, max_products, max_search_pages)
        return await self.schedule_crawl(job_id)

    async def schedule_crawl(self, job_id: int) -> RuntimeTask:
        await self.database.get_job(job_id)
        key = f"crawl:{job_id}"
        async with self._lock:
            existing = self._states.get(key)
            if existing and existing.task and not existing.task.done():
                return existing
            state = RuntimeTask(key=key, kind="crawl", target_id=job_id)
            state.task = asyncio.create_task(self._run_crawl(state), name=key)
            self._states[key] = state
            return state

    async def schedule_watchlist(self, watchlist_id: int) -> RuntimeTask:
        await self.intelligence.get_watchlist(watchlist_id)
        key = f"watchlist:{watchlist_id}"
        async with self._lock:
            existing = self._states.get(key)
            if existing and existing.task and not existing.task.done():
                return existing
            state = RuntimeTask(key=key, kind="watchlist", target_id=watchlist_id)
            state.task = asyncio.create_task(self._run_watchlist(state), name=key)
            self._states[key] = state
            return state

    async def cancel(self, key: str) -> RuntimeTask:
        async with self._lock:
            state = self._states.get(key)
            if state is None or state.task is None or state.task.done():
                raise KeyError(f"runtime task {key} is not active")
            state.task.cancel()
            task = state.task
        try:
            await task
        except asyncio.CancelledError:
            pass
        return state

    async def snapshot(self) -> list[dict[str, Any]]:
        async with self._lock:
            states = list(self._states.values())
        ordered = sorted(states, key=lambda item: item.created_at, reverse=True)
        return [state.public() for state in ordered]

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [
                state.task
                for state in self._states.values()
                if state.task and not state.task.done()
            ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_crawl(self, state: RuntimeTask) -> None:
        state.status = "running"
        state.started_at = datetime.now(UTC)
        try:
            summary = await CrawlPipeline(
                self.scraper,
                self.database,
                intelligence=self.intelligence,
            ).run(state.target_id)
            await self.control.rescore(job_id=summary.job_id)
            await self.control.alert_for_high_scores(summary.job_id)
            state.result = summary.model_dump(mode="json")
            state.status = "completed"
        except asyncio.CancelledError:
            await self._mark_job_cancelled(state.target_id)
            state.status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced in runtime state
            state.status = "failed"
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            state.completed_at = datetime.now(UTC)

    async def _run_watchlist(self, state: RuntimeTask) -> None:
        state.status = "running"
        state.started_at = datetime.now(UTC)
        try:
            result = await WatchlistService(
                self.scraper,
                self.database,
                self.intelligence,
                control=self.control,
            ).run_watchlist(state.target_id)
            state.result = result.model_dump(mode="json")
            state.status = "completed"
        except asyncio.CancelledError:
            state.status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced in runtime state
            state.status = "failed"
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            state.completed_at = datetime.now(UTC)

    async def _mark_job_cancelled(self, job_id: int) -> None:
        """Persist cancellation using a short independent WAL write transaction."""
        now = datetime.now(UTC).isoformat()
        async with Database(self.database.path) as database:
            await database.connection.execute(
                """
                UPDATE crawl_jobs
                   SET status = 'cancelled', updated_at = ?, completed_at = ?
                 WHERE id = ?
                """,
                (now, now, job_id),
            )
            await database.connection.execute(
                """
                UPDATE crawl_queue
                   SET status = 'pending', updated_at = ?
                 WHERE job_id = ? AND status = 'in_progress'
                """,
                (now, job_id),
            )
            await database.connection.commit()
