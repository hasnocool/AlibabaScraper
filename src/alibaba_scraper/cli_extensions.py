# src/alibaba_scraper/cli_extensions.py
"""FastAPI, dashboard, catalog, profile, alert, and landed-cost CLI commands."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from .control import ControlRepository, ScoringProfileInput
from .dashboard import dashboard_snapshot, render_terminal_dashboard, watch_terminal_dashboard
from .landed_cost import LandedCostInput, calculate_landed_cost


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def register_commands(app: typer.Typer) -> None:
    """Register service/control-plane commands on the main Typer app."""

    @app.command("serve")
    def serve_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        host: Annotated[str, typer.Option("--host", help="Bind address")] = "127.0.0.1",
        port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8787,
        log_level: Annotated[str, typer.Option("--log-level")] = "info",
    ) -> None:
        """Run the local FastAPI service and browser dashboard."""
        import uvicorn

        from .service import create_app

        uvicorn.run(create_app(database), host=host, port=port, log_level=log_level)

    @app.command("dashboard")
    def dashboard_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        watch: Annotated[bool, typer.Option("--watch", help="Continuously refresh")] = False,
        refresh_seconds: Annotated[
            float,
            typer.Option("--refresh-seconds", min=1.0),
        ] = 5.0,
    ) -> None:
        """Show the terminal dashboard once or continuously."""
        try:
            if watch:
                asyncio.run(watch_terminal_dashboard(database, refresh_seconds))
                return
            typer.echo(render_terminal_dashboard(asyncio.run(dashboard_snapshot(database))))
        except KeyboardInterrupt:
            typer.echo("dashboard stopped")

    @app.command("products")
    def products_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        query: Annotated[str | None, typer.Option("--query", "-q")] = None,
        supplier_key: Annotated[str | None, typer.Option("--supplier-key")] = None,
        currency: Annotated[str | None, typer.Option("--currency")] = None,
        min_score: Annotated[
            float | None,
            typer.Option("--min-score", min=0, max=100),
        ] = None,
        max_price: Annotated[Decimal | None, typer.Option("--max-price", min=0)] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        """Browse/filter current products with the active scoring profile."""

        async def run() -> list[dict[str, object]]:
            async with ControlRepository(database) as control:
                return await control.list_products(
                    query=query,
                    supplier_key=supplier_key,
                    currency=currency,
                    min_score=min_score,
                    max_price=max_price,
                    limit=limit,
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("product")
    def product_command(
        identifier: Annotated[str, typer.Argument(help="Product key or Alibaba product id")],
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
    ) -> None:
        """Show one product, active score, score reasons, and recent changes."""

        async def run() -> dict[str, object] | None:
            async with ControlRepository(database) as control:
                return await control.get_product(identifier)

        row = asyncio.run(run())
        if row is None:
            raise typer.BadParameter("product not found", param_hint="identifier")
        typer.echo(_json(row))

    @app.command("profiles")
    def profiles_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
    ) -> None:
        """List configurable sourcing-score profiles."""

        async def run() -> list[object]:
            async with ControlRepository(database) as control:
                return [row.model_dump(mode="json") for row in await control.list_profiles()]

        typer.echo(_json(asyncio.run(run())))

    @app.command("profile-add")
    def profile_add_command(
        name: Annotated[str, typer.Argument(help="Unique profile name")],
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        price_weight: Annotated[float, typer.Option("--price-weight", min=0)] = 35.0,
        moq_weight: Annotated[float, typer.Option("--moq-weight", min=0)] = 20.0,
        supplier_weight: Annotated[float, typer.Option("--supplier-weight", min=0)] = 20.0,
        tier_weight: Annotated[float, typer.Option("--tier-weight", min=0)] = 10.0,
        data_quality_weight: Annotated[
            float,
            typer.Option("--data-quality-weight", min=0),
        ] = 15.0,
        min_score_alert: Annotated[
            float,
            typer.Option("--alert-score", min=0, max=100),
        ] = 85.0,
        activate: Annotated[bool, typer.Option("--activate")] = False,
    ) -> None:
        """Create a custom scoring profile."""
        values = ScoringProfileInput(
            name=name,
            price_weight=price_weight,
            moq_weight=moq_weight,
            supplier_weight=supplier_weight,
            tier_weight=tier_weight,
            data_quality_weight=data_quality_weight,
            min_score_alert=min_score_alert,
            activate=activate,
        )

        async def run() -> object:
            async with ControlRepository(database) as control:
                return (await control.create_profile(values)).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("profile-activate")
    def profile_activate_command(
        profile_id: Annotated[int, typer.Argument(help="Scoring profile id")],
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        rescore: Annotated[bool, typer.Option("--rescore/--no-rescore")] = True,
    ) -> None:
        """Activate a scoring profile and optionally rescore the catalog."""

        async def run() -> dict[str, object]:
            async with ControlRepository(database) as control:
                profile = await control.activate_profile(profile_id)
                count = await control.rescore(profile_id=profile_id) if rescore else 0
                return {"profile": profile.model_dump(mode="json"), "rescored": count}

        typer.echo(_json(asyncio.run(run())))

    @app.command("rescore")
    def rescore_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        profile_id: Annotated[int | None, typer.Option("--profile-id")] = None,
        job_id: Annotated[int | None, typer.Option("--job-id")] = None,
    ) -> None:
        """Recalculate active/custom profile scores for all products or one crawl."""

        async def run() -> int:
            async with ControlRepository(database) as control:
                return await control.rescore(profile_id=profile_id, job_id=job_id)

        typer.echo(_json({"rescored": asyncio.run(run()), "job_id": job_id}))

    @app.command("alerts")
    def alerts_command(
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
        unread_only: Annotated[bool, typer.Option("--unread-only")] = False,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        """List watchlist/high-score alerts."""

        async def run() -> list[object]:
            async with ControlRepository(database) as control:
                rows = await control.list_alerts(unread_only=unread_only, limit=limit)
                return [row.model_dump(mode="json") for row in rows]

        typer.echo(_json(asyncio.run(run())))

    @app.command("alert-read")
    def alert_read_command(
        alert_id: Annotated[int, typer.Argument(help="Alert id")],
        database: Annotated[
            Path,
            typer.Option("--database", "-d", help="SQLite database path"),
        ] = Path("data/alibaba.sqlite3"),
    ) -> None:
        """Mark an alert as read."""

        async def run() -> object:
            async with ControlRepository(database) as control:
                return (await control.mark_alert_read(alert_id)).model_dump(mode="json")

        typer.echo(_json(asyncio.run(run())))

    @app.command("landed-cost")
    def landed_cost_command(
        unit_price: Annotated[Decimal, typer.Argument(help="Product unit price")],
        quantity: Annotated[Decimal, typer.Argument(help="Target quantity")],
        currency: Annotated[str, typer.Option("--currency")] = "USD",
        shipping: Annotated[Decimal, typer.Option("--shipping", min=0)] = Decimal("0"),
        insurance: Annotated[Decimal, typer.Option("--insurance", min=0)] = Decimal("0"),
        duty_rate_pct: Annotated[
            Decimal,
            typer.Option("--duty-pct", min=0, max=100),
        ] = Decimal("0"),
        tax_rate_pct: Annotated[
            Decimal,
            typer.Option("--tax-pct", min=0, max=100),
        ] = Decimal("0"),
        brokerage: Annotated[Decimal, typer.Option("--brokerage", min=0)] = Decimal("0"),
        packaging_per_unit: Annotated[
            Decimal,
            typer.Option("--packaging-per-unit", min=0),
        ] = Decimal("0"),
        other_fees: Annotated[
            Decimal,
            typer.Option("--other-fees", min=0),
        ] = Decimal("0"),
        target_sale_price: Annotated[
            Decimal | None,
            typer.Option("--target-sale-price", min=0),
        ] = None,
    ) -> None:
        """Estimate landed total/unit cost from caller-provided rates and fees."""
        values = LandedCostInput(
            currency=currency,
            unit_price=unit_price,
            quantity=quantity,
            shipping=shipping,
            insurance=insurance,
            duty_rate_pct=duty_rate_pct,
            tax_rate_pct=tax_rate_pct,
            brokerage=brokerage,
            packaging_per_unit=packaging_per_unit,
            other_fees=other_fees,
            target_sale_price=target_sale_price,
        )
        typer.echo(_json(calculate_landed_cost(values)))
