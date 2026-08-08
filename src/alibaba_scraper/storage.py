# src/alibaba_scraper/storage.py
"""Non-blocking persistence helpers."""

import asyncio
import json
from pathlib import Path

from .models import ProductRecord


def _write_json_sync(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


async def write_json(path: Path, record: ProductRecord) -> None:
    """Write one record without blocking the asyncio event loop."""
    payload = json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False)
    await asyncio.to_thread(_write_json_sync, path, payload)
