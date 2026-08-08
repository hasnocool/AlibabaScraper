# AlibabaScraper

Async-first Python 3.12 toolkit for discovering, normalizing, tracking, scoring, and browsing publicly accessible Alibaba product and supplier data.

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
  -> sourcing scores + profiles
  -> alerts
  -> FastAPI / web / CLI dashboards
```

## v0.4 capabilities

- FastAPI service and OpenAPI docs.
- Browser dashboard with products, suppliers, jobs, watchlists, alerts, scoring profiles, and landed-cost tools.
- Dependency-free terminal dashboard using the same SQLite/control repositories.
- Live crawl start, resume, and cancellation controls.
- Product browser with query, supplier, currency, score, and maximum-price filters.
- Supplier browser with product relationships.
- Configurable scoring profiles with adjustable component weights and high-score alert thresholds.
- Profile-specific rescoring without re-scraping products.
- Watchlist run/change alerts and high-score sourcing-candidate alerts.
- Generic landed-cost estimates from caller-provided shipping, insurance, duty, tax, brokerage, packaging, and other fees.
- Existing CSV/JSONL exports, price/MOQ history, resumable crawl jobs, watchlist daemon, and baseline scoring.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
```

## Start the service

```bash
alibaba-scraper serve
```

Defaults:

- Dashboard: `http://127.0.0.1:8787/`
- OpenAPI: `http://127.0.0.1:8787/docs`
- Database: `data/alibaba.sqlite3`

You can also use the dedicated entrypoint:

```bash
alibaba-service
```

The service binds to localhost by default. If you intentionally expose it to another machine, put authentication/TLS in front of it first because the API includes crawl and watchlist control endpoints.

## CLI dashboard

Show one snapshot:

```bash
alibaba-scraper dashboard
```

Continuously refresh without blocking the event loop:

```bash
alibaba-scraper dashboard --watch --refresh-seconds 5
```

## Crawl and live job control

The existing direct CLI still works:

```bash
alibaba-scraper crawl "solar panel" --limit 100 --pages 5
alibaba-scraper jobs
alibaba-scraper resume 1
```

The web service can start/resume/cancel in-process jobs from the dashboard or API. Cancellation returns in-progress queue items to `pending`, so the persisted crawl remains resumable.

## Product and supplier browsing

```bash
alibaba-scraper products --query "lifepo4" --min-score 70 --currency USD
alibaba-scraper product 1601732011579
alibaba-scraper suppliers
alibaba-scraper supplier-products supplier:<key>
```

The browser dashboard exposes the same core product/supplier information and active-profile score filters.

## Scoring profiles

The baseline component scores remain normalized 0-100 values. A scoring profile changes how those components are weighted:

- price value
- MOQ flexibility
- supplier identity completeness
- quantity-tier discount depth
- data completeness

Create and activate a profile:

```bash
alibaba-scraper profile-add "Small Batch" \
  --price-weight 25 \
  --moq-weight 45 \
  --supplier-weight 15 \
  --tier-weight 5 \
  --data-quality-weight 10 \
  --alert-score 85 \
  --activate

alibaba-scraper profile-activate 2
alibaba-scraper rescore --profile-id 2
```

Profile rescoring uses persisted product records; it does not generate Alibaba requests.

## Watchlists and alerts

Existing watchlists can be run manually or by the recurring daemon:

```bash
alibaba-scraper watch-add "solar" "solar panel" --every-minutes 360
alibaba-scraper watch-run 1
alibaba-scraper watch-daemon --poll-seconds 60
```

v0.4 adds a local alert inbox for:

- watchlist failures or partial failures
- watchlist runs that detect normalized field changes
- products above the active profile's high-score threshold

```bash
alibaba-scraper alerts --unread-only
alibaba-scraper alert-read 3
```

## Landed-cost calculator

```bash
alibaba-scraper landed-cost 10.00 100 \
  --currency CAD \
  --shipping 120 \
  --insurance 10 \
  --duty-pct 5 \
  --tax-pct 12 \
  --brokerage 25 \
  --packaging-per-unit 0.40
```

This is a transparent generic estimate using the rates and fees you provide. It does not infer jurisdiction-specific customs/tax rules.

## Important API routes

| Route | Purpose |
| --- | --- |
| `GET /api/dashboard` | Dashboard summary |
| `GET /api/products` | Product browser and score filters |
| `GET /api/products/{id}` | Product detail + recent changes |
| `GET /api/suppliers` | Supplier browser |
| `GET /api/jobs` | Persisted crawl jobs |
| `POST /api/jobs` | Start crawl |
| `POST /api/jobs/{id}/resume` | Resume crawl |
| `GET /api/runtime` | Live service task state |
| `POST /api/runtime/{key}/cancel` | Cancel live task |
| `GET/POST /api/watchlists` | Watchlist management |
| `GET /api/alerts` | Alert inbox |
| `GET/POST /api/scoring/profiles` | Scoring profiles |
| `POST /api/scoring/rescore` | Profile-specific rescore |
| `POST /api/landed-cost` | Landed-cost estimate |

## Runtime configuration

Copy `.env.example` to `.env` and tune:

- `ALIBABA_SCRAPER_TIMEOUT_SECONDS`
- `ALIBABA_SCRAPER_MAX_CONCURRENCY`
- `ALIBABA_SCRAPER_REQUESTS_PER_SECOND`
- `ALIBABA_SCRAPER_MAX_RETRIES`
- `ALIBABA_SCRAPER_RETRY_BACKOFF_SECONDS`
- `ALIBABA_SCRAPER_DATABASE_PATH`
- `ALIBABA_SCRAPER_SERVICE_HOST`
- `ALIBABA_SCRAPER_SERVICE_PORT`

Defaults intentionally favor low resource use and conservative request rates.

## Storage architecture

The project uses SQLite WAL mode with separate async connections/locks for distinct responsibilities:

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

control-plane state
  scoring_profiles
  profile_scores
  alerts
```

See [`docs/SERVICE.md`](docs/SERVICE.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Guardrails

This project is for publicly accessible product/supplier data. Operate it in accordance with applicable site terms, robots directives, rate limits, and access controls. It does not implement CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
