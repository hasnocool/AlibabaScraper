# src/alibaba_scraper/service_resilience_routes.py
"""Operational-resilience API routes."""

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .database_maintenance import backup_database, integrity_check
from .production import ApiKeyCreated, ProductionRepository, Scope
from .resilience import ResilienceRepository


class QueueRetryRequest(BaseModel):
    queue_ids: list[int] | None = None
    error_contains: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=100, ge=1, le=5000)
    reset_attempts: bool = False
    resume: bool = False


class RotateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    grace_minutes: int = Field(default=15, ge=0, le=10080)


class TokenMintRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    ttl_minutes: int = Field(default=60, ge=1, le=1440)
    scopes: list[Scope] | None = None


class BackupRequest(BaseModel):
    destination: str | None = Field(default=None, max_length=4096)


class AlertPolicyRequest(BaseModel):
    max_attempts: int = Field(default=5, ge=1, le=100)
    base_backoff_seconds: float = Field(default=30.0, ge=1.0, le=86400.0)
    max_backoff_seconds: float = Field(default=3600.0, ge=1.0, le=604800.0)


class DeadLetterRetryRequest(BaseModel):
    reset_attempts: bool = True


def register_resilience_routes(app: FastAPI) -> None:
    @app.get("/api/jobs/{job_id}/errors")
    async def queue_errors(
        request: Request,
        job_id: int,
        error_contains: str | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    ) -> list[dict[str, object]]:
        return await _resilience(request).list_failed_queue(
            job_id, error_contains=error_contains, limit=limit
        )

    @app.post("/api/jobs/{job_id}/retry-errors")
    async def retry_queue_errors(
        request: Request,
        job_id: int,
        values: QueueRetryRequest,
    ) -> dict[str, object]:
        try:
            result = await _resilience(request).retry_failed_queue(
                job_id,
                queue_ids=values.queue_ids,
                error_contains=values.error_contains,
                limit=values.limit,
                reset_attempts=values.reset_attempts,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if values.resume and result["retried"]:
            state = await request.app.state.runtime.schedule_crawl(job_id)
            result["runtime"] = state.public()
        return result

    @app.get("/api/suppliers/quality")
    async def supplier_quality(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        return await _resilience(request).list_supplier_quality(limit)

    @app.get("/api/suppliers/{supplier_key:path}/quality-history")
    async def supplier_quality_history(
        request: Request,
        supplier_key: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        return await _resilience(request).supplier_quality_history(supplier_key, limit)

    @app.post("/api/suppliers/quality/snapshot")
    async def snapshot_supplier_quality(request: Request) -> dict[str, object]:
        rows = await _resilience(request).snapshot_supplier_quality()
        return {"snapshots": len(rows), "suppliers": rows}

    @app.post(
        "/api/admin/api-keys/{key_id}/rotate",
        status_code=201,
        response_model=ApiKeyCreated,
    )
    async def rotate_api_key(
        request: Request,
        key_id: int,
        values: RotateApiKeyRequest,
    ) -> ApiKeyCreated:
        try:
            return await _production(request).rotate_api_key(
                key_id, name=values.name, grace_minutes=values.grace_minutes
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/admin/api-keys/{key_id}/tokens",
        status_code=201,
        response_model=ApiKeyCreated,
    )
    async def mint_short_token(
        request: Request,
        key_id: int,
        values: TokenMintRequest,
    ) -> ApiKeyCreated:
        try:
            return await _production(request).mint_short_lived_token(
                key_id,
                ttl_minutes=values.ttl_minutes,
                scopes=values.scopes,
                name=values.name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/admin/alert-sinks/{sink_id}/policy")
    async def update_alert_sink_policy(
        request: Request,
        sink_id: int,
        values: AlertPolicyRequest,
    ) -> dict[str, object]:
        try:
            row = await _production(request).update_alert_sink_policy(
                sink_id,
                max_attempts=values.max_attempts,
                base_backoff_seconds=values.base_backoff_seconds,
                max_backoff_seconds=values.max_backoff_seconds,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return row.model_dump(mode="json")

    @app.get("/api/admin/alert-deliveries/dead-letter")
    async def dead_letters(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        return await _production(request).list_dead_letters(limit)

    @app.post("/api/admin/alert-deliveries/{delivery_id}/retry")
    async def retry_dead_letter(
        request: Request,
        delivery_id: int,
        values: DeadLetterRetryRequest,
    ) -> dict[str, object]:
        try:
            await _production(request).retry_dead_letter(
                delivery_id, reset_attempts=values.reset_attempts
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"delivery_id": delivery_id, "status": "retry_scheduled"}

    @app.get("/api/admin/database/integrity")
    async def database_integrity(request: Request) -> dict[str, object]:
        return await integrity_check(request.app.state.settings.database_path)

    @app.post("/api/admin/database/backup")
    async def database_backup(
        request: Request,
        values: BackupRequest,
    ) -> dict[str, object]:
        destination = Path(values.destination) if values.destination else None
        result = await backup_database(request.app.state.settings.database_path, destination)
        return result.__dict__


def _resilience(request: Request) -> ResilienceRepository:
    return request.app.state.resilience


def _production(request: Request) -> ProductionRepository:
    return request.app.state.production
