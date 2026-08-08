# src/alibaba_scraper/pipeline.py
"""Search -> queue -> scrape -> normalize -> SQLite crawl orchestration."""

import asyncio

from .database import Database
from .models import CrawlSummary, QueueItem
from .scraper import AlibabaScraper


class CrawlPipeline:
    """Resumable Alibaba collection pipeline backed by SQLite."""

    def __init__(self, scraper: AlibabaScraper, database: Database) -> None:
        self.scraper = scraper
        self.database = database

    async def start(
        self,
        query: str,
        *,
        max_products: int = 50,
        max_search_pages: int = 5,
    ) -> CrawlSummary:
        job_id = await self.database.create_job(query, max_products, max_search_pages)
        return await self.run(job_id)

    async def resume(self, job_id: int) -> CrawlSummary:
        await self.database.get_job(job_id)
        return await self.run(job_id)

    async def run(self, job_id: int) -> CrawlSummary:
        await self.database.mark_job_running(job_id)
        try:
            await self._discover(job_id)
            while True:
                batch = await self.database.claim_pending(
                    job_id,
                    limit=self.scraper.settings.max_concurrency,
                )
                if not batch:
                    break
                await asyncio.gather(*(self._collect_item(item) for item in batch))
            return await self.database.finish_job(job_id)
        except Exception:
            await self.database.fail_job(job_id)
            raise

    async def _discover(self, job_id: int) -> None:
        job = await self.database.get_job(job_id)
        page = job.next_search_page
        while page <= job.max_search_pages:
            current_count = await self.database.queue_count(job_id)
            if current_count >= job.max_products:
                break

            results = await self.scraper.discover(job.query, page)
            if not results:
                await self.database.set_next_search_page(job_id, page + 1)
                break

            remaining = job.max_products - current_count
            urls = [(str(result.url), result.product_id) for result in results[:remaining]]
            await self.database.enqueue(job_id, urls)
            page += 1
            await self.database.set_next_search_page(job_id, page)

    async def _collect_item(self, item: QueueItem) -> None:
        try:
            record = await self.scraper.fetch_product(item.product_url)
            await self.database.upsert_product(record)
        except Exception as exc:  # noqa: BLE001 - errors are persisted per queue item
            await self.database.mark_queue_error(item.id, f"{type(exc).__name__}: {exc}")
            return
        await self.database.mark_queue_done(item.id)
