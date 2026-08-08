# src/alibaba_scraper/dashboard.py
"""Shared dashboard snapshot and terminal rendering helpers."""

import asyncio
from pathlib import Path

from .control import ControlRepository
from .database import Database
from .intelligence import IntelligenceRepository


async def dashboard_snapshot(database_path: Path | str) -> dict[str, object]:
    """Load one compact snapshot used by the CLI dashboard."""
    async with (
        Database(database_path) as database,
        IntelligenceRepository(database_path) as intelligence,
        ControlRepository(database_path) as control,
    ):
        summary = await control.dashboard_summary()
        products = await control.list_products(limit=8)
        suppliers = await intelligence.list_suppliers(6)
        jobs = await database.list_jobs(6)
        watchlists = await intelligence.list_watchlists(6)
        alerts = await control.list_alerts(unread_only=True, limit=6)
    return {
        "summary": summary,
        "products": products,
        "suppliers": [item.model_dump(mode="json") for item in suppliers],
        "jobs": [item.model_dump(mode="json") for item in jobs],
        "watchlists": [item.model_dump(mode="json") for item in watchlists],
        "alerts": [item.model_dump(mode="json") for item in alerts],
    }


def render_terminal_dashboard(snapshot: dict[str, object]) -> str:
    """Render a monospaced, dependency-free CLI dashboard."""
    summary = snapshot["summary"]
    assert isinstance(summary, dict)
    profile = summary.get("active_profile") or {}
    profile_name = profile.get("name", "Default") if isinstance(profile, dict) else "Default"
    lines = [
        "ALIBABA SCRAPER — OPERATIONS DASHBOARD",
        "=" * 76,
        (
            f"Products {summary.get('products', 0):>6} | "
            f"Suppliers {summary.get('suppliers', 0):>6} | "
            f"Watchlists {summary.get('watchlists', 0):>4} | "
            f"Running {summary.get('running_jobs', 0):>3}"
        ),
        (
            f"Unread alerts {summary.get('unread_alerts', 0):>4} | Changes/24h "
            f"{summary.get('changes_24h', 0):>5} | Top score {str(summary.get('top_score')):>6} | "
            f"Profile {profile_name}"
        ),
        "",
        "TOP PRODUCTS",
        "-" * 76,
    ]
    products = snapshot.get("products", [])
    if isinstance(products, list):
        for row in products[:8]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "(untitled)")[:40]
            score = row.get("score")
            price = row.get("price_min")
            currency = row.get("currency") or ""
            lines.append(f"{str(score or '-'):>6}  {str(price or '-'):>10} {currency:<4}  {title}")
    lines.extend(["", "RECENT JOBS", "-" * 76])
    jobs = snapshot.get("jobs", [])
    if isinstance(jobs, list):
        for row in jobs[:6]:
            if isinstance(row, dict):
                lines.append(
                    f"#{row.get('id', '-'):>4}  {str(row.get('status', '-')):<22}  "
                    f"{str(row.get('query', ''))[:42]}"
                )
    lines.extend(["", "UNREAD ALERTS", "-" * 76])
    alerts = snapshot.get("alerts", [])
    if isinstance(alerts, list) and alerts:
        for row in alerts[:6]:
            if isinstance(row, dict):
                lines.append(f"[{row.get('severity', 'info')}] {row.get('title', '')}")
    else:
        lines.append("No unread alerts.")
    return "\n".join(lines)


async def watch_terminal_dashboard(database_path: Path | str, refresh_seconds: float) -> None:
    """Refresh the terminal dashboard without blocking the event loop."""
    if refresh_seconds < 1:
        raise ValueError("refresh_seconds must be >= 1")
    while True:
        snapshot = await dashboard_snapshot(database_path)
        print("\033[2J\033[H", end="")
        print(render_terminal_dashboard(snapshot), flush=True)
        await asyncio.sleep(refresh_seconds)
