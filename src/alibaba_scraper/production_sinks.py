# src/alibaba_scraper/production_sinks.py
"""External alert-sink and delivery bookkeeping methods."""

import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from .production_models import AlertSink, AlertSinkInput


class AlertSinkMixin:
    async def create_alert_sink(self, values: AlertSinkInput) -> AlertSink:
        now = _now()
        async with self._write_lock:
            cursor = await self.connection.execute(
                """
                INSERT INTO alert_sinks(
                    name,kind,endpoint,secret,headers_json,event_kinds_json,
                    minimum_severity,enabled,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    values.name.strip(),
                    values.kind,
                    values.endpoint,
                    values.secret,
                    json.dumps(values.headers),
                    json.dumps(values.event_kinds),
                    values.minimum_severity,
                    int(values.enabled),
                    now,
                    now,
                ),
            )
            await self.connection.commit()
        return await self.get_alert_sink(int(cursor.lastrowid))

    async def get_alert_sink(self, sink_id: int) -> AlertSink:
        row = await (
            await self.connection.execute("SELECT * FROM alert_sinks WHERE id=?", (sink_id,))
        ).fetchone()
        if row is None:
            raise KeyError(f"alert sink {sink_id} does not exist")
        return _sink(row)

    async def list_alert_sinks(self) -> list[AlertSink]:
        rows = await (
            await self.connection.execute("SELECT * FROM alert_sinks ORDER BY id DESC")
        ).fetchall()
        return [_sink(row) for row in rows]

    async def delete_alert_sink(self, sink_id: int) -> None:
        await self.get_alert_sink(sink_id)
        async with self._write_lock:
            await self.connection.execute("DELETE FROM alert_sinks WHERE id=?", (sink_id,))
            await self.connection.commit()

    async def pending_deliveries(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                """
                SELECT a.id AS alert_id,a.kind,a.severity,a.title,a.message,a.payload_json,
                       a.created_at,s.id AS sink_id,s.name AS sink_name,s.kind AS sink_kind,
                       s.endpoint,s.secret,s.headers_json,s.event_kinds_json,s.minimum_severity
                FROM alerts a CROSS JOIN alert_sinks s
                LEFT JOIN alert_deliveries d ON d.alert_id=a.id AND d.sink_id=s.id
                WHERE s.enabled=1 AND (d.id IS NULL OR d.status='failed')
                ORDER BY a.id,s.id LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def record_delivery(
        self, alert_id: int, sink_id: int, *, success: bool, error: str | None = None
    ) -> None:
        now = _now()
        async with self._write_lock:
            await self.connection.execute(
                """
                INSERT INTO alert_deliveries(
                    alert_id,sink_id,status,attempts,last_error,last_attempt_at,delivered_at
                ) VALUES(?,?,?,1,?,?,?)
                ON CONFLICT(alert_id,sink_id) DO UPDATE SET
                    status=excluded.status,attempts=alert_deliveries.attempts+1,
                    last_error=excluded.last_error,last_attempt_at=excluded.last_attempt_at,
                    delivered_at=excluded.delivered_at
                """,
                (
                    alert_id,
                    sink_id,
                    "delivered" if success else "failed",
                    error[:1000] if error else None,
                    now,
                    now if success else None,
                ),
            )
            await self.connection.commit()

    async def delivery_summary(self) -> dict[str, int]:
        rows = await (
            await self.connection.execute(
                "SELECT status,COUNT(*) AS count FROM alert_deliveries GROUP BY status"
            )
        ).fetchall()
        values = {row["status"]: int(row["count"]) for row in rows}
        return {"delivered": values.get("delivered", 0), "failed": values.get("failed", 0)}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sink(row: aiosqlite.Row) -> AlertSink:
    return AlertSink(
        id=int(row["id"]),
        name=row["name"],
        kind=row["kind"],
        endpoint=row["endpoint"],
        has_secret=bool(row["secret"]),
        headers=json.loads(row["headers_json"] or "{}"),
        event_kinds=json.loads(row["event_kinds_json"] or "[]"),
        minimum_severity=row["minimum_severity"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
