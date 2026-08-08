# tests/test_runtime_v04.py
import asyncio
from pathlib import Path

from alibaba_scraper.control import ControlRepository
from alibaba_scraper.database import Database
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.runtime import RuntimeManager


class _FakeSettings:
    max_concurrency = 1


class _SlowScraper:
    settings = _FakeSettings()

    async def discover(self, query: str, page: int = 1) -> list[object]:
        await asyncio.sleep(60)
        return []

    async def fetch_product(self, url: str) -> object:
        raise AssertionError("fetch_product should not run in cancellation test")


async def test_runtime_cancel_persists_cancelled_job(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    async with (
        Database(path) as database,
        IntelligenceRepository(path) as intelligence,
        ControlRepository(path) as control,
    ):
        runtime = RuntimeManager(
            database,
            intelligence,
            control,
            _SlowScraper(),  # type: ignore[arg-type]
        )
        state = await runtime.create_crawl("slow", max_products=1, max_search_pages=1)
        await asyncio.sleep(0)
        cancelled = await runtime.cancel(state.key)
        assert cancelled.status == "cancelled"
        job = await database.get_job(state.target_id)
        assert job.status == "cancelled"
