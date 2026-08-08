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

## 0.3 — Data platform

- Dedicated supplier model and supplier-product relationships.
- CSV/JSONL export from persisted data.
- Product field-diff history beyond pricing.
- Crawl error ledger/reporting and retry controls.
- Saved searches and watchlists.
- Query/report CLI commands.

## 0.4 — Rendering + service

- Optional Playwright adapter for public pages that require JavaScript rendering.
- Local FastAPI service.
- Job-control API.
- Product/supplier browser.
- Search filters and saved queries.
- Price/MOQ trend charts.
- Scraper health and crawl telemetry.

## 0.5 — Sourcing intelligence

- Supplier quality signals.
- Landed-cost input model.
- Price/MOQ opportunity scoring.
- Product change alerts.
- Search result ranking and sourcing shortlists.

## Guardrails

This project is for collecting data made publicly accessible by the target site. It should honor applicable terms, robots directives, rate limits, and access controls. Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
