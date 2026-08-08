# src/alibaba_scraper/service.py
"""Authenticated FastAPI control plane for AlibabaScraper."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .alert_delivery import AlertDispatcher
from .config import Settings
from .control import ControlRepository
from .database import Database
from .intelligence import IntelligenceRepository
from .migrations import migrate_database
from .production import ProductionRepository, Scope
from .runtime import RuntimeManager
from .scraper import AlibabaScraper
from .service_core_routes import register_core_routes
from .service_production_routes import register_production_routes
from .telemetry import RequestTimer, TelemetryRegistry
from .watchlists import WatchlistService


def create_app(
    database_path: Path | str = Path("data/alibaba.sqlite3"),
    *,
    auth_required: bool | None = None,
) -> FastAPI:
    """Create the authenticated local-first API/dashboard application."""
    path = Path(database_path)
    base_settings = Settings(database_path=path)
    require_auth = base_settings.auth_required if auth_required is None else auth_required

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = Settings(database_path=path, auth_required=require_auth)
        await migrate_database(path)
        database = Database(path)
        intelligence = IntelligenceRepository(path)
        control = ControlRepository(path)
        production = ProductionRepository(path)
        scraper = AlibabaScraper(settings)
        await database.open()
        await intelligence.open()
        await control.open()
        await production.open()
        runtime = RuntimeManager(
            database, intelligence, control, scraper, production=production
        )
        telemetry = TelemetryRegistry()
        dispatcher = AlertDispatcher(
            production,
            interval_seconds=settings.alert_dispatch_interval_seconds,
            timeout_seconds=settings.alert_delivery_timeout_seconds,
        )
        dispatcher.start()
        watch_scheduler: asyncio.Task[None] | None = None
        if settings.watch_scheduler_enabled:
            watch_service = WatchlistService(
                scraper, database, intelligence, control=control
            )
            watch_scheduler = asyncio.create_task(
                _watch_scheduler_loop(
                    watch_service, production, control, settings.watch_scheduler_poll_seconds
                ),
                name="watchlist-scheduler",
            )
        app.state.settings = settings
        app.state.database = database
        app.state.intelligence = intelligence
        app.state.control = control
        app.state.production = production
        app.state.scraper = scraper
        app.state.runtime = runtime
        app.state.telemetry = telemetry
        app.state.dispatcher = dispatcher
        try:
            yield
        finally:
            if watch_scheduler is not None:
                watch_scheduler.cancel()
                await asyncio.gather(watch_scheduler, return_exceptions=True)
            await dispatcher.stop()
            await runtime.shutdown()
            await scraper.aclose()
            await production.close()
            await control.close()
            await intelligence.close()
            await database.close()

    app = FastAPI(
        title="AlibabaScraper",
        version="0.5.0",
        description="Authenticated Alibaba public-product collection and sourcing operations API.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def production_middleware(request: Request, call_next: Any):
        timer = RequestTimer()
        status_code = 500
        try:
            if _requires_auth(request.url.path, require_auth):
                raw_key = request.headers.get("X-API-Key") or request.cookies.get(
                    "alibaba_api_key", ""
                )
                principal = await request.app.state.production.authenticate(raw_key)
                if principal is None:
                    status_code = 401
                    return JSONResponse(
                        status_code=401, content={"detail": "valid API key required"}
                    )
                required_scope = _required_scope(request.method, request.url.path)
                if not principal.allows(required_scope):
                    status_code = 403
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"API key requires {required_scope} scope"},
                    )
                request.state.api_principal = principal
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            telemetry = getattr(request.app.state, "telemetry", None)
            if telemetry is not None:
                await telemetry.observe(
                    request.method, request.url.path, status_code, timer.elapsed()
                )

    register_core_routes(app)
    register_production_routes(app)
    _install_openapi_security(app, require_auth)
    return app


async def _watch_scheduler_loop(
    service: WatchlistService,
    production: ProductionRepository,
    control: ControlRepository,
    poll_seconds: float,
) -> None:
    while True:
        runs = await service.run_due()
        if runs:
            await production.rescore_category_profiles(control)
        await asyncio.sleep(poll_seconds)


def _requires_auth(path: str, auth_required: bool) -> bool:
    if not auth_required:
        return False
    if path == "/api/health/live":
        return False
    return path.startswith("/api/") or path == "/metrics"


def _required_scope(method: str, path: str) -> Scope:
    if path == "/api/auth/session":
        return "read"
    if path.startswith("/api/admin/"):
        return "admin"
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    return "write"


def _install_openapi_security(app: FastAPI, auth_required: bool) -> None:
    if not auth_required:
        return
    original_openapi = app.openapi

    def secured_openapi() -> dict[str, Any]:
        schema = original_openapi()
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["ApiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "AlibabaScraper API key created by the local CLI.",
        }
        for path, item in schema.get("paths", {}).items():
            if not path.startswith("/api/") or path == "/api/health/live":
                continue
            for operation in item.values():
                if isinstance(operation, dict) and "responses" in operation:
                    operation["security"] = [{"ApiKeyAuth": []}]
        return schema

    app.openapi = secured_openapi  # type: ignore[method-assign]
