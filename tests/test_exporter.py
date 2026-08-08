# tests/test_exporter.py
"""CSV/JSONL export tests."""

import json
from decimal import Decimal
from pathlib import Path

from alibaba_scraper.database import Database
from alibaba_scraper.exporter import export_products
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.models import PriceRange, ProductRecord


async def test_export_products_to_jsonl_and_csv(tmp_path: Path) -> None:
    database_path = tmp_path / "export.sqlite3"
    record = ProductRecord(
        source_url="https://www.alibaba.com/product-detail/example_1600000000002.html",
        product_id="1600000000002",
        title="Export example",
        supplier_name="Export Supplier",
        price=PriceRange(currency="USD", minimum=Decimal("12.5"), maximum=Decimal("15")),
        minimum_order_quantity=Decimal("5"),
        minimum_order_unit="pieces",
    )

    async with Database(database_path) as db, IntelligenceRepository(database_path):
        await db.upsert_product(record)
        jsonl = tmp_path / "products.jsonl"
        csv_path = tmp_path / "products.csv"
        assert await export_products(db, jsonl, format="jsonl") == 1
        assert await export_products(db, csv_path, format="csv") == 1

    payload = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert payload["product_id"] == "1600000000002"
    assert "Export example" in csv_path.read_text(encoding="utf-8")
