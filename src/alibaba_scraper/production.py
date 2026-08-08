# src/alibaba_scraper/production.py
"""Production-operation repository facade."""

import asyncio
from pathlib import Path

import aiosqlite

from .migrations import migrate_database
from .production_auth import ApiKeyMixin
from .production_models import (
    AlertSink,
    AlertSinkInput,
    ApiKeyCreated,
    ApiKeyRecord,
    ApiPrincipal,
    CategoryProfileBinding,
    CategoryProfileBindingInput,
    LandedCostScenario,
    LandedCostScenarioInput,
    Scope,
    Severity,
)
from .production_scenarios import ScenarioMixin
from .production_scoring import CategoryScoringMixin
from .production_sinks import AlertSinkMixin

__all__ = [
    "AlertSink",
    "AlertSinkInput",
    "ApiKeyCreated",
    "ApiKeyRecord",
    "ApiPrincipal",
    "CategoryProfileBinding",
    "CategoryProfileBindingInput",
    "LandedCostScenario",
    "LandedCostScenarioInput",
    "ProductionRepository",
    "Scope",
    "Severity",
]


class ProductionRepository(
    ApiKeyMixin, ScenarioMixin, CategoryScoringMixin, AlertSinkMixin
):
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "ProductionRepository":
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("production repository is not open")
        return self._connection

    async def open(self) -> None:
        await migrate_database(self.path)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA busy_timeout = 5000")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
