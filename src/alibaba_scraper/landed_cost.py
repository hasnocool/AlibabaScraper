# src/alibaba_scraper/landed_cost.py
"""Generic landed-cost estimation without jurisdiction-specific tax claims."""

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, model_validator

MONEY = Decimal("0.01")


class LandedCostInput(BaseModel):
    """Inputs for a same-currency landed-cost estimate."""

    currency: str = "USD"
    unit_price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    shipping: Decimal = Field(default=Decimal("0"), ge=0)
    insurance: Decimal = Field(default=Decimal("0"), ge=0)
    duty_rate_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tax_rate_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    brokerage: Decimal = Field(default=Decimal("0"), ge=0)
    packaging_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    other_fees: Decimal = Field(default=Decimal("0"), ge=0)
    target_sale_price: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def normalize_currency(self) -> "LandedCostInput":
        self.currency = self.currency.strip().upper()
        if not self.currency:
            raise ValueError("currency is required")
        return self


class LandedCostResult(BaseModel):
    """Calculated landed-cost breakdown."""

    currency: str
    quantity: Decimal
    merchandise: Decimal
    packaging: Decimal
    customs_value: Decimal
    duty: Decimal
    tax: Decimal
    brokerage: Decimal
    other_fees: Decimal
    landed_total: Decimal
    landed_per_unit: Decimal
    target_revenue: Decimal | None = None
    estimated_gross_profit: Decimal | None = None
    estimated_gross_margin_pct: Decimal | None = None


def calculate_landed_cost(values: LandedCostInput) -> LandedCostResult:
    """Return a transparent generic estimate using the caller's rates and fees."""
    merchandise = values.unit_price * values.quantity
    packaging = values.packaging_per_unit * values.quantity
    customs_value = merchandise + values.shipping + values.insurance
    duty = customs_value * values.duty_rate_pct / Decimal("100")
    taxable_base = customs_value + duty
    tax = taxable_base * values.tax_rate_pct / Decimal("100")
    landed_total = duty + tax + customs_value + packaging + values.brokerage + values.other_fees
    landed_per_unit = landed_total / values.quantity

    target_revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    gross_margin: Decimal | None = None
    if values.target_sale_price is not None:
        target_revenue = values.target_sale_price * values.quantity
        gross_profit = target_revenue - landed_total
        if target_revenue > 0:
            gross_margin = gross_profit / target_revenue * Decimal("100")

    return LandedCostResult(
        currency=values.currency,
        quantity=values.quantity,
        merchandise=_money(merchandise),
        packaging=_money(packaging),
        customs_value=_money(customs_value),
        duty=_money(duty),
        tax=_money(tax),
        brokerage=_money(values.brokerage),
        other_fees=_money(values.other_fees),
        landed_total=_money(landed_total),
        landed_per_unit=_money(landed_per_unit),
        target_revenue=_money(target_revenue) if target_revenue is not None else None,
        estimated_gross_profit=_money(gross_profit) if gross_profit is not None else None,
        estimated_gross_margin_pct=_percent(gross_margin) if gross_margin is not None else None,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
