# tests/test_intelligence.py
"""Supplier, change detection, scoring, and watchlist persistence tests."""

from decimal import Decimal
from pathlib import Path

from alibaba_scraper.database import Database
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.models import PriceRange, ProductRecord


def _record(price: str = "20") -> ProductRecord:
    return ProductRecord(
        source_url="https://www.alibaba.com/product-detail/example_1600000000001.html",
        canonical_url="https://www.alibaba.com/product-detail/example_1600000000001.html",
        product_id="1600000000001",
        title="Example product",
        supplier_name="Example Supplier Co., Ltd.",
        supplier_country="China",
        minimum_order_quantity=Decimal("2"),
        minimum_order_unit="pieces",
        price=PriceRange(currency="USD", minimum=Decimal(price), maximum=Decimal(price)),
        attributes={"Material": "Example"},
    )


async def test_supplier_relationship_change_detection_and_scoring(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    async with Database(path) as db, IntelligenceRepository(path) as intelligence:
        first = _record("20")
        previous = await intelligence.previous_record(first)
        key = await db.upsert_product(first)
        changes = await intelligence.record_product(
            first,
            key,
            previous=previous,
            job_id=None,
        )
        assert changes == []

        second = _record("15")
        previous = await intelligence.previous_record(second)
        key = await db.upsert_product(second)
        changes = await intelligence.record_product(
            second,
            key,
            previous=previous,
            job_id=7,
        )

        assert any(change.field == "price.minimum" for change in changes)
        suppliers = await intelligence.list_suppliers()
        assert suppliers[0].name == "Example Supplier Co., Ltd."
        assert suppliers[0].product_count == 1
        products = await intelligence.supplier_products(suppliers[0].supplier_key)
        assert products[0]["product_id"] == "1600000000001"


async def test_watchlist_crud_and_due_selection(tmp_path: Path) -> None:
    path = tmp_path / "watch.sqlite3"
    async with IntelligenceRepository(path) as intelligence:
        watchlist_id = await intelligence.create_watchlist(
            "solar",
            "solar panel",
            interval_minutes=60,
            max_products=25,
            max_search_pages=3,
        )
        watchlist = await intelligence.get_watchlist(watchlist_id)
        assert watchlist.enabled is True
        assert watchlist.query == "solar panel"
        assert [item.id for item in await intelligence.due_watchlists()] == [watchlist_id]

        await intelligence.set_watchlist_enabled(watchlist_id, False)
        assert await intelligence.due_watchlists() == []
