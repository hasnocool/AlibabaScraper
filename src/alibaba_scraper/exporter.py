# src/alibaba_scraper/exporter.py
"""Non-blocking CSV and JSONL exports from persisted product data."""

import asyncio
import csv
import json
from pathlib import Path
from typing import Any, Literal

from .database import Database
from .models import ProductRecord

ExportFormat = Literal["csv", "jsonl"]


async def export_products(
    database: Database,
    output: Path,
    *,
    format: ExportFormat,
) -> int:
    """Export current product snapshots without blocking the event loop on file I/O."""
    rows = await _load_rows(database)
    if format == "csv":
        await asyncio.to_thread(_write_csv, output, rows)
    elif format == "jsonl":
        await asyncio.to_thread(_write_jsonl, output, rows)
    else:  # pragma: no cover - guarded by CLI and type hints
        raise ValueError(f"unsupported export format: {format}")
    return len(rows)


async def _load_rows(database: Database) -> list[dict[str, Any]]:
    cursor = await database.connection.execute(
        """
        SELECT p.product_key, p.record_json,
               s.score, s.price_value, s.moq_score, s.supplier_confidence,
               s.tier_discount, s.data_quality, s.peer_median_price,
               s.reasons_json, s.scored_at
          FROM products p
          LEFT JOIN product_scores s ON s.product_key = p.product_key
         ORDER BY p.last_seen_at DESC, p.product_key
        """
    )
    output: list[dict[str, Any]] = []
    for row in await cursor.fetchall():
        record = ProductRecord.model_validate_json(row["record_json"])
        payload = record.model_dump(mode="json")
        payload["product_key"] = row["product_key"]
        payload["sourcing_score"] = row["score"]
        payload["score_components"] = (
            {
                "price_value": row["price_value"],
                "moq": row["moq_score"],
                "supplier_confidence": row["supplier_confidence"],
                "tier_discount": row["tier_discount"],
                "data_quality": row["data_quality"],
                "peer_median_price": row["peer_median_price"],
                "reasons": json.loads(row["reasons_json"]),
                "scored_at": row["scored_at"],
            }
            if row["score"] is not None
            else None
        )
        output.append(payload)
    return output


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "product_key",
        "product_id",
        "title",
        "supplier_name",
        "supplier_country",
        "category",
        "price_min",
        "price_max",
        "currency",
        "moq",
        "moq_unit",
        "sourcing_score",
        "source_url",
        "canonical_url",
        "scraped_at",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            price = row.get("price") or {}
            writer.writerow(
                {
                    "product_key": row.get("product_key"),
                    "product_id": row.get("product_id"),
                    "title": row.get("title"),
                    "supplier_name": row.get("supplier_name"),
                    "supplier_country": row.get("supplier_country"),
                    "category": row.get("category"),
                    "price_min": price.get("minimum"),
                    "price_max": price.get("maximum"),
                    "currency": price.get("currency"),
                    "moq": row.get("minimum_order_quantity"),
                    "moq_unit": row.get("minimum_order_unit"),
                    "sourcing_score": row.get("sourcing_score"),
                    "source_url": row.get("source_url"),
                    "canonical_url": row.get("canonical_url"),
                    "scraped_at": row.get("scraped_at"),
                }
            )
