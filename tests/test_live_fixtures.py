# tests/test_live_fixtures.py
"""Regression tests based on sanitized fragments from current public Alibaba layouts."""

from decimal import Decimal
from pathlib import Path

from alibaba_scraper.scraper import AlibabaScraper

FIXTURES = Path(__file__).parent / "fixtures"


def test_public_lifepo4_fixture_extracts_tiers_supplier_and_attributes() -> None:
    html = (FIXTURES / "lifepo4_tiered_public.html").read_text(encoding="utf-8")
    record = AlibabaScraper.parse_product(
        "https://wholesaler.alibaba.com/product-detail/"
        "GFB-ffh4d3-rechargeable-lifepo4-battery-3_1906993224.html",
        html,
    )

    assert record.product_id == "1906993224"
    assert record.supplier_name == "Shenzhen Boye Energy Co., Ltd."
    assert record.price is not None
    assert record.price.minimum == Decimal("20.50")
    assert record.price.maximum == Decimal("26")
    assert len(record.price.tiers) == 4
    assert record.minimum_order_quantity == Decimal("10")
    assert record.minimum_order_unit.lower() == "pieces"
    assert record.attributes["Nominal Voltage"] == "3.2V"


def test_public_product_introduction_fixture_extracts_quantity_pricing() -> None:
    html = (FIXTURES / "power_station_public.html").read_text(encoding="utf-8")
    record = AlibabaScraper.parse_product(
        "https://www.alibaba.com/product-introduction/"
        "300w-Lithium-Battery-Solar-Portable-Lifepo4_1600984312491.html",
        html,
    )

    assert record.product_id == "1600984312491"
    assert record.price is not None
    assert record.price.minimum == Decimal("85")
    assert record.price.maximum == Decimal("100")
    assert record.minimum_order_quantity == Decimal("100")
    assert len(record.price.tiers) == 4
