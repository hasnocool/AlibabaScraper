# src/alibaba_scraper/production_sinks.py
"""External alert-sink delivery bookkeeping with backoff and dead letters."""

import json
from datetime import UTC, datetime, timedelta
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
                    minimum_severity,enabled,created_at,updated_at,
                    max_attempts,base_backoff_seconds,max_backoff_seconds
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    values.max_attempts,
                    values.base_backoff_seconds,
                    values.max_backoff_seconds,
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

    async def update_alert_sink_policy(
        self,
        sink_id: int,
        *,
        max_attempts: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
    ) -> AlertSink:
        await self.get_alert_sink(sink_id)
        if max_attempts < 1 or max_attempts > 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if base_backoff_seconds < 1 or max_backoff_seconds < base_backoff_seconds:
            raise ValueError("backoff values are invalid")
        async with self._write_lock:
            await self.connection.execute(
                """
                UPDATE alert_sinks
                SET max_attempts=?,base_backoff_seconds=?,max_backoff_seconds=?,updated_at=?
                WHERE id=?
                """,
                (
                    max_attempts,
                    base_backoff_seconds,
                    max_backoff_seconds,
                    _now(),
                    sink_id,
                ),
            )
            await self.connection.commit()
        return await self.get_alert_sink(sink_id)

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
                       s.endpoint,s.secret,s.headers_json,s.event_kinds_json,s.minimum_severity,
                       s.max_attempts,s.base_backoff_seconds,s.max_backoff_seconds,
                       d.attempts,d.next_attempt_at,d.dead_lettered_at
                FROM alerts a CROSS JOIN alert_sinks s
                LEFT JOIN alert_deliveries d ON d.alert_id=a.id AND d.sink_id=s.id
                WHERE s.enabled=1
                  AND (
                    d.id IS NULL OR (
                      d.status='failed'
                      AND d.dead_lettered_at IS NULL
                      AND (
                        d.next_attempt_at IS NULL
                        OR datetime(d.next_attempt_at)<=datetime('now')
                      )
                    )
                  )
                ORDER BY a.id,s.id LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def record_delivery(
        self,
        alert_id: int,
        sink_id: int,
        *,
        success: bool,
        error: str | None = None,
    ) -> str:
        """Record delivery atomically and return delivered, failed, or dead_letter."""
        now = datetime.now(UTC)
        async with self._write_lock:
            existing = await (
                await self.connection.execute(
                    "SELECT attempts FROM alert_deliveries WHERE alert_id=? AND sink_id=?",
                    (alert_id, sink_id),
                )
            ).fetchone()
            sink = await (
                await self.connection.execute(
                    """
                    SELECT max_attempts,base_backoff_seconds,max_backoff_seconds
                    FROM alert_sinks WHERE id=?
                    """,
                    (sink_id,),
                )
            ).fetchone()
            if sink is None:
                raise KeyError(f"alert sink {sink_id} does not exist")
            attempts = int(existing["attempts"] or 0) + 1 if existing else 1
            status = "delivered" if success else "failed"
            next_attempt_at: str | None = None
            dead_lettered_at: str | None = None
            if not success:
                if attempts >= int(sink["max_attempts"]):
                    status = "dead_letter"
                    dead_lettered_at = now.isoformat()
                else:
                    base = float(sink["base_backoff_seconds"])
                    maximum = float(sink["max_backoff_seconds"])
                    delay = min(maximum, base * (2 ** max(0, attempts - 1)))
                    next_attempt_at = (now + timedelta(seconds=delay)).isoformat()
            await self.connection.execute(
                """
                INSERT INTO alert_deliveries(
                    alert_id,sink_id,status,attempts,last_error,last_attempt_at,delivered_at,
                    next_attempt_at,dead_lettered_at
                ) VALUES(?,?,?,1,?,?,?,?,?)
                ON CONFLICT(alert_id,sink_id) DO UPDATE SET
                    status=excluded.status,attempts=alert_deliveries.attempts+1,
                    last_error=excluded.last_error,last_attempt_at=excluded.last_attempt_at,
                    delivered_at=excluded.delivered_at,next_attempt_at=excluded.next_attempt_at,
                    dead_lettered_at=excluded.dead_lettered_at
                """,
                (
                    alert_id,
                    sink_id,
                    status,
                    error[:1000] if error else None,
                    now.isoformat(),
                    now.isoformat() if success else None,
                    next_attempt_at,
                    dead_lettered_at,
                ),
            )
            await self.connection.commit()
        return status

    async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                """
                SELECT d.*,a.kind,a.severity,a.title,s.name AS sink_name,s.endpoint
                FROM alert_deliveries d
                JOIN alerts a ON a.id=d.alert_id
                JOIN alert_sinks s ON s.id=d.sink_id
                WHERE d.status='dead_letter'
                ORDER BY d.id DESC LIMIT ?
                """,
                (limit,),
            )
        ).fetchall()
        return [dict(row) for row in rows]

    async def retry_dead_letter(self, delivery_id: int, *, reset_attempts: bool = True) -> None:
        row = await (
            await self.connection.execute(
                "SELECT id FROM alert_deliveries WHERE id=? AND status='dead_letter'",
                (delivery_id,),
            )
        ).fetchone()
        if row is None:
            raise KeyError(f"dead-letter delivery {delivery_id} does not exist")
        attempts_sql = "attempts=0," if reset_attempts else ""
        async with self._write_lock:
            await self.connection.execute(
                f"""
                UPDATE alert_deliveries SET {attempts_sql}
                    status='failed',next_attempt_at=?,dead_lettered_at=NULL,last_error=NULL
                WHERE id=?
                """,
                (_now(), delivery_id),
            )
            await self.connection.commit()

    async def delivery_summary(self) -> dict[str, int]:
        rows = await (
            await self.connection.execute(
                "SELECT status,COUNT(*) AS count FROM alert_deliveries GROUP BY status"
            )
        ).fetchall()
        values = {row["status"]: int(row["count"]) for row in rows}
        return {
            "delivered": values.get("delivered", 0),
            "failed": values.get("failed", 0),
            "dead_letter": values.get("dead_letter", 0),
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sink(row: aiosqlite.Row) -> AlertSink:
    keys = set(row.keys())
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
        max_attempts=int(row["max_attempts"]) if "max_attempts" in keys else 5,
        base_backoff_seconds=(
            float(row["base_backoff_seconds"]) if "base_backoff_seconds" in keys else 30.0
        ),
        max_backoff_seconds=(
            float(row["max_backoff_seconds"]) if "max_backoff_seconds" in keys else 3600.0
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
