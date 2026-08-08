# tests/test_pipeline.py
"""End-to-end orchestration tests with an in-memory fake scraper."""

from pathlib import Path

from alibaba_scraper.config import Settings
from alibaba_scraper.database import Database
from alibaba_scraper.models import ProductRecord, SearchResult
from alibaba_scraper.pipeline import CrawlPipeline


class FakeScraper:
    def __init__(self) -> None:
        self.settings = Settings(max_concurrency=2)
        self.pages = {
            1: [
                SearchResult(
                    url="https://www.alibaba.com/product-detail/A_1600000000001.html",
                    product_id="1600000000001",
                ),
                SearchResult(
                    url="https://www.alibaba.com/product-detail/B_1600000000002.html",
                    product_id="1600000000002",
                ),
            ],
            2: [],
        }

    async def discover(self, query: str, page: int = 1) -> list[SearchResult]:
        assert query == "solar panel"
        return self.pages.get(page, [])

    async def fetch_product(self, url: str) -> ProductRecord:
        product_id = "1600000000001" if "_1600000000001" in url else "1600000000002"
        return ProductRecord(source_url=url, product_id=product_id, title=f"Product {product_id}")


async def test_pipeline_discovers_collects_and_finishes(tmp_path: Path) -> None:
    async with Database(tmp_path / "crawl.sqlite3") as db:
        summary = await CrawlPipeline(FakeScraper(), db).start(
            "solar panel",
            max_products=10,
            max_search_pages=3,
        )

    assert summary.status == "completed"
    assert summary.discovered == 2
    assert summary.completed == 2
    assert summary.errors == 0
    assert summary.pending == 0
