# src/alibaba_scraper/service_production_routes.py
"""Production-operations API routes."""

from typing import Annotated

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, Request

from .alert_delivery import deliver_pending_alerts
from .control import ControlRepository
from .production import (
    AlertSinkInput,
    ApiKeyCreated,
    CategoryProfileBindingInput,
    LandedCostScenarioInput,
    ProductionRepository,
)
from .service_models import ApiKeyCreateRequest, ComparisonRequest


def register_production_routes(app: FastAPI) -> None:
    @app.get("/api/analytics")
    async def analytics(request: Request) -> dict[str, object]:
        return await _production(request).analytics()

    @app.post("/api/comparisons/products")
    async def compare_products(
        request: Request, values: ComparisonRequest
    ) -> list[dict[str, object]]:
        return await _production(request).compare_products(values.identifiers, _control(request))

    @app.get("/api/charts/price-history/{identifier:path}")
    async def price_history(request: Request, identifier: str) -> list[dict[str, object]]:
        return await _production(request).price_history(identifier)

    @app.get("/api/landed-cost/scenarios")
    async def landed_scenarios(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        rows = await _production(request).list_landed_scenarios(limit)
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/landed-cost/scenarios", status_code=201)
    async def save_landed_scenario(
        request: Request, values: LandedCostScenarioInput
    ) -> dict[str, object]:
        row = await _production(request).save_landed_scenario(values)
        return row.model_dump(mode="json")

    @app.get("/api/landed-cost/scenarios/{scenario_id}")
    async def landed_scenario(request: Request, scenario_id: int) -> dict[str, object]:
        try:
            row = await _production(request).get_landed_scenario(scenario_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return row.model_dump(mode="json")

    @app.delete("/api/landed-cost/scenarios/{scenario_id}", status_code=204)
    async def delete_landed_scenario(request: Request, scenario_id: int) -> None:
        try:
            await _production(request).delete_landed_scenario(scenario_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/scoring/category-bindings")
    async def category_bindings(request: Request) -> list[dict[str, object]]:
        rows = await _production(request).list_category_bindings()
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/scoring/category-bindings", status_code=201)
    async def bind_category_profile(
        request: Request, values: CategoryProfileBindingInput
    ) -> dict[str, object]:
        try:
            await _control(request).get_profile(values.profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        row = await _production(request).bind_category_profile(values)
        return row.model_dump(mode="json")

    @app.delete("/api/scoring/category-bindings/{binding_id}", status_code=204)
    async def delete_category_binding(request: Request, binding_id: int) -> None:
        try:
            await _production(request).delete_category_binding(binding_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/scoring/category-rescore")
    async def category_rescore(request: Request) -> dict[str, int]:
        count = await _production(request).rescore_category_profiles(_control(request))
        return {"rescored": count}

    @app.get("/api/admin/api-keys")
    async def api_keys(request: Request) -> list[dict[str, object]]:
        rows = await _production(request).list_api_keys()
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/admin/api-keys", status_code=201, response_model=ApiKeyCreated)
    async def create_api_key(request: Request, values: ApiKeyCreateRequest) -> ApiKeyCreated:
        try:
            return await _production(request).create_api_key(
                values.name, values.scopes, values.expires_at
            )
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="API key name already exists") from exc

    @app.delete("/api/admin/api-keys/{key_id}")
    async def revoke_api_key(request: Request, key_id: int) -> dict[str, object]:
        try:
            row = await _production(request).revoke_api_key(key_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return row.model_dump(mode="json")

    @app.get("/api/admin/alert-sinks")
    async def alert_sinks(request: Request) -> list[dict[str, object]]:
        rows = await _production(request).list_alert_sinks()
        return [row.model_dump(mode="json") for row in rows]

    @app.post("/api/admin/alert-sinks", status_code=201)
    async def create_alert_sink(request: Request, values: AlertSinkInput) -> dict[str, object]:
        try:
            row = await _production(request).create_alert_sink(values)
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="alert sink name already exists") from exc
        return row.model_dump(mode="json")

    @app.delete("/api/admin/alert-sinks/{sink_id}", status_code=204)
    async def delete_alert_sink(request: Request, sink_id: int) -> None:
        try:
            await _production(request).delete_alert_sink(sink_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/admin/alert-sinks/deliver")
    async def deliver_alerts(request: Request) -> dict[str, int]:
        settings = request.app.state.settings
        return await deliver_pending_alerts(
            _production(request),
            timeout_seconds=settings.alert_delivery_timeout_seconds,
        )


def _control(request: Request) -> ControlRepository:
    return request.app.state.control


def _production(request: Request) -> ProductionRepository:
    return request.app.state.production
