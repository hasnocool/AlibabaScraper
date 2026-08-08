# src/alibaba_scraper/models.py
"""Normalized data models used by crawler, intelligence, and persistence layers."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class PriceTier(BaseModel):
    """One quantity-dependent price tier."""

    minimum_quantity: Decimal | None = None
    maximum_quantity: Decimal | None = None
    unit: str | None = None
    price: Decimal
    currency: str | None = None


class PriceRange(BaseModel):
    """Normalized product price range and optional quantity tiers."""

    currency: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    unit: str | None = None
    tiers: list[PriceTier] = Field(default_factory=list)


class ProductRecord(BaseModel):
    """Normalized representation of a public Alibaba product listing."""

    source_url: HttpUrl
    canonical_url: HttpUrl | None = None
    title: str | None = None
    product_id: str | None = None
    supplier_name: str | None = None
    supplier_url: HttpUrl | None = None
    supplier_country: str | None = None
    category: str | None = None
    minimum_order_quantity: Decimal | None = None
    minimum_order_unit: str | None = None
    price: PriceRange | None = None
    image_urls: list[HttpUrl] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SearchResult(BaseModel):
    """A product URL discovered from an Alibaba search result page."""

    url: HttpUrl
    product_id: str | None = None
    title: str | None = None


CrawlStatus = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
QueueStatus = Literal["pending", "in_progress", "done", "error"]


class CrawlJob(BaseModel):
    """Persisted crawl job state."""

    id: int
    query: str
    status: CrawlStatus
    max_products: int
    max_search_pages: int
    next_search_page: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class QueueItem(BaseModel):
    """One product URL awaiting collection."""

    id: int
    job_id: int
    product_url: str
    product_id: str | None = None
    status: QueueStatus
    attempts: int
    last_error: str | None = None


class CrawlSummary(BaseModel):
    """Compact final or current state for a crawl job."""

    job_id: int
    query: str
    status: CrawlStatus
    discovered: int
    completed: int
    errors: int
    pending: int


class SupplierRecord(BaseModel):
    """Normalized supplier entry with its observed product count."""

    supplier_key: str
    name: str
    url: str | None = None
    country: str | None = None
    product_count: int = 0
    first_seen_at: datetime
    last_seen_at: datetime


class ProductChange(BaseModel):
    """One normalized field change detected between product observations."""

    id: int | None = None
    product_key: str
    job_id: int | None = None
    field: str
    old_value: str | None = None
    new_value: str | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SourcingScore(BaseModel):
    """Deterministic sourcing/deal score and component breakdown."""

    product_key: str | None = None
    job_id: int | None = None
    total: float
    price_value: float
    moq: float
    supplier_confidence: float
    tier_discount: float
    data_quality: float
    peer_median_price: Decimal | None = None
    reasons: list[str] = Field(default_factory=list)
    scored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Watchlist(BaseModel):
    """Saved search that can be recrawled on a recurring interval."""

    id: int
    name: str
    query: str
    enabled: bool
    interval_minutes: int
    max_products: int
    max_search_pages: int
    last_run_at: datetime | None = None
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime


class WatchlistRun(BaseModel):
    """Result of running one watchlist crawl."""

    id: int
    watchlist_id: int
    job_id: int | None = None
    status: str
    changes_count: int
    started_at: datetime
    completed_at: datetime | None = None
