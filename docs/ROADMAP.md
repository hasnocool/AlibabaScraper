# Roadmap

## 0.1 — Foundation ✅

- Async HTTP client and bounded concurrency.
- Normalized product model.
- Basic parser, JSON output, tests, and CI.

## 0.2 — Discovery + historical storage ✅

- Current search discovery and canonical product IDs/URLs.
- Resumable crawl jobs and persistent queues.
- Product/supplier metadata, price tiers, MOQ, attributes, categories.
- SQLite WAL persistence and change-only price/MOQ history.
- Retry/backoff and globally spaced async request starts.

## 0.3 — Data platform + sourcing intelligence ✅

- Supplier model and supplier-product relationships.
- CSV/JSONL exports.
- Product field-change history.
- Saved searches/watchlists and recurring recrawls.
- Sourcing/deal component scoring.
- Current-layout regression fixtures.

## 0.4 — Service + dashboards ✅

- FastAPI service and OpenAPI docs.
- Browser control dashboard.
- Terminal dashboard.
- Live crawl start/resume/cancel control.
- Product/supplier browsing and score filters.
- Configurable scoring profiles and persisted profile scores.
- Watchlist/high-score alert inbox.
- Generic landed-cost calculations.

## 0.5 — Operations + comparison

- Explicit schema migrations.
- Service install/upgrade/uninstall scripts and systemd integration.
- Dashboard crawl telemetry and performance charts.
- Product comparison and sourcing shortlists.
- Retry/error queue management.
- Alert delivery adapter interface.
- Landed-cost preset profiles with visible assumptions.

## 0.6 — Rendering + scale

- Optional Playwright normal-browser rendering for public JavaScript-only pages.
- Optional PostgreSQL persistence when measured workload warrants it.
- Multi-worker service coordination without duplicate crawl execution.
- API authentication/authorization for intentionally remote deployments.

## Guardrails

This project is for data made publicly accessible by the target site. It should honor applicable terms, robots directives, rate limits, and access controls. Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
