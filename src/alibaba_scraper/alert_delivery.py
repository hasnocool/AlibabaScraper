# src/alibaba_scraper/alert_delivery.py
"""Configurable external alert delivery with webhook retry bookkeeping."""

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from .production import ProductionRepository

_SEVERITY = {"info": 0, "warning": 1, "error": 2}


async def deliver_pending_alerts(
    production: ProductionRepository,
    *,
    limit: int = 100,
    timeout_seconds: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Deliver pending alerts to configured webhook sinks."""
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_seconds)
    delivered = failed = skipped = 0
    try:
        for row in await production.pending_deliveries(limit):
            kinds = json.loads(row["event_kinds_json"] or "[]")
            if kinds and row["kind"] not in kinds:
                skipped += 1
                await production.record_delivery(
                    row["alert_id"], row["sink_id"], success=True
                )
                continue
            if _SEVERITY.get(row["severity"], 0) < _SEVERITY.get(row["minimum_severity"], 0):
                skipped += 1
                await production.record_delivery(
                    row["alert_id"], row["sink_id"], success=True
                )
                continue
            payload: dict[str, Any] = {
                "id": row["alert_id"],
                "kind": row["kind"],
                "severity": row["severity"],
                "title": row["title"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"] or "{}"),
                "created_at": row["created_at"],
            }
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            headers = {
                "Content-Type": "application/json",
                **json.loads(row["headers_json"] or "{}"),
            }
            if row["secret"]:
                signature = hmac.new(
                    str(row["secret"]).encode(), body, hashlib.sha256
                ).hexdigest()
                headers["X-AlibabaScraper-Signature"] = f"sha256={signature}"
            try:
                response = await client.post(row["endpoint"], content=body, headers=headers)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - persisted for operator review
                failed += 1
                await production.record_delivery(
                    row["alert_id"],
                    row["sink_id"],
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            else:
                delivered += 1
                await production.record_delivery(
                    row["alert_id"], row["sink_id"], success=True
                )
    finally:
        if owned:
            await client.aclose()
    return {"delivered": delivered, "failed": failed, "skipped": skipped}


class AlertDispatcher:
    """Periodic non-blocking alert-delivery loop for the long-running service."""

    def __init__(
        self,
        production: ProductionRepository,
        *,
        interval_seconds: float = 10.0,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.production = production
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="alert-dispatcher")

    async def stop(self) -> None:
        if self.task is None:
            return
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    async def _run(self) -> None:
        while True:
            await deliver_pending_alerts(
                self.production, timeout_seconds=self.timeout_seconds
            )
            await asyncio.sleep(self.interval_seconds)
