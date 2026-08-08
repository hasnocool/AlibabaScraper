# Service and Dashboard Architecture

## Purpose

v0.6 keeps the authenticated v0.5 control plane intact and adds an operational-resilience layer for recovery, credential rotation, bounded logging, database protection, alert dead letters, supplier-history sampling, and TLS reverse-proxy deployment.

## Process model

```text
FastAPI / Uvicorn
  |
  +-- Database ---------------- core product/crawl state
  +-- IntelligenceRepository -- suppliers, changes, watchlists, baseline scores
  +-- ControlRepository ------- profile scores, alerts, dashboard read models
  +-- ProductionRepository ---- API keys, scenarios, category bindings, alert sinks
  +-- ResilienceRepository ---- targeted queue retry + supplier quality history
  +-- AlibabaScraper ---------- bounded async public-page collection
  +-- RuntimeManager ---------- live crawl/watchlist tasks
  +-- watchlist scheduler ----- automatically runs due saved searches
  +-- alert dispatcher -------- backoff/dead-letter-aware webhook delivery
  +-- supplier sampler -------- periodic observed-data quality snapshots
  +-- TelemetryRegistry ------- request/error/latency/uptime aggregates
  +-- JSON logging ------------ rotating file + process stream
```

The service opens each SQLite repository once for its lifespan. Writes remain separated by repository-specific coroutine locks and WAL mode. Resilience operations that mutate crawl queues refuse to run against an actively running crawl.

## Live task and queue recovery

Normal API-started crawls still create durable jobs and run through `RuntimeManager`. Cancellation keeps the existing behavior: it persists `cancelled` and returns `in_progress` queue rows to `pending`.

v0.6 adds targeted recovery for rows already in `error`. Operators can inspect only failed queue entries and select rows by ID or error substring. Selected rows return to `pending`; completed rows are never replayed. The operation uses an immediate SQLite transaction and is rejected while the owning job status is `running`.

## Authentication and credential lifecycle

Authentication remains enabled by default. Persistent API keys are opaque `abs_...` values; only prefixes and SHA-256 digests are stored.

v0.6 adds linked key rotation and short-lived opaque tokens:

- rotation creates the replacement before retiring the old key;
- an optional grace period permits controlled client rollover;
- rotation lineage is persisted;
- short-lived tokens have a maximum 24-hour TTL;
- token scopes cannot exceed the parent key;
- expired, revoked, or disabled credentials do not authenticate.

Both persistent keys and tokens use `X-API-Key`. Browser sessions still use the HttpOnly same-site cookie flow.

## Migrations

`migrations.py` remains the ordered transactional migration registry. Schema version 2 adds key lineage/token metadata, alert retry/dead-letter state, alert-sink retry policies, and supplier-quality snapshots.

The service applies missing migrations before opening long-lived repositories. `alibaba-scraper migrate` remains the explicit operator path.

## Background work

A normal long-running service can own three non-blocking loops:

1. watchlist scheduler — runs due saved searches;
2. alert dispatcher — delivers due alerts and honors retry windows/dead letters;
3. supplier-quality sampler — periodically persists observed-data supplier metrics.

Each loop can be configured independently. None uses busy-wait polling.

## Health, telemetry, and logs

`/api/health/live`, `/api/health`, `/api/health/ready`, and `/metrics` remain the supervision endpoints. Detailed health now exposes dead-letter counts and supplier-sampler configuration.

Request telemetry stays aggregate and bounded. Structured logs are JSON lines containing event metadata such as method, path, status, and latency; request bodies and authentication/secret values are not intentionally logged. Rotating-file retention bounds local disk usage while the same stream remains suitable for journald collection.

## Alert delivery

Webhook sinks retain HMAC signing, event-kind filters, severity filters, and custom headers. v0.6 adds per-sink:

- maximum attempts;
- base backoff;
- maximum backoff.

Failures are scheduled with capped exponential backoff. Exhausted alert/sink pairs move to persistent `dead_letter` state and stop retrying automatically. Operators can inspect and requeue individual dead letters after correcting the cause.

## Database resilience

Online backups use SQLite's native backup API so WAL state is captured consistently. Backups are integrity checked and SHA-256 hashed.

Restore remains deliberately outside the live HTTP API. The CLI requires explicit confirmation; operators should stop the service first. The restore path validates the source backup, creates a pre-restore safety copy by default, restores into a temporary SQLite database, verifies it, and atomically replaces the target only after validation succeeds.

## Supplier observed-data quality

`ResilienceRepository` persists explainable supplier snapshots composed only from data visible to AlibabaScraper: product sourcing-score averages, field completeness, recent observed field-change stability, and catalog breadth.

This is not a trust, legal, financial, safety, manufacturing-quality, or fulfillment rating. The components are stored with every snapshot so trends can be inspected without hiding the underlying evidence.

## TLS and network exposure

Uvicorn remains bound to `127.0.0.1:8787` by default. v0.6 can render hardened Caddy or Nginx reverse-proxy configurations that terminate TLS and proxy back to loopback.

Caddy output is suitable for automatic HTTPS. Nginx output expects operator-supplied certificate/key paths. Generated configs include baseline HSTS and browser-security headers. API-key authentication does not replace transport encryption for intentionally remote deployments.
