# AlibabaScraper

Async-first Python 3.12 toolkit for discovering, normalizing, tracking, exporting, and scoring publicly accessible Alibaba product and supplier data.

## Pipeline

```text
saved search / one-off query
   ↓
Alibaba search pages
   ↓
canonical product URLs + product IDs
   ↓
resumable SQLite crawl queue
   ↓
async product fetches
   ↓
JSON-LD + conservative HTML fallbacks
   ↓
product / supplier / price / MOQ normalization
   ↓
product snapshots + field changes + supplier relationships
   ↓
peer-relative sourcing score
   ↓
CSV / JSONL / watchlist recrawls
```

## Current capabilities

- Public Alibaba search discovery with product-detail and product-introduction URL support.
- Canonicalization and deduplication of public Alibaba product URLs.
- Async HTTP/2 collection with globally spaced request starts, bounded concurrency, retry/backoff, and no blocking sleeps.
- Product title, ID, supplier, origin, category, images, attributes, price range, quantity tiers, and MOQ extraction.
- JSON-LD first with isolated HTML fallbacks.
- Sanitized regression fixtures derived from current public Alibaba page layouts.
- SQLite WAL storage with separate async connections for crawl state and derived intelligence.
- Current product snapshots, price/MOQ observations, and normalized field-level change events.
- Supplier table plus supplier-to-product relationships.
- Saved search watchlists, due scheduling, manual recrawls, and a non-blocking watch daemon.
- Deterministic sourcing/deal scoring using peer price, MOQ, supplier completeness, tier discount, and data quality.
- CSV and JSONL exports including current sourcing scores.
- Persisted crawl jobs and queues that recover `in_progress` work after interruption.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
```

## Crawl and score a search

```bash
alibaba-scraper crawl "solar panel" --limit 100 --pages 5
alibaba-scraper scores --limit 25
```

The default database is `data/alibaba.sqlite3`.

## Export data

```bash
alibaba-scraper export data/products.jsonl --format jsonl
alibaba-scraper export data/products.csv --format csv
```

Exports include the normalized product payload and, when available, the latest sourcing score.

## Suppliers

```bash
alibaba-scraper suppliers --limit 50
alibaba-scraper supplier-products supplier:<key>
```

Supplier identities are normalized from supplier URL when available, otherwise from name/country. Products are linked through a many-to-many relationship table.

## Changes

```bash
alibaba-scraper changes --limit 100
alibaba-scraper changes --job-id 12
alibaba-scraper history 1601732011579
```

`history` shows price/MOQ observations. `changes` reports normalized field changes including title, supplier, category, price, MOQ, and attributes.

## Saved searches / watchlists

Create a saved search that is immediately due for its first run:

```bash
alibaba-scraper watch-add "solar-panels" "solar panel" --every-minutes 360 --limit 100 --pages 5
```

Inspect and run watchlists:

```bash
alibaba-scraper watchlists
alibaba-scraper watch-run 1
alibaba-scraper watch-run-due
```

Run automatic recrawls continuously:

```bash
alibaba-scraper watch-daemon --poll-seconds 60
```

The daemon uses `asyncio.sleep()` and async database/network operations; it does not busy-wait or block the event loop.

## Resume a crawl

```bash
alibaba-scraper jobs
alibaba-scraper resume 1
```

If a process stopped while URLs were `in_progress`, resume returns them to the pending queue before continuing.

## Fetch one product

```bash
alibaba-scraper fetch "https://www.alibaba.com/product-detail/..._1601732011579.html"
alibaba-scraper fetch "https://www.alibaba.com/product-detail/..._1601732011579.html" -o data/product.json
```

## Sourcing score

The score is a deterministic prioritization signal, not a guarantee of product quality, supplier reliability, profitability, or landed cost. The current 0-100 score combines:

- 35% minimum price versus the same-currency median in the crawl.
- 20% MOQ flexibility.
- 20% supplier identity completeness.
- 10% quantity-tier discount depth.
- 15% normalized data completeness.

Future versions can add shipping/landed cost, supplier history, certification validation, and user-defined scoring weights.

## Runtime controls

Copy `.env.example` to `.env` and tune:

- `ALIBABA_SCRAPER_MAX_CONCURRENCY`
- `ALIBABA_SCRAPER_REQUESTS_PER_SECOND`
- `ALIBABA_SCRAPER_TIMEOUT_SECONDS`
- `ALIBABA_SCRAPER_MAX_RETRIES`
- `ALIBABA_SCRAPER_RETRY_BACKOFF_SECONDS`
- `ALIBABA_SCRAPER_DATABASE_PATH`

Defaults intentionally favor low resource usage and conservative request rates.

## SQLite data model

Core crawl tables:

- `products`
- `product_observations`
- `crawl_jobs`
- `crawl_queue`

Derived intelligence tables:

- `suppliers`
- `supplier_products`
- `product_changes`
- `product_scores`
- `watchlists`
- `watchlist_runs`

## Site behavior and guardrails

Alibaba can change markup and may render some pages dynamically. Parsers are isolated and prioritize structured metadata. An optional normal-browser rendering adapter remains on the roadmap for public pages that require JavaScript rendering.

Operate the collector in accordance with applicable site terms, robots directives, rate limits, and access controls. The project does not implement CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention.

See [`docs/ROADMAP.md`](docs/ROADMAP.md).
