from pathlib import Path

from fastapi.testclient import TestClient

from alibaba_scraper.service import create_app


def test_service_health_dashboard_profiles_and_landed_cost(tmp_path: Path) -> None:
    app = create_app(tmp_path / "service.sqlite3", auth_required=False)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["version"] == "0.6.0"
        assert health.json()["schema_current"] == 2

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "AlibabaScraper" in dashboard.text

        summary = client.get("/api/dashboard")
        assert summary.status_code == 200
        assert summary.json()["products"] == 0

        profiles = client.get("/api/scoring/profiles")
        assert profiles.status_code == 200
        assert profiles.json()[0]["active"] is True

        cost = client.post(
            "/api/landed-cost",
            json={
                "currency": "USD",
                "unit_price": "5",
                "quantity": "20",
                "shipping": "25",
            },
        )
        assert cost.status_code == 200
        assert cost.json()["landed_total"] == "125.00"
