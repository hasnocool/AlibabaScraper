# src/alibaba_scraper/cli.py
"""Command-line interface."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

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


@app.command()
def fetch(
    url: Annotated[str, typer.Argument(help="Public Alibaba product URL")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional JSON output path"),
    ] = None,
) -> None:
    """Fetch a single product page."""
    asyncio.run(_fetch(url, output))


if __name__ == "__main__":
    app()
