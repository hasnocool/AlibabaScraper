# src/alibaba_scraper/scoring.py
"""Deterministic product sourcing/deal scoring."""

from decimal import Decimal

from .models import ProductRecord, SourcingScore


def score_product(
    record: ProductRecord,
    *,
    peer_median_price: Decimal | None = None,
) -> SourcingScore:
    """Score sourcing attractiveness without making financial-return claims."""
    price_value = _price_value_score(record, peer_median_price)
    moq = _moq_score(record)
    supplier = _supplier_score(record)
    tier_discount = _tier_discount_score(record)
    data_quality = _data_quality_score(record)

    total = (
        price_value * 0.35
        + moq * 0.20
        + supplier * 0.20
        + tier_discount * 0.10
        + data_quality * 0.15
    )
    reasons = _reasons(record, peer_median_price, price_value, moq, tier_discount)
    return SourcingScore(
        total=round(total, 2),
        price_value=round(price_value, 2),
        moq=round(moq, 2),
        supplier_confidence=round(supplier, 2),
        tier_discount=round(tier_discount, 2),
        data_quality=round(data_quality, 2),
        peer_median_price=peer_median_price,
        reasons=reasons,
    )


def _price_value_score(record: ProductRecord, peer_median: Decimal | None) -> float:
    current = record.price.minimum if record.price else None
    if current is None:
        return 0.0
    if peer_median is None or peer_median <= 0:
        return 50.0
    delta = (peer_median - current) / peer_median
    return _clamp(50.0 + float(delta) * 100.0)


def _moq_score(record: ProductRecord) -> float:
    quantity = record.minimum_order_quantity
    if quantity is None:
        return 40.0
    thresholds = (
        (Decimal("1"), 100.0),
        (Decimal("5"), 90.0),
        (Decimal("10"), 80.0),
        (Decimal("50"), 65.0),
        (Decimal("100"), 50.0),
        (Decimal("500"), 30.0),
    )
    for maximum, score in thresholds:
        if quantity <= maximum:
            return score
    return 15.0


def _supplier_score(record: ProductRecord) -> float:
    score = 0.0
    if record.supplier_name:
        score += 45.0
    if record.supplier_url:
        score += 30.0
    if record.supplier_country:
        score += 25.0
    return score


def _tier_discount_score(record: ProductRecord) -> float:
    tiers = record.price.tiers if record.price else []
    if not tiers:
        return 20.0 if record.price else 0.0
    if len(tiers) == 1:
        return 35.0
    prices = [tier.price for tier in tiers]
    highest = max(prices)
    lowest = min(prices)
    if highest <= 0:
        return 35.0
    discount = float((highest - lowest) / highest)
    return _clamp(35.0 + discount * 180.0)


def _data_quality_score(record: ProductRecord) -> float:
    checks = (
        bool(record.title),
        bool(record.product_id),
        bool(record.supplier_name),
        bool(record.price and record.price.minimum is not None),
        record.minimum_order_quantity is not None,
        bool(record.category),
        bool(record.attributes),
        bool(record.image_urls),
    )
    return sum(checks) / len(checks) * 100.0


def _reasons(
    record: ProductRecord,
    peer_median: Decimal | None,
    price_value: float,
    moq: float,
    tier_discount: float,
) -> list[str]:
    reasons: list[str] = []
    if peer_median is None and record.price:
        reasons.append("Price is known, but no same-currency peer median is available yet.")
    elif price_value >= 65:
        reasons.append("Minimum price is favorable versus the current same-currency peer median.")
    elif price_value <= 35 and record.price:
        reasons.append("Minimum price is above the current same-currency peer median.")
    if moq >= 80:
        reasons.append("Low MOQ improves small-batch sourcing flexibility.")
    elif moq <= 30:
        reasons.append("High MOQ reduces small-batch sourcing flexibility.")
    if tier_discount >= 60:
        reasons.append("Quantity tiers show a meaningful volume discount.")
    if not record.supplier_name:
        reasons.append("Supplier identity was not extracted, lowering confidence.")
    if not record.price:
        reasons.append("No normalized price was extracted.")
    return reasons


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
