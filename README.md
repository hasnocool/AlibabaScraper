# AlibabaScraper

Async-first Python 3.12 toolkit for authenticated Alibaba sourcing research, historical tracking, scoring, alerting, and production operations.

## Current pipeline

```text
Alibaba search
  -> canonical product URLs / IDs
  -> resumable crawl queue
  -> async product collection
  -> product + supplier normalization
  -> SQLite WAL snapshots/history
  -> field-level change detection
  -> saved-search watchlists
  -> global + category-specific sourcing scores
  -> local alerts + external delivery sinks
  -> authenticated FastAPI / web / CLI operations
```

## v0.5 production capabilities

- Scoped API-key authentication with one-time plaintext key creation and hash-only persistence.
- Read/write/admin scopes, key expiry, revocation, and last-used tracking.
- Explicit transactional SQLite migrations with an operator `migrate` command.
- systemd user/system service install, uninstall, and status commands.
- Liveness/readiness endpoints, Prometheus-style metrics, and request/error/latency telemetry.
- One long-running service process for the API/dashboard, recurring watchlist scheduler, and alert dispatcher.
- Production operations dashboard plus the preserved classic control dashboard.
- Product comparison, category composition, category score distribution, and price-history chart data.
- Saved landed-cost scenarios linked optionally to products.
- Category-pattern scoring-profile bindings with separate persisted category scores.
- Configurable webhook alert sinks with severity/event filters, optional HMAC-SHA256 signatures, and delivery history/retries.
- Existing live crawl controls, suppliers, watchlists, exports, history, local alerts, and baseline/profile scoring remain available.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
```

## Upgrade / migrate

```bash
alibaba-scraper migrate
```

The service also applies missing migrations before opening its long-lived repositories.

## Create the first API key

Authentication is enabled by default. Bootstrap an administrator key locally:

```bash
alibaba-scraper api-key-create local-admin --scopes admin
```

The generated `abs_...` key is shown only once. The database stores its prefix and SHA-256 digest, never the plaintext key.

List or revoke keys:

```bash
alibaba-scraper api-keys
alibaba-scraper api-key-revoke 2
```

## Start the production service

```bash
alibaba-service
```

or:

```bash
alibaba-scraper serve
```

Defaults:

- Production dashboard: `http://127.0.0.1:8787/`
- Classic control dashboard: `http://127.0.0.1:8787/classic`
- OpenAPI: `http://127.0.0.1:8787/docs`
- Database: `data/alibaba.sqlite3`

Enter the API key on the production dashboard. The browser exchanges it for an HttpOnly same-site session cookie.

Header API clients use:

```text
X-API-Key: abs_...
```

## systemd service

A normal user installation:

```bash
alibaba-scraper service-install --user --env-file .env
alibaba-scraper service-status --user
```

Remove it with:

```bash
alibaba-scraper service-uninstall --user
```

System-wide installation is also supported when run with appropriate permissions:

```bash
sudo -E alibaba-scraper service-install --system --env-file /etc/alibaba-scraper.env
```

The installer requires at least one API key when authentication is enabled.

## Health and metrics

Public process liveness:

```bash
curl http://127.0.0.1:8787/api/health/live
```

Detailed authenticated health:

```bash
curl -H 'X-API-Key: abs_...' http://127.0.0.1:8787/api/health
```

Prometheus-style metrics:

```bash
curl -H 'X-API-Key: abs_...' http://127.0.0.1:8787/metrics
```

Health includes schema version, active profile, runtime tasks, scheduler state, alert-delivery status, request counts, server-error counts, latency, and uptime.

## Product comparison and charts

CLI comparison:

```bash
alibaba-scraper compare 1601732011579 1601771345931
```

The operations dashboard provides:

- category product/supplier composition;
- category-specific score distribution;
- side-by-side product comparisons;
- product price/MOQ history charts.

## Scoring profiles and category bindings

Create profiles with the existing commands, then bind category patterns:

```bash
alibaba-scraper profile-add "Solar sourcing" --price-weight 45 --moq-weight 20
alibaba-scraper profile-bind-category '*solar*' 2 --priority 200
alibaba-scraper profile-bind-category '*battery*' 3 --priority 150
alibaba-scraper profile-bindings
alibaba-scraper category-rescore
```

Patterns are case-insensitive globs. Higher priority bindings are evaluated first. Category scores are stored separately from the global active-profile score so different sourcing strategies do not overwrite one another.

## Saved landed-cost scenarios

The transparent generic landed-cost calculator remains available directly:

```bash
alibaba-scraper landed-cost 10.00 100 --currency CAD --shipping 120 --duty-pct 5
```

Save exact assumptions/results for later comparison:

```bash
alibaba-scraper landed-scenario-save '100-unit import' 12.50 100 \
  --currency CAD \
  --shipping 180 \
  --duty-pct 5 \
  --tax-pct 12

alibaba-scraper landed-scenarios
```

Scenarios may optionally reference a product key. Rates remain caller-provided; the application does not invent jurisdiction-specific customs rules.

## External alert delivery

The local alert inbox still records watchlist changes/errors and high-score candidates. Add a webhook sink to deliver selected alerts externally:

```bash
alibaba-scraper alert-sink-add ops https://example.invalid/alibaba-alerts \
  --secret 'replace-me' \
  --event-kinds high_score,watchlist_change \
  --minimum-severity info
```

The long-running service dispatches automatically. Manual pass:

```bash
alibaba-scraper alert-deliver
```

When a secret is set, the exact JSON body is signed with HMAC-SHA256 and sent as:

```text
X-AlibabaScraper-Signature: sha256=<hex>
```

Sink list/API responses never return the stored secret.

## Watchlists

The production service now checks due watchlists itself, so a systemd deployment does not require a second daemon:

```bash
alibaba-scraper watch-add "solar" "solar panel" --every-minutes 360
```

The standalone `watch-daemon` command remains available for non-service workflows.

## API authentication scopes

- `read`: GET/HEAD API operations.
- `write`: write operations plus read access.
- `admin`: API-key and alert-sink administration plus all other access.

`GET /api/health/live` is intentionally unauthenticated for process supervision. Detailed health, metrics, and data/control routes require authentication when `ALIBABA_SCRAPER_AUTH_REQUIRED=true`.

## Runtime configuration

Copy `.env.example` to `.env`. Important production controls:

- `ALIBABA_SCRAPER_DATABASE_PATH`
- `ALIBABA_SCRAPER_SERVICE_HOST`
- `ALIBABA_SCRAPER_SERVICE_PORT`
- `ALIBABA_SCRAPER_AUTH_REQUIRED`
- `ALIBABA_SCRAPER_WATCH_SCHEDULER_ENABLED`
- `ALIBABA_SCRAPER_WATCH_SCHEDULER_POLL_SECONDS`
- `ALIBABA_SCRAPER_ALERT_DISPATCH_INTERVAL_SECONDS`
- `ALIBABA_SCRAPER_ALERT_DELIVERY_TIMEOUT_SECONDS`
- existing collection concurrency/rate/retry settings

Defaults remain conservative and localhost-only.

## Storage architecture

```text
core crawl state
  products
  product_observations
  crawl_jobs
  crawl_queue

intelligence state
  suppliers
  supplier_products
  product_changes
  product_scores
  watchlists
  watchlist_runs

control state
  scoring_profiles
  profile_scores
  alerts

production operations (migration-managed)
  schema_migrations
  api_keys
  landed_cost_scenarios
  category_scoring_bindings
  category_profile_scores
  alert_sinks
  alert_deliveries
```

See [`docs/SERVICE.md`](docs/SERVICE.md), [`docs/OPERATIONS.md`](docs/OPERATIONS.md), and [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Security and site guardrails

API keys authenticate requests but do **not** encrypt traffic. Keep the default localhost bind or use TLS/reverse proxy protection when intentionally exposing the service to another machine.

This project is for publicly accessible product/supplier data. Operate it in accordance with applicable site terms, robots directives, rate limits, and access controls. It does not implement CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
