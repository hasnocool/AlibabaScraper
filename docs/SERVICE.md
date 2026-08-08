# Service and Dashboard Architecture

## Purpose

v0.5 turns the v0.4 control plane into an authenticated production-style local service while keeping crawler, intelligence, and control repositories separate.

## Process model

```text
FastAPI / Uvicorn
  |
  +-- Database ---------------- core product/crawl state
  +-- IntelligenceRepository -- suppliers, changes, watchlists, baseline scores
  +-- ControlRepository ------- profile scores, alerts, dashboard read models
  +-- ProductionRepository ---- API keys, migrations, scenarios, bindings, sinks
  +-- AlibabaScraper ---------- bounded async public-page collection
  +-- RuntimeManager ---------- live crawl/watchlist tasks
  +-- watchlist scheduler ----- automatically runs due saved searches
  +-- alert dispatcher -------- delivers persisted alerts to configured sinks
  +-- TelemetryRegistry ------- request/error/latency/uptime aggregates
```

The service opens each repository once for its lifespan. SQLite writes remain separated by repository-specific coroutine locks and WAL mode.

## Live task behavior

Starting a crawl through the API:

1. creates a durable crawl job in SQLite;
2. schedules an asyncio task;
3. returns immediately with the runtime task key;
4. updates durable crawl/queue state as collection progresses;
5. computes active-profile and category-profile scores after completion;
6. creates a high-score alert when candidates exceed the configured threshold.

Cancellation cancels the asyncio task, marks the durable crawl `cancelled`, and returns any `in_progress` queue rows to `pending`. The job can therefore be resumed later.

## Authentication

Authentication is enabled by default. API keys are created locally with the CLI:

```bash
alibaba-scraper api-key-create admin --scopes admin
```

The plaintext key is returned only at creation time. SQLite stores the key prefix and SHA-256 digest, plus scopes, expiry, revocation, and last-used timestamps.

Use the key as:

```text
X-API-Key: abs_...
```

Scopes are hierarchical:

- `read` — GET/HEAD API operations;
- `write` — write operations and read operations;
- `admin` — API-key and alert-sink administration plus all other operations.

The production browser dashboard can exchange the header key for an HttpOnly same-site session cookie. The classic dashboard then works through the same authenticated cookie.

`GET /api/health/live` remains unauthenticated for process liveness checks. Detailed health, readiness, metrics, and all control/data API routes require a key when auth is enabled.

## Migrations

`migrations.py` owns ordered transactional migrations in `schema_migrations`. The service applies missing migrations before opening long-lived repositories.

Operators can also run:

```bash
alibaba-scraper migrate
```

The command is idempotent and reports the applied/current schema version.

## Scheduled work

The long-running service now owns two background loops:

1. the watchlist scheduler checks due saved searches and runs them with non-blocking sleeps;
2. the alert dispatcher sends newly persisted alerts to configured external sinks.

This means the normal systemd deployment uses one `alibaba-service` process. A separate `watch-daemon` is not required when the service scheduler is enabled.

## Health and telemetry

Routes:

- `GET /api/health/live` — unauthenticated liveness;
- `GET /api/health` — schema, active profile, runtime, alert delivery, request telemetry;
- `GET /api/health/ready` — database/schema readiness;
- `GET /metrics` — Prometheus-style counters and gauges.

Telemetry is intentionally aggregate and bounded. It records request counts, server-error counts, average/max latency, uptime, and a bounded route-frequency map rather than full request bodies.

## Category scoring

A category binding maps a case-insensitive glob pattern such as `*solar*` to a scoring profile. Higher-priority bindings are evaluated first. Rescoring stores category-specific results separately from the active global profile, so no baseline/profile history is destroyed.

Service-managed crawl and watchlist runs refresh category scores automatically. Operators can force a refresh with:

```bash
alibaba-scraper category-rescore
```

## Alert delivery

v0.5 ships a webhook sink adapter. Each sink can configure:

- URL;
- optional HMAC-SHA256 signing secret;
- additional headers;
- event-kind filters;
- minimum severity;
- enabled/disabled state.

Delivery attempts are persisted. Failed deliveries remain retryable; successful deliveries are not resent to the same sink.

## Landed-cost scenarios

The calculator remains input-driven and jurisdiction-neutral. Saved scenarios persist the exact inputs and resulting calculation and can optionally reference a product key. Saving a scenario with an existing name updates it.

## Dashboards

`/` serves the production operations dashboard with API-key entry, health, charts, comparisons, saved scenarios, category bindings, alert sinks, and key metadata.

`/classic` preserves the v0.4 control dashboard for products, suppliers, jobs, watchlists, local alerts, scoring, and direct landed-cost calculations. It authenticates through the same session cookie after a key is entered on the operations dashboard.

## Network exposure

The default bind remains `127.0.0.1:8787`. API-key auth is enabled by default, but API keys alone do not provide transport encryption. If the service is intentionally exposed beyond localhost, use TLS directly or an authenticated/TLS reverse proxy and keep system/firewall access restricted.
