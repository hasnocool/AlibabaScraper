# src/alibaba_scraper/resilience_cli.py
"""Operational-resilience CLI commands for v0.6."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from .config import Settings
from .database_maintenance import backup_database, integrity_check, restore_database
from .production import ProductionRepository
from .proxy import render_caddyfile, render_nginx_config, write_proxy_config
from .resilience import ResilienceRepository


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def register_resilience_commands(app: typer.Typer) -> None:
    @app.command("queue-errors")
    def queue_errors_command(
        job_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        contains: Annotated[str | None, typer.Option("--contains")] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=5000)] = 100,
    ) -> None:
        async def run() -> list[dict[str, object]]:
            async with ResilienceRepository(database) as resilience:
                return await resilience.list_failed_queue(
                    job_id, error_contains=contains, limit=limit
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("queue-retry")
    def queue_retry_command(
        job_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        queue_ids: Annotated[str, typer.Option("--queue-ids")] = "",
        contains: Annotated[str | None, typer.Option("--contains")] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=5000)] = 100,
        reset_attempts: Annotated[bool, typer.Option("--reset-attempts")] = False,
    ) -> None:
        ids = [int(value.strip()) for value in queue_ids.split(",") if value.strip()]

        async def run() -> dict[str, object]:
            async with ResilienceRepository(database) as resilience:
                return await resilience.retry_failed_queue(
                    job_id,
                    queue_ids=ids or None,
                    error_contains=contains,
                    limit=limit,
                    reset_attempts=reset_attempts,
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("api-key-rotate")
    def api_key_rotate_command(
        key_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        name: Annotated[str | None, typer.Option("--name")] = None,
        grace_minutes: Annotated[
            int, typer.Option("--grace-minutes", min=0, max=10080)
        ] = 15,
    ) -> None:
        async def run() -> object:
            async with ProductionRepository(database) as production:
                return await production.rotate_api_key(
                    key_id, name=name, grace_minutes=grace_minutes
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("token-mint")
    def token_mint_command(
        parent_key_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        ttl_minutes: Annotated[int, typer.Option("--ttl-minutes", min=1, max=1440)] = 60,
        scopes: Annotated[str, typer.Option("--scopes")] = "",
        name: Annotated[str | None, typer.Option("--name")] = None,
    ) -> None:
        requested = [scope.strip() for scope in scopes.split(",") if scope.strip()]

        async def run() -> object:
            async with ProductionRepository(database) as production:
                return await production.mint_short_lived_token(
                    parent_key_id,
                    ttl_minutes=ttl_minutes,
                    scopes=requested or None,  # type: ignore[arg-type]
                    name=name,
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("db-integrity")
    def db_integrity_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        typer.echo(_json(asyncio.run(integrity_check(database))))

    @app.command("db-backup")
    def db_backup_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    ) -> None:
        result = asyncio.run(backup_database(database, output))
        typer.echo(_json(result.__dict__))

    @app.command("db-restore")
    def db_restore_command(
        backup: Annotated[Path, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive restore")] = False,
        safety_backup: Annotated[
            bool, typer.Option("--safety-backup/--no-safety-backup")
        ] = True,
    ) -> None:
        if not yes:
            raise typer.BadParameter("db-restore requires --yes after stopping the service")
        result = asyncio.run(
            restore_database(backup, database, create_safety_backup=safety_backup)
        )
        typer.echo(_json(result.__dict__))

    @app.command("alert-sink-policy")
    def alert_sink_policy_command(
        sink_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        max_attempts: Annotated[int, typer.Option("--max-attempts", min=1, max=100)] = 5,
        base_backoff_seconds: Annotated[
            float, typer.Option("--base-backoff-seconds", min=1)
        ] = 30.0,
        max_backoff_seconds: Annotated[
            float, typer.Option("--max-backoff-seconds", min=1)
        ] = 3600.0,
    ) -> None:
        async def run() -> object:
            async with ProductionRepository(database) as production:
                return await production.update_alert_sink_policy(
                    sink_id,
                    max_attempts=max_attempts,
                    base_backoff_seconds=base_backoff_seconds,
                    max_backoff_seconds=max_backoff_seconds,
                )

        typer.echo(_json(asyncio.run(run())))

    @app.command("alert-dead-letters")
    def alert_dead_letters_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        async def run() -> list[dict[str, object]]:
            async with ProductionRepository(database) as production:
                return await production.list_dead_letters(limit)

        typer.echo(_json(asyncio.run(run())))

    @app.command("alert-dead-retry")
    def alert_dead_retry_command(
        delivery_id: Annotated[int, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        reset_attempts: Annotated[
            bool, typer.Option("--reset-attempts/--keep-attempts")
        ] = True,
    ) -> None:
        async def run() -> dict[str, object]:
            async with ProductionRepository(database) as production:
                await production.retry_dead_letter(
                    delivery_id, reset_attempts=reset_attempts
                )
            return {"delivery_id": delivery_id, "status": "retry_scheduled"}

        typer.echo(_json(asyncio.run(run())))

    @app.command("supplier-quality-snapshot")
    def supplier_quality_snapshot_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
    ) -> None:
        async def run() -> dict[str, object]:
            async with ResilienceRepository(database) as resilience:
                rows = await resilience.snapshot_supplier_quality()
                return {"snapshots": len(rows), "suppliers": rows}

        typer.echo(_json(asyncio.run(run())))

    @app.command("supplier-quality")
    def supplier_quality_command(
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        async def run() -> list[dict[str, object]]:
            async with ResilienceRepository(database) as resilience:
                return await resilience.list_supplier_quality(limit)

        typer.echo(_json(asyncio.run(run())))

    @app.command("supplier-quality-history")
    def supplier_quality_history_command(
        supplier_key: Annotated[str, typer.Argument()],
        database: Annotated[Path, typer.Option("--database", "-d")] = Path(
            "data/alibaba.sqlite3"
        ),
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    ) -> None:
        async def run() -> list[dict[str, object]]:
            async with ResilienceRepository(database) as resilience:
                return await resilience.supplier_quality_history(supplier_key, limit)

        typer.echo(_json(asyncio.run(run())))

    @app.command("log-status")
    def log_status_command() -> None:
        settings = Settings()
        if settings.log_path is None:
            typer.echo(_json({"enabled": False}))
            return
        path = settings.log_path
        files = sorted(path.parent.glob(path.name + "*")) if path.parent.exists() else []
        typer.echo(
            _json(
                {
                    "enabled": True,
                    "path": str(path),
                    "max_bytes": settings.log_max_bytes,
                    "backup_count": settings.log_backup_count,
                    "files": [
                        {"path": str(item), "bytes": item.stat().st_size} for item in files
                    ],
                }
            )
        )

    @app.command("proxy-render")
    def proxy_render_command(
        kind: Annotated[str, typer.Argument(help="caddy or nginx")],
        domain: Annotated[str, typer.Argument()],
        output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
        upstream: Annotated[str, typer.Option("--upstream")] = "127.0.0.1:8787",
        email: Annotated[str | None, typer.Option("--email")] = None,
        cert_file: Annotated[Path | None, typer.Option("--cert-file")] = None,
        key_file: Annotated[Path | None, typer.Option("--key-file")] = None,
    ) -> None:
        normalized = kind.strip().lower()
        if normalized == "caddy":
            content = render_caddyfile(domain, upstream, email)
        elif normalized == "nginx":
            if cert_file is None or key_file is None:
                raise typer.BadParameter("nginx requires --cert-file and --key-file")
            content = render_nginx_config(domain, cert_file, key_file, upstream)
        else:
            raise typer.BadParameter("kind must be caddy or nginx")
        if output is None:
            typer.echo(content)
            return
        target = write_proxy_config(output, content)
        typer.echo(str(target))
