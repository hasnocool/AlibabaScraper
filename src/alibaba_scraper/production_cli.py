# src/alibaba_scraper/production_cli.py
"""Production-operation CLI commands."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from .alert_delivery import deliver_pending_alerts
from .control import ControlRepository
from .installer import install_systemd_service, systemd_status, uninstall_systemd_service
from .landed_cost import LandedCostInput
from .migrations import CURRENT_SCHEMA_VERSION, migrate_database, schema_version
from .production import (
    AlertSinkInput,
    CategoryProfileBindingInput,
    LandedCostScenarioInput,
    ProductionRepository,
)


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def register_production_commands(app: typer.Typer) -> None:
    @app.command("migrate")
    def migrate_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        """Apply pending schema migrations."""

        async def run() -> dict[str, object]:
            applied = await migrate_database(database)
            return {
                "applied": applied,
                "schema_version": await schema_version(database),
                "current_version": CURRENT_SCHEMA_VERSION,
            }

        typer.echo(_json(asyncio.run(run())))

    @app.command("api-key-create")
    def api_key_create_command(
        name: Annotated[str, typer.Argument(help="Unique API key name")],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        scopes: Annotated[str, typer.Option("--scopes")] = "read,write",
        expires_days: Annotated[int | None, typer.Option("--expires-days", min=1)] = None,
    ) -> None:
        """Create an API key; the plaintext key is shown exactly once."""

        async def run() -> object:
            expires = (
                datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
            )
            async with ProductionRepository(database) as production:
                return await production.create_api_key(
                    name,
                    [scope.strip() for scope in scopes.split(",") if scope.strip()],
                    expires,
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("api-keys")
    def api_keys_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        """List API key metadata; plaintext keys are never persisted."""

        async def run() -> list[object]:
            async with ProductionRepository(database) as production:
                return [row.model_dump(mode="json") for row in await production.list_api_keys()]

        typer.echo(_json(asyncio.run(run())))

    @app.command("api-key-revoke")
    def api_key_revoke_command(
        key_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> object:
            async with ProductionRepository(database) as production:
                return (await production.revoke_api_key(key_id)).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("service-install")
    def service_install_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        env_file: Annotated[Path, typer.Option("--env-file")] = Path(".env"),
        user_mode: Annotated[bool, typer.Option("--user/--system")] = True,
        start: Annotated[bool, typer.Option("--start/--no-start")] = True,
    ) -> None:
        """Install and optionally start the systemd service."""

        async def validate() -> None:
            await migrate_database(database)
            async with ProductionRepository(database) as production:
                if not await production.list_api_keys():
                    raise RuntimeError(
                        "create an API key first with `alibaba-scraper api-key-create ...`"
                    )

        asyncio.run(validate())
        result = install_systemd_service(
            user_mode=user_mode,
            env_file=env_file,
            database_path=database,
            start=start,
        )
        typer.echo(_json(result.__dict__))

    @app.command("service-uninstall")
    def service_uninstall_command(
        user_mode: Annotated[bool, typer.Option("--user/--system")] = True,
    ) -> None:
        typer.echo(str(uninstall_systemd_service(user_mode=user_mode)))

    @app.command("service-status")
    def service_status_command(
        user_mode: Annotated[bool, typer.Option("--user/--system")] = True,
    ) -> None:
        result = systemd_status(user_mode=user_mode)
        typer.echo(result.stdout or result.stderr)
        if result.returncode not in {0, 3}:
            raise typer.Exit(result.returncode)

    @app.command("landed-scenario-save")
    def landed_scenario_save_command(
        name: Annotated[str, typer.Argument()],
        unit_price: Annotated[Decimal, typer.Argument()],
        quantity: Annotated[Decimal, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        product_key: Annotated[str | None, typer.Option("--product-key")] = None,
        currency: Annotated[str, typer.Option("--currency")] = "USD",
        shipping: Annotated[Decimal, typer.Option("--shipping", min=0)] = Decimal("0"),
        duty_pct: Annotated[Decimal, typer.Option("--duty-pct", min=0)] = Decimal("0"),
        tax_pct: Annotated[Decimal, typer.Option("--tax-pct", min=0)] = Decimal("0"),
        packaging_per_unit: Annotated[
            Decimal, typer.Option("--packaging-per-unit", min=0)
        ] = Decimal("0"),
    ) -> None:
        values = LandedCostScenarioInput(
            name=name,
            product_key=product_key,
            values=LandedCostInput(
                currency=currency,
                unit_price=unit_price,
                quantity=quantity,
                shipping=shipping,
                duty_rate_pct=duty_pct,
                tax_rate_pct=tax_pct,
                packaging_per_unit=packaging_per_unit,
            ),
        )

        async def run() -> object:
            async with ProductionRepository(database) as production:
                return (await production.save_landed_scenario(values)).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("landed-scenarios")
    def landed_scenarios_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> list[object]:
            async with ProductionRepository(database) as production:
                return [
                    row.model_dump(mode="json")
                    for row in await production.list_landed_scenarios()
                ]

        typer.echo(_json(asyncio.run(run())))

    @app.command("profile-bind-category")
    def profile_bind_category_command(
        pattern: Annotated[str, typer.Argument(help="Case-insensitive glob, e.g. *solar*")],
        profile_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        priority: Annotated[int, typer.Option("--priority")] = 100,
    ) -> None:
        async def run() -> object:
            async with ProductionRepository(database) as production:
                return (
                    await production.bind_category_profile(
                        CategoryProfileBindingInput(
                            category_pattern=pattern,
                            profile_id=profile_id,
                            priority=priority,
                        )
                    )
                ).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("profile-bindings")
    def profile_bindings_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> list[object]:
            async with ProductionRepository(database) as production:
                return [
                    row.model_dump(mode="json")
                    for row in await production.list_category_bindings()
                ]

        typer.echo(_json(asyncio.run(run())))

    @app.command("category-rescore")
    def category_rescore_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> int:
            async with (
                ProductionRepository(database) as production,
                ControlRepository(database) as control,
            ):
                return await production.rescore_category_profiles(control)

        typer.echo(_json({"rescored": asyncio.run(run())}))

    @app.command("alert-sink-add")
    def alert_sink_add_command(
        name: Annotated[str, typer.Argument()],
        endpoint: Annotated[str, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        secret: Annotated[str | None, typer.Option("--secret")] = None,
        event_kinds: Annotated[str, typer.Option("--event-kinds")] = "",
        minimum_severity: Annotated[str, typer.Option("--minimum-severity")] = "info",
    ) -> None:
        async def run() -> object:
            async with ProductionRepository(database) as production:
                return (
                    await production.create_alert_sink(
                        AlertSinkInput(
                            name=name,
                            endpoint=endpoint,
                            secret=secret,
                            event_kinds=[x.strip() for x in event_kinds.split(",") if x.strip()],
                            minimum_severity=minimum_severity,  # type: ignore[arg-type]
                        )
                    )
                ).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("alert-sinks")
    def alert_sinks_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> list[object]:
            async with ProductionRepository(database) as production:
                return [row.model_dump(mode="json") for row in await production.list_alert_sinks()]

        typer.echo(_json(asyncio.run(run())))

    @app.command("alert-deliver")
    def alert_deliver_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        async def run() -> dict[str, int]:
            async with ProductionRepository(database) as production:
                return await deliver_pending_alerts(production, limit=limit)

        typer.echo(_json(asyncio.run(run())))

    @app.command("compare")
    def compare_command(
        identifiers: Annotated[list[str], typer.Argument(help="Product IDs or keys")],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> list[dict[str, object]]:
            async with (
                ProductionRepository(database) as production,
                ControlRepository(database) as control,
            ):
                return await production.compare_products(identifiers, control)

        typer.echo(_json(asyncio.run(run())))
