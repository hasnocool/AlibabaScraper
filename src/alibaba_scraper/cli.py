# src/alibaba_scraper/cli.py
"""Command-line interface."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from .config import Settings
from .database import Database
from .exporter import export_products
from .intelligence import IntelligenceRepository
from .pipeline import CrawlPipeline
from .scraper import AlibabaScraper
from .storage import write_json
from .watchlists import WatchlistService

app = typer.Typer(no_args_is_help=True, help="Collect and analyze public Alibaba product data.")


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


async def _fetch(url: str, output: Path | None) -> None:
    async with AlibabaScraper() as scraper:
        record = await scraper.fetch_product(url)

    if output is not None:
        await write_json(output, record)
        typer.echo(str(output))
        return
    typer.echo(_json(record))


async def _crawl(query: str, database: Path, limit: int, pages: int) -> None:
    settings = Settings(database_path=database)
    async with Database(database) as db, AlibabaScraper(settings) as scraper:
        summary = await CrawlPipeline(scraper, db).start(
            query,
            max_products=limit,
            max_search_pages=pages,
        )
    typer.echo(summary.model_dump_json(indent=2))


async def _resume(job_id: int, database: Path) -> None:
    settings = Settings(database_path=database)
    async with Database(database) as db, AlibabaScraper(settings) as scraper:
        summary = await CrawlPipeline(scraper, db).resume(job_id)
    typer.echo(summary.model_dump_json(indent=2))


async def _jobs(database: Path, limit: int) -> None:
    async with Database(database) as db:
        jobs = await db.list_jobs(limit)
    typer.echo(_json([job.model_dump(mode="json") for job in jobs]))


async def _history(product_id: str, database: Path) -> None:
    async with Database(database) as db:
        history = await db.product_history(product_id)
    typer.echo(_json(history))


async def _export(database: Path, output: Path, format: str) -> None:
    async with IntelligenceRepository(database), Database(database) as db:
        count = await export_products(db, output, format=format)  # type: ignore[arg-type]
    typer.echo(_json({"format": format, "records": count, "output": str(output)}))


async def _suppliers(database: Path, limit: int) -> None:
    async with IntelligenceRepository(database) as intelligence:
        suppliers = await intelligence.list_suppliers(limit)
    typer.echo(_json([supplier.model_dump(mode="json") for supplier in suppliers]))


async def _supplier_products(database: Path, supplier_key: str, limit: int) -> None:
    async with IntelligenceRepository(database) as intelligence:
        rows = await intelligence.supplier_products(supplier_key, limit)
    typer.echo(_json(rows))


async def _changes(database: Path, job_id: int | None, limit: int) -> None:
    async with IntelligenceRepository(database) as intelligence:
        rows = await intelligence.list_changes(job_id=job_id, limit=limit)
    typer.echo(_json([row.model_dump(mode="json") for row in rows]))


async def _scores(database: Path, limit: int) -> None:
    async with IntelligenceRepository(database) as intelligence:
        rows = await intelligence.top_scores(limit)
    typer.echo(_json(rows))


async def _watch_add(
    database: Path,
    name: str,
    query: str,
    interval_minutes: int,
    limit: int,
    pages: int,
) -> None:
    async with IntelligenceRepository(database) as intelligence:
        watchlist_id = await intelligence.create_watchlist(
            name,
            query,
            interval_minutes=interval_minutes,
            max_products=limit,
            max_search_pages=pages,
        )
        watchlist = await intelligence.get_watchlist(watchlist_id)
    typer.echo(watchlist.model_dump_json(indent=2))


async def _watchlists(database: Path, limit: int) -> None:
    async with IntelligenceRepository(database) as intelligence:
        rows = await intelligence.list_watchlists(limit)
    typer.echo(_json([row.model_dump(mode="json") for row in rows]))


async def _watch_enable(database: Path, watchlist_id: int, enabled: bool) -> None:
    async with IntelligenceRepository(database) as intelligence:
        await intelligence.set_watchlist_enabled(watchlist_id, enabled)
        watchlist = await intelligence.get_watchlist(watchlist_id)
    typer.echo(watchlist.model_dump_json(indent=2))


async def _watch_run(database: Path, watchlist_id: int) -> None:
    settings = Settings(database_path=database)
    async with (
        Database(database) as db,
        IntelligenceRepository(database) as intelligence,
        AlibabaScraper(settings) as scraper,
    ):
        result = await WatchlistService(scraper, db, intelligence).run_watchlist(watchlist_id)
    typer.echo(result.model_dump_json(indent=2))


async def _watch_run_due(database: Path, limit: int) -> None:
    settings = Settings(database_path=database)
    async with (
        Database(database) as db,
        IntelligenceRepository(database) as intelligence,
        AlibabaScraper(settings) as scraper,
    ):
        rows = await WatchlistService(scraper, db, intelligence).run_due(limit)
    typer.echo(_json([row.model_dump(mode="json") for row in rows]))


async def _watch_daemon(database: Path, poll_seconds: float) -> None:
    settings = Settings(database_path=database)
    async with (
        Database(database) as db,
        IntelligenceRepository(database) as intelligence,
        AlibabaScraper(settings) as scraper,
    ):
        await WatchlistService(scraper, db, intelligence).daemon(poll_seconds=poll_seconds)


@app.command()
def fetch(
    url: Annotated[str, typer.Argument(help="Public Alibaba product URL")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON output path"),
    ] = None,
) -> None:
    """Fetch and normalize a single product page."""
    asyncio.run(_fetch(url, output))


@app.command()
def crawl(
    query: Annotated[str, typer.Argument(help="Alibaba product search query")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=5000)] = 50,
    pages: Annotated[int, typer.Option("--pages", min=1, max=100)] = 5,
) -> None:
    """Discover, collect, track changes, and score a product search."""
    asyncio.run(_crawl(query, database, limit, pages))


@app.command("resume")
def resume_command(
    job_id: Annotated[int, typer.Argument(help="Crawl job id")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
) -> None:
    """Resume an interrupted crawl job."""
    asyncio.run(_resume(job_id, database))


@app.command("jobs")
def jobs_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
) -> None:
    """List persisted crawl jobs."""
    asyncio.run(_jobs(database, limit))


@app.command()
def history(
    product_id: Annotated[str, typer.Argument(help="Alibaba product id or storage key")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
) -> None:
    """Show recorded price/MOQ history for a product."""
    asyncio.run(_history(product_id, database))


@app.command("export")
def export_command(
    output: Annotated[Path, typer.Argument(help="Destination .csv or .jsonl file")],
    format: Annotated[str, typer.Option("--format", "-f", help="csv or jsonl")] = "jsonl",
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
) -> None:
    """Export current product snapshots with sourcing scores."""
    normalized = format.lower()
    if normalized not in {"csv", "jsonl"}:
        raise typer.BadParameter("format must be csv or jsonl", param_hint="--format")
    asyncio.run(_export(database, output, normalized))


@app.command("suppliers")
def suppliers_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """List normalized suppliers ranked by observed product count."""
    asyncio.run(_suppliers(database, limit))


@app.command("supplier-products")
def supplier_products_command(
    supplier_key: Annotated[str, typer.Argument(help="Supplier storage key")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """List products linked to one normalized supplier."""
    asyncio.run(_supplier_products(database, supplier_key, limit))


@app.command("changes")
def changes_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    job_id: Annotated[int | None, typer.Option("--job-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=5000)] = 100,
) -> None:
    """Show normalized product-field changes."""
    asyncio.run(_changes(database, job_id, limit))


@app.command("scores")
def scores_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 50,
) -> None:
    """Show top sourcing/deal scores."""
    asyncio.run(_scores(database, limit))


@app.command("watch-add")
def watch_add_command(
    name: Annotated[str, typer.Argument(help="Unique watchlist name")],
    query: Annotated[str, typer.Argument(help="Alibaba search query")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    interval_minutes: Annotated[
        int,
        typer.Option("--every-minutes", min=1, help="Recrawl interval"),
    ] = 1440,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=5000)] = 50,
    pages: Annotated[int, typer.Option("--pages", min=1, max=100)] = 5,
) -> None:
    """Create a saved search that is immediately due for its first run."""
    asyncio.run(_watch_add(database, name, query, interval_minutes, limit, pages))


@app.command("watchlists")
def watchlists_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """List saved search watchlists."""
    asyncio.run(_watchlists(database, limit))


@app.command("watch-enable")
def watch_enable_command(
    watchlist_id: Annotated[int, typer.Argument(help="Watchlist id")],
    enabled: Annotated[
        bool,
        typer.Option("--enabled/--disabled", help="Enable or disable automatic recrawls"),
    ] = True,
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
) -> None:
    """Enable or disable a watchlist."""
    asyncio.run(_watch_enable(database, watchlist_id, enabled))


@app.command("watch-run")
def watch_run_command(
    watchlist_id: Annotated[int, typer.Argument(help="Watchlist id")],
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
) -> None:
    """Run one watchlist immediately."""
    asyncio.run(_watch_run(database, watchlist_id))


@app.command("watch-run-due")
def watch_run_due_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 25,
) -> None:
    """Run all currently due watchlists once."""
    asyncio.run(_watch_run_due(database, limit))


@app.command("watch-daemon")
def watch_daemon_command(
    database: Annotated[
        Path,
        typer.Option("--database", "-d", help="SQLite database path"),
    ] = Path("data/alibaba.sqlite3"),
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=1.0, help="How often to check due watchlists"),
    ] = 60.0,
) -> None:
    """Continuously recrawl due watchlists until interrupted."""
    try:
        asyncio.run(_watch_daemon(database, poll_seconds))
    except KeyboardInterrupt:
        typer.echo("watch daemon stopped")


if __name__ == "__main__":
    app()
