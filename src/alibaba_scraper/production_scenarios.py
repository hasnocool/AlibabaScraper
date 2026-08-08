# src/alibaba_scraper/production_scenarios.py
"""Saved landed-cost scenario methods."""

from datetime import UTC, datetime

import aiosqlite

from .landed_cost import LandedCostInput, LandedCostResult, calculate_landed_cost
from .production_models import LandedCostScenario, LandedCostScenarioInput


class ScenarioMixin:
    async def save_landed_scenario(self, values: LandedCostScenarioInput) -> LandedCostScenario:
        result = calculate_landed_cost(values.values)
        now = _now()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO landed_cost_scenarios(
                    name,product_key,input_json,result_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    product_key=excluded.product_key,input_json=excluded.input_json,
                    result_json=excluded.result_json,updated_at=excluded.updated_at
                RETURNING id
                """,
                (
                    values.name.strip(),
                    values.product_key,
                    values.values.model_dump_json(),
                    result.model_dump_json(),
                    now,
                    now,
                ),
            )
            row = await cursor.fetchone()
            await self.connection.commit()
        return await self.get_landed_scenario(int(row["id"]))

    async def get_landed_scenario(self, scenario_id: int) -> LandedCostScenario:
        row = await (
            await self.connection.execute(
                "SELECT * FROM landed_cost_scenarios WHERE id=?", (scenario_id,)
            )
        ).fetchone()
        if row is None:
            raise KeyError(f"landed-cost scenario {scenario_id} does not exist")
        return _scenario(row)

    async def list_landed_scenarios(self, limit: int = 100) -> list[LandedCostScenario]:
        rows = await (
            await self.connection.execute(
                "SELECT * FROM landed_cost_scenarios ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        ).fetchall()
        return [_scenario(row) for row in rows]

    async def delete_landed_scenario(self, scenario_id: int) -> None:
        await self.get_landed_scenario(scenario_id)
        async with self._write_lock:
            await self.connection.execute(
                "DELETE FROM landed_cost_scenarios WHERE id=?", (scenario_id,)
            )
            await self.connection.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scenario(row: aiosqlite.Row) -> LandedCostScenario:
    return LandedCostScenario(
        id=int(row["id"]),
        name=row["name"],
        product_key=row["product_key"],
        values=LandedCostInput.model_validate_json(row["input_json"]),
        result=LandedCostResult.model_validate_json(row["result_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
