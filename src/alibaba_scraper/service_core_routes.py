# src/alibaba_scraper/service_core_routes.py
"""Core-compatible API and dashboard routes."""

from decimal import Decimal
from typing import Annotated

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .control import ControlRepository, ScoringProfileInput
from .database import Database
from .intelligence import IntelligenceRepository
from .landed_cost import LandedCostInput, LandedCostResult, calculate_landed_cost
from .migrations import CURRENT_SCHEMA_VERSION, schema_version
from .production import ProductionRepository
from .production_ui import OPS_CSS, OPS_HTML, OPS_JS
from .runtime import RuntimeManager
from .service_models import CrawlRequest, RescoreRequest, WatchlistRequest, WatchlistUpdate
from .telemetry import TelemetryRegistry
from .webui import DASHBOARD_CSS, DASHBOARD_HTML, DASHBOARD_JS


def register_core_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def operations_page() -> str:
        return OPS_HTML

    @app.get("/classic", response_class=HTMLResponse, include_in_schema=False)
    async def classic_dashboard_page() -> str:
        return DASHBOARD_HTML

    @app.get("/assets/dashboard.css", response_class=PlainTextResponse, include_in_schema=False)
    async def dashboard_css() -> PlainTextResponse:
        return PlainTextResponse(DASHBOARD_CSS, media_type="text/css")

    @app.get("/assets/dashboard.js", response_class=PlainTextResponse, include_in_schema=False)
    async def dashboard_js() -> PlainTextResponse:
        return PlainTextResponse(DASHBOARD_JS, media_type="application/javascript")

    @app.get("/assets/ops.css", response_class=PlainTextResponse, include_in_schema=False)
    async def ops_css() -> PlainTextResponse:
        return PlainTextResponse(OPS_CSS, media_type="text/css")

    @app.get("/assets/ops.js", response_class=PlainTextResponse, include_in_schema=False)
    async def ops_js() -> PlainTextResponse:
        return PlainTextResponse(OPS_JS, media_type="application/javascript")

    @app.post("/api/auth/session")
    async def auth_session(request: Request) -> JSONResponse:
        raw_key = request.headers.get("X-API-Key", "")
        principal = await _production(request).authenticate(raw_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="valid API key required")
        response = JSONResponse({"authenticated": True, "name": principal.name})
        response.set_cookie(
            "alibaba_api_key",
            raw_key,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return response

    @app.delete("/api/auth/session")
    async def auth_session_delete() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("alibaba_api_key")
        return response

    @app.get("/api/health/live")
    async def health_live() -> dict[str, object]:
        return {"status": "ok", "version": "0.6.0"}

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, object]:
        await _database(request).connection.execute("SELECT 1")
        control = _control(request)
        profile = await control.active_profile()
        runtime = await _runtime(request).snapshot()
        delivery = await _production(request).delivery_summary()
        return {
            "status": "ok",
            "version": "0.6.0",
            "schema_version": await schema_version(_database(request).path),
            "schema_current": CURRENT_SCHEMA_VERSION,
            "active_profile": profile.name,
            "watch_scheduler_enabled": request.app.state.settings.watch_scheduler_enabled,
            "supplier_quality_sampler_enabled": (
                request.app.state.settings.supplier_quality_sampler_enabled
            ),
            "runtime_active": sum(
                1 for task in runtime if task["status"] in {"queued", "running"}
            ),
            "alert_delivery": delivery,
            "telemetry": _telemetry(request).snapshot(),
        }

    @app.get("/api/health/ready")
    async def health_ready(request: Request) -> dict[str, object]:
        await _database(request).connection.execute("SELECT 1")
        version = await schema_version(_database(request).path)
        return {
            "ready": version == CURRENT_SCHEMA_VERSION,
            "schema_version": version,
            "schema_current": CURRENT_SCHEMA_VERSION,
        }

    @app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
    async def metrics(request: Request) -> PlainTextResponse:
        summary = await _control(request).dashboard_summary()
        delivery = await _production(request).delivery_summary()
        extra = {
            "products": summary["products"],
            "suppliers": summary["suppliers"],
            "running_jobs": summary["running_jobs"],
            "unread_alerts": summary["unread_alerts"],
            "alert_delivery_failed": delivery["failed"],
            "alert_delivery_dead_letter": delivery["dead_letter"],
        }
        return PlainTextResponse(_telemetry(request).prometheus(extra))

    @app.get("/api/dashboard")
    async def dashboard(request: Request) -> dict[str, object]:
        return await _control(request).dashboard_summary()

    @app.get("/api/products")
    async def products(
        request: Request,
        query: str | None = None,
        supplier_key: str | None = None,
        currency: str | None = None,
        min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
        max_price: Annotated[Decimal | None, Query(gt=0)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, object]]:
        return await _control(request).list_products(
            query=query,
            supplier_key=supplier_key,
            currency=currency,
            min_score=min_score,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/products/{identifier:path}")
    async def product_detail(request: Request, identifier: str) -> dict[str, object]:
        product = await _control(request).get_product(identifier)
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        return product

    @app.get("/api/suppliers")
    async def suppliers(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _intelligence(request).list_suppliers(limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/api/suppliers/{supplier_key:path}/products")
    async def supplier_products(
        request: Request,
        supplier_key: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        return await _intelligence(request).supplier_products(supplier_key, limit)

    @app.get("/api/jobs")
    async def jobs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _database(request).list_jobs(limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/jobs", status_code=202)
    async def create_job(request: Request, values: CrawlRequest) -> dict[str, object]:
        state = await _runtime(request).create_crawl(
            values.query,
            max_products=values.max_products,
            max_search_pages=values.max_search_pages,
        )
        return state.public()

    @app.post("/api/jobs/{job_id}/resume", status_code=202)
    async def resume_job(request: Request, job_id: int) -> dict[str, object]:
        try:
            state = await _runtime(request).schedule_crawl(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return state.public()

    @app.get("/api/runtime")
    async def runtime_state(request: Request) -> list[dict[str, object]]:
        return await _runtime(request).snapshot()

    @app.post("/api/runtime/{key:path}/cancel")
    async def cancel_runtime(request: Request, key: str) -> dict[str, object]:
        try:
            state = await _runtime(request).cancel(key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return state.public()

    @app.get("/api/watchlists")
    async def watchlists(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _intelligence(request).list_watchlists(limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/watchlists", status_code=201)
    async def create_watchlist(request: Request, values: WatchlistRequest) -> dict[str, object]:
        intelligence = _intelligence(request)
        try:
            watchlist_id = await intelligence.create_watchlist(
                values.name,
                values.query,
                interval_minutes=values.interval_minutes,
                max_products=values.max_products,
                max_search_pages=values.max_search_pages,
            )
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="watchlist name already exists") from exc
        row = await intelligence.get_watchlist(watchlist_id)
        return row.model_dump(mode="json")

    @app.patch("/api/watchlists/{watchlist_id}")
    async def update_watchlist(
        request: Request,
        watchlist_id: int,
        values: WatchlistUpdate,
    ) -> dict[str, object]:
        intelligence = _intelligence(request)
        try:
            await intelligence.get_watchlist(watchlist_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await intelligence.set_watchlist_enabled(watchlist_id, values.enabled)
        return (await intelligence.get_watchlist(watchlist_id)).model_dump(mode="json")

    @app.post("/api/watchlists/{watchlist_id}/run", status_code=202)
    async def run_watchlist(request: Request, watchlist_id: int) -> dict[str, object]:
        try:
            state = await _runtime(request).schedule_watchlist(watchlist_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return state.public()

    @app.get("/api/changes")
    async def changes(
        request: Request,
        job_id: int | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _intelligence(request).list_changes(job_id=job_id, limit=limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/api/alerts")
    async def alerts(
        request: Request,
        unread_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _control(request).list_alerts(unread_only=unread_only, limit=limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/alerts/{alert_id}/read")
    async def read_alert(request: Request, alert_id: int) -> dict[str, object]:
        try:
            row = await _control(request).mark_alert_read(alert_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return row.model_dump(mode="json")

    @app.get("/api/scoring/profiles")
    async def scoring_profiles(request: Request) -> list[dict[str, object]]:
        rows = await _control(request).list_profiles()
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/scoring/profiles", status_code=201)
    async def create_scoring_profile(
        request: Request,
        values: ScoringProfileInput,
    ) -> dict[str, object]:
        try:
            row = await _control(request).create_profile(values)
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="scoring profile name already exists",
            ) from exc
        return row.model_dump(mode="json")

    @app.post("/api/scoring/profiles/{profile_id}/activate")
    async def activate_scoring_profile(request: Request, profile_id: int) -> dict[str, object]:
        try:
            row = await _control(request).activate_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return row.model_dump(mode="json")

    @app.post("/api/scoring/rescore")
    async def rescore(request: Request, values: RescoreRequest) -> dict[str, object]:
        try:
            count = await _control(request).rescore(
                profile_id=values.profile_id,
                job_id=values.job_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"rescored": count, "profile_id": values.profile_id, "job_id": values.job_id}

    @app.post("/api/landed-cost", response_model=LandedCostResult)
    async def landed_cost(values: LandedCostInput) -> LandedCostResult:
        return calculate_landed_cost(values)


def _database(request: Request) -> Database:
    return request.app.state.database


def _intelligence(request: Request) -> IntelligenceRepository:
    return request.app.state.intelligence


def _control(request: Request) -> ControlRepository:
    return request.app.state.control


def _production(request: Request) -> ProductionRepository:
    return request.app.state.production


def _runtime(request: Request) -> RuntimeManager:
    return request.app.state.runtime


def _telemetry(request: Request) -> TelemetryRegistry:
    return request.app.state.telemetry
