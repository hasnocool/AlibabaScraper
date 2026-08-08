# src/alibaba_scraper/production_scoring.py
"""Category-specific profile scoring and comparison methods."""

import fnmatch
import json
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median
from typing import Any

import aiosqlite

from .control import ControlRepository
from .models import ProductRecord
from .production_models import CategoryProfileBinding, CategoryProfileBindingInput
from .scoring import score_product


class CategoryScoringMixin:
    async def bind_category_profile(
        self, values: CategoryProfileBindingInput
    ) -> CategoryProfileBinding:
        now = _now()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO category_scoring_bindings(
                    category_pattern,profile_id,priority,enabled,created_at,updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(category_pattern) DO UPDATE SET
                    profile_id=excluded.profile_id,priority=excluded.priority,
                    enabled=excluded.enabled,updated_at=excluded.updated_at
                RETURNING id
                """,
                (
                    values.category_pattern,
                    values.profile_id,
                    values.priority,
                    int(values.enabled),
                    now,
                    now,
                ),
            )
            row = await cursor.fetchone()
            await self.connection.commit()
        return await self.get_category_binding(int(row["id"]))

    async def get_category_binding(self, binding_id: int) -> CategoryProfileBinding:
        row = await (
            await self.connection.execute(
                "SELECT * FROM category_scoring_bindings WHERE id=?", (binding_id,)
            )
        ).fetchone()
        if row is None:
            raise KeyError(f"category binding {binding_id} does not exist")
        return _binding(row)

    async def list_category_bindings(self) -> list[CategoryProfileBinding]:
        rows = await (
            await self.connection.execute(
                """
                SELECT * FROM category_scoring_bindings
                ORDER BY priority DESC,id
                """
            )
        ).fetchall()
        return [_binding(row) for row in rows]

    async def delete_category_binding(self, binding_id: int) -> None:
        await self.get_category_binding(binding_id)
        async with self._write_lock:
            await self.connection.execute(
                "DELETE FROM category_scoring_bindings WHERE id=?", (binding_id,)
            )
            await self.connection.commit()

    async def resolve_category_profile(self, category: str | None) -> int | None:
        if not category:
            return None
        normalized = category.strip().lower()
        for binding in await self.list_category_bindings():
            if binding.enabled and fnmatch.fnmatchcase(normalized, binding.category_pattern):
                return binding.profile_id
        return None

    async def rescore_category_profiles(self, control: ControlRepository) -> int:
        rows = await (
            await self.connection.execute(
                "SELECT product_key,category,record_json FROM products WHERE category IS NOT NULL"
            )
        ).fetchall()
        assigned: list[tuple[str, str, ProductRecord, int]] = []
        for row in rows:
            profile_id = await self.resolve_category_profile(row["category"])
            if profile_id is None:
                continue
            assigned.append(
                (
                    row["product_key"],
                    row["category"],
                    ProductRecord.model_validate_json(row["record_json"]),
                    profile_id,
                )
            )
        medians: dict[tuple[int, str | None], Decimal] = {}
        price_groups: dict[tuple[int, str | None], list[Decimal]] = {}
        for _, _, record, profile_id in assigned:
            if record.price and record.price.minimum is not None:
                price_groups.setdefault((profile_id, record.price.currency), []).append(
                    record.price.minimum
                )
        for key, values in price_groups.items():
            medians[key] = median(values)
        profile_ids = {profile_id for *_, profile_id in assigned}
        profiles = {
            profile_id: await control.get_profile(profile_id) for profile_id in profile_ids
        }
        now = _now()
        async with self._write_lock:
            for product_key, category, record, profile_id in assigned:
                profile = profiles[profile_id]
                currency = record.price.currency if record.price else None
                result = score_product(
                    record,
                    peer_median_price=medians.get((profile_id, currency)),
                    weights=profile.weights(),
                )
                await self.connection.execute(
                    """
                    INSERT INTO category_profile_scores(
                        product_key,profile_id,category,score,price_value,moq_score,
                        supplier_confidence,tier_discount,data_quality,peer_median_price,
                        reasons_json,scored_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(product_key) DO UPDATE SET
                        profile_id=excluded.profile_id,category=excluded.category,
                        score=excluded.score,price_value=excluded.price_value,
                        moq_score=excluded.moq_score,
                        supplier_confidence=excluded.supplier_confidence,
                        tier_discount=excluded.tier_discount,
                        data_quality=excluded.data_quality,
                        peer_median_price=excluded.peer_median_price,
                        reasons_json=excluded.reasons_json,scored_at=excluded.scored_at
                    """,
                    (
                        product_key,
                        profile_id,
                        category,
                        result.total,
                        result.price_value,
                        result.moq,
                        result.supplier_confidence,
                        result.tier_discount,
                        result.data_quality,
                        str(result.peer_median_price) if result.peer_median_price else None,
                        json.dumps(result.reasons, ensure_ascii=False),
                        now,
                    ),
                )
            await self.connection.commit()
        return len(assigned)

    async def compare_products(
        self, identifiers: list[str], control: ControlRepository
    ) -> list[dict[str, Any]]:
        if not identifiers:
            return []
        results: list[dict[str, Any]] = []
        active = await control.active_profile()
        for identifier in identifiers[:12]:
            row = await (
                await self.connection.execute(
                    """
                    SELECT p.product_key,p.product_id,p.title,p.supplier_name,p.category,
                           p.price_min,p.price_max,p.currency,p.moq,p.moq_unit,p.last_seen_at,
                           ps.score AS active_score,cps.score AS category_score,
                           cps.profile_id AS category_profile_id
                    FROM products p
                    LEFT JOIN profile_scores ps
                      ON ps.product_key=p.product_key AND ps.profile_id=?
                    LEFT JOIN category_profile_scores cps ON cps.product_key=p.product_key
                    WHERE p.product_key=? OR p.product_id=? LIMIT 1
                    """,
                    (active.id, identifier, identifier),
                )
            ).fetchone()
            if row is None:
                continue
            data = dict(row)
            data["effective_score"] = data["category_score"] or data["active_score"]
            results.append(data)
        return results

    async def price_history(self, identifier: str) -> list[dict[str, Any]]:
        row = await (
            await self.connection.execute(
                "SELECT product_key FROM products WHERE product_key=? OR product_id=? LIMIT 1",
                (identifier, identifier),
            )
        ).fetchone()
        if row is None:
            return []
        rows = await (
            await self.connection.execute(
                """
                SELECT observed_at,price_min,price_max,currency,moq,moq_unit
                FROM product_observations WHERE product_key=? ORDER BY id
                """,
                (row["product_key"],),
            )
        ).fetchall()
        return [dict(item) for item in rows]

    async def analytics(self) -> dict[str, Any]:
        score_rows = await (
            await self.connection.execute(
                """
                SELECT
                  CASE
                    WHEN score < 40 THEN '0-39'
                    WHEN score < 60 THEN '40-59'
                    WHEN score < 75 THEN '60-74'
                    WHEN score < 90 THEN '75-89'
                    ELSE '90-100'
                  END AS bucket,
                  COUNT(*) AS count
                FROM category_profile_scores GROUP BY bucket
                ORDER BY MIN(score)
                """
            )
        ).fetchall()
        category_rows = await (
            await self.connection.execute(
                """
                SELECT COALESCE(category,'Uncategorized') AS category,
                       COUNT(*) AS products,
                       COUNT(DISTINCT supplier_name) AS suppliers
                FROM products GROUP BY category ORDER BY products DESC LIMIT 20
                """
            )
        ).fetchall()
        return {
            "score_distribution": [dict(row) for row in score_rows],
            "categories": [dict(row) for row in category_rows],
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _binding(row: aiosqlite.Row) -> CategoryProfileBinding:
    return CategoryProfileBinding(
        id=int(row["id"]),
        category_pattern=row["category_pattern"],
        profile_id=int(row["profile_id"]),
        priority=int(row["priority"]),
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
