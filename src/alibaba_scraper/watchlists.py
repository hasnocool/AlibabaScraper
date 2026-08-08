# src/alibaba_scraper/watchlists.py
"""Saved-search watchlists and recurring non-blocking recrawl orchestration."""

import asyncio
from typing import TYPE_CHECKING

from .database import Database
from .intelligence import IntelligenceRepository
from .models import WatchlistRun
from .pipeline import CrawlPipeline
from .scraper import AlibabaScraper

if TYPE_CHECKING:
    from .control import ControlRepository


class WatchlistService:
    """Run saved searches immediately, when due, or continuously as a daemon."""

    def __init__(
        self,
        scraper: AlibabaScraper,
        database: Database,
        intelligence: IntelligenceRepository,
        *,
        control: "ControlRepository | None" = None,
    ) -> None:
        self.scraper = scraper
        self.database = database
        self.intelligence = intelligence
        self.control = control

    async def run_watchlist(self, watchlist_id: int) -> WatchlistRun:
        """Run once and always produce profile scores/alerts when the control layer exists."""
        if self.control is not None:
            return await self._run_watchlist(watchlist_id, self.control)

        from .control import ControlRepository

        async with ControlRepository(self.database.path) as control:
            return await self._run_watchlist(watchlist_id, control)

    async def _run_watchlist(
        self,
        watchlist_id: int,
        control: "ControlRepository",
    ) -> WatchlistRun:
        watchlist = await self.intelligence.get_watchlist(watchlist_id)
        run_id = await self.intelligence.begin_watchlist_run(watchlist_id)
        job_id: int | None = None
        try:
            summary = await CrawlPipeline(
                self.scraper,
                self.database,
                intelligence=self.intelligence,
            ).start(
                watchlist.query,
                max_products=watchlist.max_products,
                max_search_pages=watchlist.max_search_pages,
            )
            job_id = summary.job_id
            changes = await self.intelligence.count_job_changes(job_id)
            status = summary.status
            await control.rescore(job_id=job_id)
            await control.alert_for_high_scores(job_id)
        except Exception:
            result = await self.intelligence.finish_watchlist_run(
                run_id,
                watchlist,
                job_id=job_id,
                status="failed",
                changes_count=0,
            )
            await control.alert_for_watchlist_result(
                watchlist_id=watchlist.id,
                watchlist_name=watchlist.name,
                job_id=job_id,
                status="failed",
                changes_count=0,
            )
            raise

        result = await self.intelligence.finish_watchlist_run(
            run_id,
            watchlist,
            job_id=job_id,
            status=status,
            changes_count=changes,
        )
        await control.alert_for_watchlist_result(
            watchlist_id=watchlist.id,
            watchlist_name=watchlist.name,
            job_id=job_id,
            status=status,
            changes_count=changes,
        )
        return result

    async def run_due(self, limit: int = 25) -> list[WatchlistRun]:
        """Run due watchlists independently so one failure does not stop the rest."""
        results: list[WatchlistRun] = []
        for watchlist in await self.intelligence.due_watchlists(limit):
            try:
                results.append(await self.run_watchlist(watchlist.id))
            except Exception:  # noqa: BLE001 - failure is persisted on the watchlist run
                continue
        return results

    async def daemon(self, *, poll_seconds: float = 60.0) -> None:
        """Continuously run due watchlists using non-blocking sleeps."""
        if poll_seconds < 1.0:
            raise ValueError("poll_seconds must be >= 1")
        while True:
            await self.run_due()
            await asyncio.sleep(poll_seconds)
