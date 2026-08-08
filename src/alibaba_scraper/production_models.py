# src/alibaba_scraper/production_models.py
"""Pydantic models for production-operation persistence."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator

from .landed_cost import LandedCostInput, LandedCostResult

Scope = Literal["read", "write", "admin"]
Severity = Literal["info", "warning", "error"]


class ApiKeyRecord(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: list[Scope]
    enabled: bool
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    record: ApiKeyRecord
    api_key: str


class ApiPrincipal(BaseModel):
    key_id: int
    name: str
    scopes: list[Scope]

    def allows(self, required: Scope) -> bool:
        scope_set = set(self.scopes)
        if "admin" in scope_set:
            return True
        if required == "read" and "write" in scope_set:
            return True
        return required in scope_set


class LandedCostScenarioInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    product_key: str | None = Field(default=None, max_length=200)
    values: LandedCostInput


class LandedCostScenario(BaseModel):
    id: int
    name: str
    product_key: str | None = None
    values: LandedCostInput
    result: LandedCostResult
    created_at: datetime
    updated_at: datetime


class CategoryProfileBindingInput(BaseModel):
    category_pattern: str = Field(min_length=1, max_length=200)
    profile_id: int
    priority: int = Field(default=100, ge=-100000, le=100000)
    enabled: bool = True

    @model_validator(mode="after")
    def normalize(self) -> "CategoryProfileBindingInput":
        self.category_pattern = self.category_pattern.strip().lower()
        return self


class CategoryProfileBinding(BaseModel):
    id: int
    category_pattern: str
    profile_id: int
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertSinkInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["webhook"] = "webhook"
    endpoint: str = Field(min_length=8, max_length=2048)
    secret: str | None = Field(default=None, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    event_kinds: list[str] = Field(default_factory=list)
    minimum_severity: Severity = "info"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_endpoint(self) -> "AlertSinkInput":
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("webhook endpoint must be an http:// or https:// URL")
        return self


class AlertSink(BaseModel):
    id: int
    name: str
    kind: str
    endpoint: str
    has_secret: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    event_kinds: list[str] = Field(default_factory=list)
    minimum_severity: Severity
    enabled: bool
    created_at: datetime
    updated_at: datetime
