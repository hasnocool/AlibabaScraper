# src/alibaba_scraper/telemetry.py
"""Low-overhead in-process request and service telemetry."""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TelemetryRegistry:
    """Bounded aggregate metrics suitable for health pages and Prometheus scraping."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    requests_total: int = 0
    request_errors_total: int = 0
    latency_seconds_total: float = 0.0
    latency_seconds_max: float = 0.0
    by_route: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def observe(self, method: str, path: str, status_code: int, elapsed: float) -> None:
        route_key = f"{method} {path}"
        async with self._lock:
            self.requests_total += 1
            if status_code >= 500:
                self.request_errors_total += 1
            self.latency_seconds_total += elapsed
            self.latency_seconds_max = max(self.latency_seconds_max, elapsed)
            if len(self.by_route) < 100 or route_key in self.by_route:
                self.by_route[route_key] += 1

    def snapshot(self) -> dict[str, Any]:
        uptime = max(0.0, (datetime.now(UTC) - self.started_at).total_seconds())
        average = self.latency_seconds_total / self.requests_total if self.requests_total else 0.0
        return {
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": round(uptime, 3),
            "requests_total": self.requests_total,
            "request_errors_total": self.request_errors_total,
            "request_latency_seconds_avg": round(average, 6),
            "request_latency_seconds_max": round(self.latency_seconds_max, 6),
            "routes": dict(
                sorted(self.by_route.items(), key=lambda item: item[1], reverse=True)[:25]
            ),
        }

    def prometheus(self, extra: dict[str, int | float] | None = None) -> str:
        snapshot = self.snapshot()
        lines = [
            "# TYPE alibaba_scraper_requests_total counter",
            f"alibaba_scraper_requests_total {snapshot['requests_total']}",
            "# TYPE alibaba_scraper_request_errors_total counter",
            f"alibaba_scraper_request_errors_total {snapshot['request_errors_total']}",
            "# TYPE alibaba_scraper_request_latency_seconds_avg gauge",
            (
                "alibaba_scraper_request_latency_seconds_avg "
                f"{snapshot['request_latency_seconds_avg']}"
            ),
            "# TYPE alibaba_scraper_request_latency_seconds_max gauge",
            (
                "alibaba_scraper_request_latency_seconds_max "
                f"{snapshot['request_latency_seconds_max']}"
            ),
            "# TYPE alibaba_scraper_uptime_seconds gauge",
            f"alibaba_scraper_uptime_seconds {snapshot['uptime_seconds']}",
        ]
        for key, value in (extra or {}).items():
            safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key)
            lines.extend(
                (f"# TYPE alibaba_scraper_{safe} gauge", f"alibaba_scraper_{safe} {value}")
            )
        return "\n".join(lines) + "\n"


class RequestTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.started
