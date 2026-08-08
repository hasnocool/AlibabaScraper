# tests/test_production_v05.py
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alibaba_scraper.control import ControlRepository, ScoringProfileInput
from alibaba_scraper.database import Database
from alibaba_scraper.landed_cost import LandedCostInput
from alibaba_scraper.models import PriceRange, ProductRecord
from alibaba_scraper.production import (
    CategoryProfileBindingInput,
    LandedCostScenarioInput,
    ProductionRepository,
)


async def test_api_keys_scenarios_and_category_profiles(tmp_path: Path) -> None:
    path = tmp_path / "production.sqlite3"
    async with Database(path) as database, ControlRepository(path) as control:
        async with ProductionRepository(path) as production:
            created = await production.create_api_key(
                "service-admin",
                ["admin"],
                datetime.now(UTC) + timedelta(days=30),
            )
            assert created.api_key.startswith("abs_")
            assert created.api_key not in str(await production.list_api_keys())
            principal = await production.authenticate(created.api_key)
            assert principal is not None and principal.allows("admin")

            scenario = await production.save_landed_scenario(
                LandedCostScenarioInput(
                    name="sample",
                    values=LandedCostInput(
                        currency="CAD",
                        unit_price=Decimal("10"),
                        quantity=Decimal("10"),
                        shipping=Decimal("20"),
                    ),
                )
            )
            assert scenario.result.landed_total == Decimal("120.00")
            assert (await production.list_landed_scenarios())[0].name == "sample"

            profile = await control.create_profile(
                ScoringProfileInput(
                    name="Solar",
                    price_weight=60,
                    moq_weight=20,
                    supplier_weight=10,
                    tier_weight=5,
                    data_quality_weight=5,
                )
            )
            await production.bind_category_profile(
                CategoryProfileBindingInput(
                    category_pattern="*solar*",
                    profile_id=profile.id,
                )
            )
            record = ProductRecord(
                source_url=(
                    "https://www.alibaba.com/product-detail/example_1600000000001.html"
                ),
                title="Solar panel",
                product_id="1600000000001",
                supplier_name="Supplier",
                supplier_country="CN",
                category="Solar Panels",
                minimum_order_quantity=Decimal("5"),
                price=PriceRange(
                    currency="USD", minimum=Decimal("25"), maximum=Decimal("30")
                ),
            )
            await database.upsert_product(record)
            assert await production.rescore_category_profiles(control) == 1
            compared = await production.compare_products(["1600000000001"], control)
            assert compared[0]["category_profile_id"] == profile.id
            assert compared[0]["category_score"] is not None

            revoked = await production.revoke_api_key(created.record.id)
            assert revoked.enabled is False
            assert await production.authenticate(created.api_key) is None
