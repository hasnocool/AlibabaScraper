# src/alibaba_scraper/models.py
"""Normalized product data models."""

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, HttpUrl


class PriceRange(BaseModel):
    """Optional normalized product price range."""

    currency: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    unit: str | None = None


class ProductRecord(BaseModel):
    """Normalized representation of a public Alibaba product listing."""

    source_url: HttpUrl
    title: str | None = None
    product_id: str | None = None
    supplier_name: str | None = None
    supplier_country: str | None = None
    category: str | None = None
    minimum_order_quantity: str | None = None
    price: PriceRange | None = None
    image_urls: list[HttpUrl] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
