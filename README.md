# AlibabaScraper

Async-first Python 3.12 toolkit for discovering, normalizing, tracking, scoring, comparing, and operating sourcing research against publicly accessible Alibaba product and supplier data.

## Current architecture

```text
public Alibaba search/product pages
  -> canonical product discovery
  -> resumable SQLite crawl queue
  -> async collection + normalization
  -> product/supplier/history/change storage
  -> watchlists + sourcing scores
  -> category-specific scoring
  -> local + external alerts
  -> authenticated FastAPI / web / CLI control plane
  -> operational resilience: retry, backup, DLQ, logs, supplier history, TLS proxy tooling
```

## v0.6 operational resilience

v0.6 focuses on keeping an already-running deployment recoverable and observable:

- Targeted retry of selected failed crawl-queue rows without replaying successful work.
- API-key rotation with configurable overlap/grace periods.
- Opaque short-lived API tokens whose scopes cannot exceed their parent key.
- Structured JSON service/request/alert logging.
- Bounded rotating-file log retention.
- Online SQLite backups using SQLite's backup API.
- `PRAGMA integrity_check` verification for live databases and backups.
- Restore workflow with pre-restore safety backups and atomic replacement.
- Exponential alert-delivery backoff and persistent dead-letter queue.
- Manual dead-letter requeue after an operator fixes the destination/configuration.
- Supplier observed-data quality snapshots and time-series history.
- Caddy automatic-HTTPS and Nginx TLS reverse-proxy configuration generation.

Supplier quality is an **observed data/catalog quality signal** based on fields available to this project. It is not a claim about legal status, trustworthiness, manufacturing quality, solvency, or fulfillment reliability.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
```

Apply schema migrations:

```bash
alibaba-scraper migrate
```

## Authentication

Create an administrative key before running an authenticated service:

```bash
alibaba-scraper api-key-create local-admin --scopes admin
```

Only a prefix and SHA-256 digest are stored. The plaintext `abs_...` value is returned once.

Rotate a long-lived key with a 15-minute overlap:

```bash
alibaba-scraper api-key-rotate 1 --grace-minutes 15
```

Mint a one-hour read-only token derived from a parent key:

```bash
alibaba-scraper token-mint 2 --ttl-minutes 60 --scopes read
```

Short-lived tokens use the same `X-API-Key` transport but carry a bounded expiry and cannot obtain scopes the parent key did not have.

## Start the service

```bash
alibaba-scraper serve
```

Defaults:

- Operations dashboard: `http://127.0.0.1:8787/`
- Classic dashboard: `http://127.0.0.1:8787/classic`
- OpenAPI: `http://127.0.0.1:8787/docs`
- Public liveness: `http://127.0.0.1:8787/api/health/live`
- Database: `data/alibaba.sqlite3`

The service remains localhost-only by default.

## Targeted failed-queue recovery

Inspect only failed rows for a crawl:

```bash
alibaba-scraper queue-errors 12
alibaba-scraper queue-errors 12 --contains timeout
```

Move selected errors back to `pending` without touching completed rows:

```bash
alibaba-scraper queue-retry 12 --queue-ids 44,47,51
alibaba-scraper resume 12
```

A targeted retry is refused while the crawl job is actively `running`. This prevents an operator retry from racing workers currently claiming/updating queue rows.

The API equivalents are:

- `GET /api/jobs/{job_id}/errors`
- `POST /api/jobs/{job_id}/retry-errors`

The POST route can optionally schedule the resumed crawl after resetting the selected errors.

## SQLite backup, integrity, and restore

Check integrity:

```bash
alibaba-scraper db-integrity
```

Create a consistent online backup:

```bash
alibaba-scraper db-backup
alibaba-scraper db-backup --output /srv/backups/alibaba.sqlite3
```

Backups are verified before they are reported as successful and include a SHA-256 digest.

Restore only after stopping the service:

```bash
alibaba-scraper service-status --user
systemctl --user stop alibaba-scraper.service
alibaba-scraper db-restore data/backups/alibaba-20260808T200000Z.sqlite3 --yes
systemctl --user start alibaba-scraper.service
```

By default, restore first makes a `pre-restore` copy of the current database. The candidate backup and the temporary restored database must both pass `PRAGMA integrity_check` before the live database is atomically replaced.

## Structured JSON logging

The service emits one JSON object per log record and does not intentionally log API-key, cookie, authorization, or secret fields.

Default file output:

```text
data/logs/alibaba-scraper.jsonl
```

Retention defaults to 10 MiB per file plus seven rotated backups and is configurable through `.env`.

```bash
alibaba-scraper log-status
```

The same JSON records are also emitted to stderr/stdout so systemd/journald can collect them.

## Alert delivery resilience

Webhook sinks now have configurable retry policies:

- maximum attempts
- base backoff delay
- maximum backoff delay
- exponential delay between attempts
- persistent `dead_letter` state once attempts are exhausted

Configure a policy:

```bash
alibaba-scraper alert-sink-policy 1 \
  --max-attempts 6 \
  --base-backoff-seconds 30 \
  --max-backoff-seconds 3600
```

Review/requeue dead letters:

```bash
alibaba-scraper alert-dead-letters
alibaba-scraper alert-dead-retry 14
```

Failed alert deliveries do not busy-loop. A successful alert/sink pair is not resent.

## Supplier observed-data quality history

Capture current supplier snapshots:

```bash
alibaba-scraper supplier-quality-snapshot
alibaba-scraper supplier-quality
alibaba-scraper supplier-quality-history supplier:<key>
```

The long-running service also samples periodically. The score combines:

- product sourcing scores already calculated by the project
- normalized field completeness
- observed 30-day field-change stability
- catalog breadth visible to this database

The raw components are persisted alongside the aggregate so the result stays explainable.

## TLS / reverse proxy deployment

For an Internet-facing deployment, keep Uvicorn bound to `127.0.0.1` and terminate TLS in a dedicated reverse proxy.

Caddy with automatic HTTPS:

```bash
alibaba-scraper proxy-render caddy scraper.example.com \
  --email ops@example.com \
  --output ./deploy/Caddyfile
```

Nginx with operator-managed certificate files:

```bash
alibaba-scraper proxy-render nginx scraper.example.com \
  --cert-file /etc/letsencrypt/live/scraper.example.com/fullchain.pem \
  --key-file /etc/letsencrypt/live/scraper.example.com/privkey.pem \
  --output ./deploy/alibaba-scraper.conf
```

Generated configs proxy only to the local service and include HSTS and basic browser-security headers. API keys authenticate requests; TLS is still required to protect them in transit.

## Existing platform capabilities

The earlier stages remain available:

- public search/product discovery
- product and supplier normalization
- SQLite history and resumable crawl jobs
- CSV/JSONL exports
- watchlists and automatic recrawls
- field-level change detection
- deterministic sourcing scores
- named and category-specific scoring profiles
- landed-cost calculations and saved scenarios
- local alert inbox and signed external webhooks
- FastAPI/web/CLI dashboards and live task control
- systemd installation/management
- health, readiness, telemetry, and Prometheus-style metrics

## Guardrails

This project is for publicly accessible product/supplier data. Operate it in accordance with applicable site terms, robots directives, rate limits, and access controls. It does not implement CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md), [`docs/RESILIENCE.md`](docs/RESILIENCE.md), and [`docs/ROADMAP.md`](docs/ROADMAP.md).
