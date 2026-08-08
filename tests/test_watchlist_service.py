# tests/test_watchlist_service.py
"""End-to-end watchlist recrawl and change-count tests."""

from decimal import Decimal
from pathlib import Path

from alibaba_scraper.database import Database
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.models import PriceRange, ProductRecord, SearchResult
from alibaba_scraper.watchlists import WatchlistService


class FakeSettings:
    max_concurrency = 2


class FakeScraper:
    settings = FakeSettings()

    def __init__(self) -> None:
        self.price = Decimal("20")

    async def discover(self, query: str, page: int = 1) -> list[SearchResult]:
        if page > 1:
            return []
        return [
            SearchResult(
                url="https://www.alibaba.com/product-detail/example_1600000000200.html",
                product_id="1600000000200",
                title="Example",
            )
        ]

    async def fetch_product(self, url: str) -> ProductRecord:
        return ProductRecord(
            source_url=url,
            canonical_url=url,
            product_id="1600000000200",
            title="Example",
            supplier_name="Supplier Example",
            supplier_country="China",
            minimum_order_quantity=Decimal("2"),
            minimum_order_unit="pieces",
            price=PriceRange(currency="USD", minimum=self.price, maximum=self.price),
        )


async def test_watchlist_recrawl_detects_changed_price(tmp_path: Path) -> None:
    path = tmp_path / "watch-service.sqlite3"
    scraper = FakeScraper()
    async with Database(path) as db, IntelligenceRepository(path) as intelligence:
        watchlist_id = await intelligence.create_watchlist(
            "example",
            "example query",
            interval_minutes=60,
            max_products=10,
            max_search_pages=2,
        )
        service = WatchlistService(scraper, db, intelligence)  # type: ignore[arg-type]

        first = await service.run_watchlist(watchlist_id)
        assert first.status == "completed"
        assert first.changes_count == 0

        scraper.price = Decimal("15")
        second = await service.run_watchlist(watchlist_id)
        assert second.status == "completed"
        assert second.changes_count >= 1

        changes = await intelligence.list_changes(job_id=second.job_id)
        assert any(change.field == "price.minimum" for change in changes)
        scores = await intelligence.top_scores()
        assert scores[0]["product_id"] == "1600000000200"
