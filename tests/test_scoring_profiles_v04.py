# tests/test_scoring_profiles_v04.py
from decimal import Decimal

from alibaba_scraper.models import PriceRange, ProductRecord
from alibaba_scraper.scoring import ScoreWeights, score_product


def test_custom_weights_change_total_without_changing_components() -> None:
    record = ProductRecord(
        source_url="https://www.alibaba.com/product-detail/Test_1600000000400.html",
        title="Test product",
        product_id="1600000000400",
        supplier_name="Supplier",
        supplier_country="CN",
        price=PriceRange(currency="USD", minimum=Decimal("8"), maximum=Decimal("10")),
        minimum_order_quantity=Decimal("500"),
    )
    balanced = score_product(record, peer_median_price=Decimal("10"))
    price_first = score_product(
        record,
        peer_median_price=Decimal("10"),
        weights=ScoreWeights(
            price_value=100,
            moq=0,
            supplier_confidence=0,
            tier_discount=0,
            data_quality=0,
        ),
    )

    assert price_first.price_value == balanced.price_value
    assert price_first.total == price_first.price_value
    assert price_first.total != balanced.total
