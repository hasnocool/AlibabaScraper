# src/alibaba_scraper/service_models.py
"""Request models shared by FastAPI route modules."""

from datetime import datetime

from pydantic import BaseModel, Field

from .production import Scope


class CrawlRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    max_products: int = Field(default=50, ge=1, le=5000)
    max_search_pages: int = Field(default=5, ge=1, le=100)


class WatchlistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=300)
    interval_minutes: int = Field(default=1440, ge=1, le=525600)
    max_products: int = Field(default=50, ge=1, le=5000)
    max_search_pages: int = Field(default=5, ge=1, le=100)


class WatchlistUpdate(BaseModel):
    enabled: bool


class RescoreRequest(BaseModel):
    profile_id: int | None = None
    job_id: int | None = None


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(default_factory=lambda: ["read", "write"])
    expires_at: datetime | None = None


class ComparisonRequest(BaseModel):
    identifiers: list[str] = Field(min_length=1, max_length=12)
