# tests/test_scoring.py
"""Sourcing-score behavior tests."""

from decimal import Decimal

from alibaba_scraper.models import PriceRange, PriceTier, ProductRecord
from alibaba_scraper.scoring import score_product


def test_score_rewards_below_median_low_moq_and_tier_discount() -> None:
    record = ProductRecord(
        source_url="https://www.alibaba.com/product-detail/example_1600000000100.html",
        product_id="1600000000100",
        title="Example",
        supplier_name="Example Supplier",
        supplier_country="China",
        minimum_order_quantity=Decimal("2"),
        minimum_order_unit="pieces",
        price=PriceRange(
            currency="USD",
            minimum=Decimal("8"),
            maximum=Decimal("12"),
            tiers=[
                PriceTier(minimum_quantity=Decimal("2"), price=Decimal("12"), currency="USD"),
                PriceTier(minimum_quantity=Decimal("100"), price=Decimal("8"), currency="USD"),
            ],
        ),
        attributes={"Example": "Yes"},
        image_urls=["https://example.com/image.jpg"],
    )

    result = score_product(record, peer_median_price=Decimal("12"))

    assert result.total > 70
    assert result.price_value > 50
    assert result.moq >= 90
    assert result.tier_discount > 60
