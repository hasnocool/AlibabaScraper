from pathlib import Path

from alibaba_scraper.control import ControlRepository
from alibaba_scraper.database import Database
from alibaba_scraper.production import AlertSinkInput, ProductionRepository


async def test_alert_failures_backoff_then_dead_letter_and_can_be_requeued(tmp_path: Path) -> None:
    path = tmp_path / "dlq.sqlite3"
    async with (
        Database(path),
        ControlRepository(path) as control,
        ProductionRepository(path) as production,
    ):
        sink = await production.create_alert_sink(
            AlertSinkInput(
                name="ops",
                endpoint="https://example.test/hook",
                max_attempts=2,
                base_backoff_seconds=60,
                max_backoff_seconds=60,
            )
        )
        alert = await control.create_alert(
            kind="watchlist_change",
            severity="info",
            title="Changed",
            message="Something changed",
        )
        first = await production.record_delivery(
            alert.id, sink.id, success=False, error="network"
        )
        assert first == "failed"
        assert await production.pending_deliveries() == []

        second = await production.record_delivery(
            alert.id, sink.id, success=False, error="network again"
        )
        assert second == "dead_letter"
        dead = await production.list_dead_letters()
        assert len(dead) == 1
        assert dead[0]["attempts"] == 2

        await production.retry_dead_letter(dead[0]["id"])
        pending = await production.pending_deliveries()
        assert len(pending) == 1
        assert pending[0]["alert_id"] == alert.id
