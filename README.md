# AlibabaScraper

Async-first Python 3.12 toolkit for discovering, normalizing, and tracking publicly accessible Alibaba product and supplier data.

## Pipeline

```text
search query
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
products + change-only price/MOQ history
```

## Current capabilities

- Public Alibaba product search discovery using the current `/search/page` URL shape.
- Canonicalization and deduplication of `/product-detail/..._<id>.html` URLs.
- Async HTTP/2 collection with globally spaced request starts, bounded concurrency, retry/backoff, and no blocking sleeps.
- Product title, numeric product ID, supplier name/URL, origin, category, images, attributes, price range, quantity-price tiers, and MOQ extraction.
- JSON-LD first, with isolated HTML fallbacks for markup changes.
- SQLite WAL storage using `aiosqlite`.
- Current product snapshots plus history rows only when tracked price/MOQ values change.
- Persisted crawl jobs and queues that can safely recover URLs left `in_progress` after interruption.
- CLI commands for crawling, resuming, listing jobs, inspecting history, and fetching a single product.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
```

## Crawl a search

```bash
alibaba-scraper crawl "solar panel" --limit 100 --pages 5
```

The default database is `data/alibaba.sqlite3`.

Use a different database:

```bash
alibaba-scraper crawl "solar panel" --database data/research.sqlite3 --limit 250 --pages 10
```

## Resume a job

```bash
alibaba-scraper jobs
alibaba-scraper resume 1
```

If a process stopped while URLs were marked `in_progress`, resuming the job returns those URLs to the pending queue before continuing.

## Price / MOQ history

```bash
alibaba-scraper history 1601732011579
```

A history row is added only when the normalized tracked values change, so repeated identical crawls do not create needless history noise.

## Fetch one product

```bash
alibaba-scraper fetch "https://www.alibaba.com/product-detail/..._1601732011579.html"
```

Write normalized JSON:

```bash
alibaba-scraper fetch "https://www.alibaba.com/product-detail/..._1601732011579.html" -o data/product.json
```

## Runtime controls

Copy `.env.example` to `.env` and tune:

- `ALIBABA_SCRAPER_MAX_CONCURRENCY`
- `ALIBABA_SCRAPER_REQUESTS_PER_SECOND`
- `ALIBABA_SCRAPER_TIMEOUT_SECONDS`
- `ALIBABA_SCRAPER_MAX_RETRIES`
- `ALIBABA_SCRAPER_RETRY_BACKOFF_SECONDS`
- `ALIBABA_SCRAPER_DATABASE_PATH`

Defaults intentionally favor low resource usage and conservative request rates.

## Data model

SQLite stores three main groups of data:

- `products`: latest normalized state for each product.
- `product_observations`: historical price/MOQ changes.
- `crawl_jobs` + `crawl_queue`: resumable collection state.

## Site behavior

Alibaba can change its page markup and may render some pages dynamically. Parsers are deliberately isolated and prioritize structured metadata. An optional normal-browser rendering adapter remains on the roadmap for pages that require JavaScript rendering; the project does not implement CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention.

The collector should be operated in accordance with applicable site terms, robots directives, rate limits, and access controls.

See [`docs/ROADMAP.md`](docs/ROADMAP.md).
