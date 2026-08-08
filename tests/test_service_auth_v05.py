# tests/test_service_auth_v05.py
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from alibaba_scraper.production import ProductionRepository
from alibaba_scraper.service import create_app


async def _bootstrap(path: Path) -> str:
    async with ProductionRepository(path) as production:
        created = await production.create_api_key("test-admin", ["admin"])
        return created.api_key


def test_service_requires_key_and_supports_cookie_session(tmp_path: Path) -> None:
    path = tmp_path / "service.sqlite3"
    api_key = asyncio.run(_bootstrap(path))
    app = create_app(path, auth_required=True)
    with TestClient(app) as client:
        assert client.get("/api/health/live").status_code == 200
        assert client.get("/api/health").status_code == 401

        headers = {"X-API-Key": api_key}
        health = client.get("/api/health", headers=headers)
        assert health.status_code == 200
        assert health.json()["version"] == "0.6.0"
        assert health.json()["schema_version"] == 2

        session = client.post("/api/auth/session", headers=headers)
        assert session.status_code == 200
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200

        ops = client.get("/")
        assert ops.status_code == 200
        assert "AlibabaScraper Operations" in ops.text
