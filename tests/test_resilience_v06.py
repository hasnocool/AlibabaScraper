from decimal import Decimal
from pathlib import Path

import pytest

from alibaba_scraper.control import ControlRepository
from alibaba_scraper.database import Database
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.models import PriceRange, ProductRecord
from alibaba_scraper.production import ProductionRepository
from alibaba_scraper.resilience import ResilienceRepository


async def test_targeted_queue_retry_only_resets_selected_errors(tmp_path: Path) -> None:
    path = tmp_path / "retry.sqlite3"
    async with Database(path) as database:
        job_id = await database.create_job("solar", 10, 1)
        await database.enqueue(
            job_id,
            [
                ("https://example.test/a", "100001"),
                ("https://example.test/b", "100002"),
            ],
        )
        claimed = await database.claim_pending(job_id, 2)
        await database.mark_queue_error(claimed[0].id, "timeout from upstream")
        await database.mark_queue_error(claimed[1].id, "parser failed")

        async with ResilienceRepository(path) as resilience:
            errors = await resilience.list_failed_queue(job_id, error_contains="timeout")
            assert [row["id"] for row in errors] == [claimed[0].id]
            result = await resilience.retry_failed_queue(
                job_id,
                queue_ids=[claimed[0].id],
                reset_attempts=True,
            )
            assert result["retried"] == 1
            remaining = await resilience.list_failed_queue(job_id)
            assert [row["id"] for row in remaining] == [claimed[1].id]

        pending = await database.claim_pending(job_id, 10)
        assert [row.id for row in pending] == [claimed[0].id]
        assert pending[0].attempts == 1


async def test_retry_refuses_running_job(tmp_path: Path) -> None:
    path = tmp_path / "running.sqlite3"
    async with Database(path) as database:
        job_id = await database.create_job("solar", 10, 1)
        await database.mark_job_running(job_id)
        async with ResilienceRepository(path) as resilience:
            with pytest.raises(RuntimeError, match="running"):
                await resilience.retry_failed_queue(job_id)


async def test_supplier_quality_history_uses_observed_catalog_data(tmp_path: Path) -> None:
    path = tmp_path / "quality.sqlite3"
    record = ProductRecord(
        source_url="https://www.alibaba.com/product-detail/example_1600000000009.html",
        title="Solar module",
        product_id="1600000000009",
        supplier_name="Example Supplier",
        supplier_url="https://supplier.example.test",
        supplier_country="CN",
        category="Solar Panels",
        minimum_order_quantity=Decimal("5"),
        price=PriceRange(currency="USD", minimum=Decimal("20"), maximum=Decimal("25")),
    )
    async with (
        Database(path) as database,
        IntelligenceRepository(path) as intelligence,
        ControlRepository(path),
        ProductionRepository(path),
        ResilienceRepository(path) as resilience,
    ):
        product_key = await database.upsert_product(record)
        await intelligence.record_product(
            record,
            product_key,
            previous=None,
            job_id=None,
        )
        suppliers = await intelligence.list_suppliers()
        assert len(suppliers) == 1
        snapshots = await resilience.snapshot_supplier_quality()
        assert len(snapshots) == 1
        assert snapshots[0]["product_count"] == 1
        assert snapshots[0]["completeness_pct"] == 100.0
        assert 0 <= snapshots[0]["quality_score"] <= 100
        history = await resilience.supplier_quality_history(suppliers[0].supplier_key)
        assert len(history) == 1
