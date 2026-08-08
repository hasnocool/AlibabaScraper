# src/alibaba_scraper/cli.py
"""Command-line interface."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from .config import Settings
from .database import Database
from .pipeline import CrawlPipeline
from .scraper import AlibabaScraper
from .storage import write_json

app = typer.Typer(no_args_is_help=True, help="Collect public Alibaba product data.")


async def _fetch(url: str, output: Path | None) -> None:
    async with AlibabaScraper() as scraper:
        record = await scraper.fetch_product(url)

    if output is not None:
        await write_json(output, record)
        typer.echo(str(output))
        return
    typer.echo(json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False))


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
    typer.echo(json.dumps([job.model_dump(mode="json") for job in jobs], indent=2))


async def _history(product_id: str, database: Path) -> None:
    async with Database(database) as db:
        history = await db.product_history(product_id)
    typer.echo(json.dumps(history, indent=2))


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
    """Discover product URLs and collect them into resumable SQLite storage."""
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


if __name__ == "__main__":
    app()
