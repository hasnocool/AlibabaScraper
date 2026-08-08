# Roadmap

## 0.1 — Foundation

- Async HTTP client and bounded concurrency.
- Normalized product model.
- Basic page parser.
- JSON output.
- Unit tests and CI.

## 0.2 — Discovery

- Search-result adapters.
- Pagination and resumable crawl jobs.
- Supplier model and supplier-product relationships.
- Better price/MOQ/attribute extraction.
- Duplicate detection and canonical URLs.

## 0.3 — Data platform

- SQLite/PostgreSQL persistence adapters.
- Price history and product-change tracking.
- CSV/JSONL exports.
- Crawl run metadata and error ledger.
- CLI query/report commands.

## 0.4 — Dashboard/API

- Local FastAPI service.
- Product/supplier browser.
- Search filters and saved queries.
- Price/MOQ trend charts.
- Job queue and scraper health page.

## Guardrails

This project is for collecting data made publicly accessible by the target site.
It should honor applicable terms, robots directives, rate limits, and access controls.
Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other
anti-abuse circumvention features.
