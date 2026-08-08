# tests/test_alert_delivery_v05.py
import hashlib
import hmac
from pathlib import Path

import httpx

from alibaba_scraper.alert_delivery import deliver_pending_alerts
from alibaba_scraper.control import ControlRepository
from alibaba_scraper.database import Database
from alibaba_scraper.production import AlertSinkInput, ProductionRepository


async def test_webhook_delivery_is_signed_and_recorded(tmp_path: Path) -> None:
    path = tmp_path / "alerts.sqlite3"
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    async with (
        Database(path),
        ControlRepository(path) as control,
        ProductionRepository(path) as prod,
    ):
        await prod.create_alert_sink(
            AlertSinkInput(
                name="ops-webhook",
                endpoint="https://example.test/hook",
                secret="shared-secret",
                event_kinds=["watchlist_change"],
            )
        )
        await control.create_alert(
            kind="watchlist_change",
            severity="info",
            title="Changed",
            message="A tracked product changed.",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await deliver_pending_alerts(prod, client=client)

        assert result["delivered"] == 1
        assert len(received) == 1
        request = received[0]
        expected = hmac.new(b"shared-secret", request.content, hashlib.sha256).hexdigest()
        assert request.headers["X-AlibabaScraper-Signature"] == f"sha256={expected}"
        assert (await prod.delivery_summary())["delivered"] == 1
