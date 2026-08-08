# tests/test_control_v04.py
from decimal import Decimal
from pathlib import Path

from alibaba_scraper.control import ControlRepository, ScoringProfileInput
from alibaba_scraper.database import Database
from alibaba_scraper.intelligence import IntelligenceRepository
from alibaba_scraper.models import PriceRange, ProductRecord


async def _seed(database_path: Path) -> tuple[int, str]:
    url = "https://www.alibaba.com/product-detail/Test_1600000000401.html"
    record = ProductRecord(
        source_url=url,
        canonical_url=url,
        title="Low MOQ test product",
        product_id="1600000000401",
        supplier_name="Example Supplier",
        supplier_country="CN",
        category="Test",
        price=PriceRange(currency="USD", minimum=Decimal("8"), maximum=Decimal("9")),
        minimum_order_quantity=Decimal("1"),
        minimum_order_unit="piece",
        attributes={"Material": "Test"},
    )
    async with Database(database_path) as database, IntelligenceRepository(database_path) as intel:
        job_id = await database.create_job("test", 1, 1)
        await database.enqueue(job_id, [(url, record.product_id)])
        item = (await database.claim_pending(job_id, 1))[0]
        product_key = await database.upsert_product(record)
        await intel.record_product(record, product_key, previous=None, job_id=job_id)
        await database.mark_queue_done(item.id)
        await intel.rescore_job(job_id)
    return job_id, product_key


async def test_control_profiles_filters_and_alerts(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    job_id, product_key = await _seed(path)

    async with ControlRepository(path) as control:
        assert (await control.active_profile()).name == "Default"
        rescored = await control.rescore(job_id=job_id)
        assert rescored == 1
        products = await control.list_products(min_score=1, limit=10)
        assert products[0]["product_key"] == product_key

        profile = await control.create_profile(
            ScoringProfileInput(
                name="MOQ first",
                price_weight=0,
                moq_weight=100,
                supplier_weight=0,
                tier_weight=0,
                data_quality_weight=0,
                min_score_alert=90,
                activate=True,
            )
        )
        assert profile.active is True
        assert await control.rescore(profile_id=profile.id, job_id=job_id) == 1
        products = await control.list_products(min_score=99, limit=10)
        assert products[0]["score"] == 100.0

        alert = await control.alert_for_high_scores(job_id)
        assert alert is not None
        assert alert.kind == "high_score"
        unread = await control.list_alerts(unread_only=True)
        assert unread[0].id == alert.id
        read = await control.mark_alert_read(alert.id)
        assert read.read_at is not None
