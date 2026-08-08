# Roadmap

## 0.1 — Foundation ✅

- Async HTTP client and bounded concurrency.
- Normalized product model.
- Basic page parser.
- JSON output.
- Unit tests and CI.

## 0.2 — Discovery + historical storage ✅

- Current search-result adapter.
- Product URL canonicalization and product IDs.
- Resumable crawl jobs and persistent queues.
- Product and supplier metadata extraction.
- Price ranges, quantity tiers, MOQ, attributes, and categories.
- SQLite WAL persistence.
- Change-only price/MOQ history.
- Retry/backoff and globally spaced async request starts.

## 0.3 — Data platform + watchlists + sourcing intelligence ✅

- Sanitized current-layout regression fixtures.
- Dedicated supplier model and supplier-product relationships.
- CSV/JSONL export from persisted data.
- Product field-diff history beyond pricing.
- Saved searches and recurring watchlists.
- Watchlist run history and change counts.
- Non-blocking automatic recrawl daemon.
- Peer-relative sourcing/deal scores.
- Additional current public Alibaba product URL shapes.

## 0.4 — Rendering + service

- Optional Playwright adapter for public pages that require JavaScript rendering.
- Local FastAPI service.
- Job-control API.
- Product/supplier browser.
- Saved searches and watchlist control.
- Price/MOQ/change trend charts.
- Scraper health and crawl telemetry.
- Mirrored CLI dashboard.

## 0.5 — Sourcing intelligence expansion

- Supplier quality history and public-signal scoring.
- Landed-cost model: shipping, duty, exchange rate, packaging, target quantity.
- Configurable/category-specific scoring weights.
- Product change alerts and notification sinks.
- Search-result ranking and sourcing shortlists.
- Comparison reports across suppliers and products.

## 0.6 — Scale

- PostgreSQL persistence adapter.
- Multi-process/distributed workers with safe leases.
- Schema migration/version tooling.
- Retention policies and compressed archival exports.

## Guardrails

This project is for collecting data made publicly accessible by the target site. It should honor applicable terms, robots directives, rate limits, and access controls. Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
