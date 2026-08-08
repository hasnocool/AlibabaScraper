# tests/test_database.py
"""SQLite persistence and resumability tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alibaba_scraper.database import Database
from alibaba_scraper.models import PriceRange, ProductRecord


async def test_queue_claim_is_resumable(tmp_path) -> None:
    database_path = tmp_path / "test.sqlite3"
    async with Database(database_path) as db:
        job_id = await db.create_job("solar panel", 10, 2)
        await db.enqueue(
            job_id,
            [
                ("https://www.alibaba.com/product-detail/A_1600000000001.html", "1600000000001"),
                ("https://www.alibaba.com/product-detail/B_1600000000002.html", "1600000000002"),
            ],
        )
        batch = await db.claim_pending(job_id, 1)
        assert len(batch) == 1
        assert batch[0].status == "in_progress"

        await db.mark_job_running(job_id)
        claimed_again = await db.claim_pending(job_id, 2)
        assert len(claimed_again) == 2


async def test_product_history_records_only_tracked_changes(tmp_path) -> None:
    database_path = tmp_path / "test.sqlite3"
    base_time = datetime(2026, 8, 8, tzinfo=UTC)
    first = ProductRecord(
        source_url="https://www.alibaba.com/product-detail/A_1600000000001.html",
        product_id="1600000000001",
        price=PriceRange(currency="USD", minimum=Decimal("10"), maximum=Decimal("12")),
        minimum_order_quantity=Decimal("100"),
        minimum_order_unit="pieces",
        scraped_at=base_time,
    )
    unchanged = first.model_copy(update={"scraped_at": base_time + timedelta(hours=1)})
    changed = first.model_copy(
        update={
            "price": PriceRange(currency="USD", minimum=Decimal("9"), maximum=Decimal("11")),
            "scraped_at": base_time + timedelta(hours=2),
        }
    )

    async with Database(database_path) as db:
        await db.upsert_product(first)
        await db.upsert_product(unchanged)
        await db.upsert_product(changed)
        history = await db.product_history("1600000000001")

    assert len(history) == 2
    assert history[0]["price_min"] == "10"
    assert history[1]["price_min"] == "9"
