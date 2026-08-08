from pathlib import Path

from fastapi.testclient import TestClient

from alibaba_scraper.service import create_app


def test_resilience_routes_are_wired_through_service(tmp_path: Path) -> None:
    database = tmp_path / "service-resilience.sqlite3"
    app = create_app(database, auth_required=False)
    with TestClient(app) as client:
        created = client.post(
            "/api/admin/api-keys",
            json={"name": "admin", "scopes": ["admin"]},
        )
        assert created.status_code == 201
        key_id = created.json()["record"]["id"]

        rotated = client.post(
            f"/api/admin/api-keys/{key_id}/rotate",
            json={"grace_minutes": 0},
        )
        assert rotated.status_code == 201
        replacement_id = rotated.json()["record"]["id"]

        token = client.post(
            f"/api/admin/api-keys/{replacement_id}/tokens",
            json={"ttl_minutes": 5, "scopes": ["read"]},
        )
        assert token.status_code == 201
        assert token.json()["record"]["kind"] == "token"

        integrity = client.get("/api/admin/database/integrity")
        assert integrity.status_code == 200
        assert integrity.json()["status"] == "ok"

        backup_path = tmp_path / "api-backup.sqlite3"
        backup = client.post(
            "/api/admin/database/backup",
            json={"destination": str(backup_path)},
        )
        assert backup.status_code == 200
        assert backup.json()["integrity"] == "ok"
        assert backup_path.exists()

        snapshot = client.post("/api/suppliers/quality/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["snapshots"] == 0

        dead = client.get("/api/admin/alert-deliveries/dead-letter")
        assert dead.status_code == 200
        assert dead.json() == []
