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
- Browser and terminal dashboards.
- Live crawl start/resume/cancel control.
- Product/supplier browsing and score filters.
- Configurable scoring profiles and persisted profile scores.
- Watchlist/high-score alert inbox.
- Generic landed-cost calculations.

## 0.5 — Production operations ✅

- Scoped API-key authentication, expiry, revocation, and OpenAPI security metadata.
- Transactional schema migrations and explicit migration command.
- systemd user/system installation, removal, and status tooling.
- Service liveness/readiness, Prometheus-style metrics, and request latency/error telemetry.
- Service-owned recurring watchlist scheduler and alert-delivery dispatcher.
- Rich product comparison, price-history, category, and score-distribution data/visuals.
- Saved landed-cost scenarios.
- Category-specific scoring-profile bindings and category score persistence.
- Configurable signed webhook alert delivery with severity/event filters and delivery history.

## 0.6 — Operational resilience

- Targeted retry/error queue management.
- API-key rotation and optional short-lived access tokens.
- JSON logging, retention, backups, integrity checks, and restore tooling.
- Alert dead-letter/backoff policies and additional notification adapters.
- Supplier-quality history and richer comparison reports.
- Optional TLS/reverse-proxy deployment recipes.

## 0.7 — Rendering + scale

- Optional Playwright normal-browser rendering for public JavaScript-only pages.
- Optional PostgreSQL persistence only when measured workload warrants it.
- Multi-worker service coordination without duplicate crawl execution.

## Guardrails

This project is for data made publicly accessible by the target site. It should honor applicable terms, robots directives, rate limits, and access controls. Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention features.
