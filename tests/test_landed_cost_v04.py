# tests/test_landed_cost_v04.py
from decimal import Decimal

from alibaba_scraper.landed_cost import LandedCostInput, calculate_landed_cost


def test_landed_cost_includes_rates_fees_and_margin() -> None:
    result = calculate_landed_cost(
        LandedCostInput(
            currency="cad",
            unit_price=Decimal("10"),
            quantity=Decimal("10"),
            shipping=Decimal("20"),
            insurance=Decimal("5"),
            duty_rate_pct=Decimal("4"),
            tax_rate_pct=Decimal("10"),
            brokerage=Decimal("3"),
            packaging_per_unit=Decimal("0.50"),
            other_fees=Decimal("2"),
            target_sale_price=Decimal("20"),
        )
    )

    assert result.currency == "CAD"
    assert result.merchandise == Decimal("100.00")
    assert result.customs_value == Decimal("125.00")
    assert result.duty == Decimal("5.00")
    assert result.tax == Decimal("13.00")
    assert result.packaging == Decimal("5.00")
    assert result.landed_total == Decimal("153.00")
    assert result.landed_per_unit == Decimal("15.30")
    assert result.estimated_gross_profit == Decimal("47.00")
    assert result.estimated_gross_margin_pct == Decimal("23.50")
