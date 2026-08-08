# Changelog

All notable changes to this project will be documented in this file.

The project follows Semantic Versioning.

## [0.6.0] - 2026-08-08

### Added

- Targeted failed crawl-queue inspection/retry with job-running conflict protection.
- API-key rotation with optional overlap/grace periods.
- Short-lived opaque API tokens with parent-scope enforcement and 24-hour maximum TTL.
- Structured JSON logging with bounded rotating-file retention.
- SQLite online backup, SHA-256 reporting, integrity checks, and guarded atomic restore.
- Alert-delivery exponential backoff, configurable retry limits, dead-letter persistence, and manual requeue.
- Supplier observed-data quality snapshots/history with explainable component metrics.
- Caddy automatic-HTTPS and Nginx TLS reverse-proxy configuration renderers.
- FastAPI resilience endpoints and matching CLI operator commands.
- Periodic supplier-quality sampling in the long-running service.
- v0.6 resilience regression tests.

### Changed

- Schema version advanced from 1 to 2.
- Version bumped from 0.5.0 to 0.6.0.
- Service health/metrics now include alert dead-letter state and supplier sampler configuration.
- Webhook sinks now persist retry/backoff policy.
- Default user agent updated to `AlibabaScraper/0.6`.

## [0.5.0] - 2026-08-08

### Added

- API-key authentication and scopes.
- Explicit schema migrations.
- systemd operator tooling.
- Service health/telemetry and richer comparisons.
- Saved landed-cost scenarios and category-specific scoring profiles.
- Signed configurable external webhook delivery.

## [0.4.0] - 2026-08-08

### Added

- FastAPI control plane, browser/CLI dashboards, live task control, profiles, alerts, and landed cost.

## [0.3.0] - 2026-08-08

### Added

- Suppliers, exports, field changes, watchlists, recurring recrawls, sourcing scores, and current-layout fixtures.

## [0.2.0] - 2026-08-08

### Added

- Real discovery, normalization, SQLite history, resumable queues, and async retry/rate control.

## [0.1.0] - 2026-08-08

### Added

- Initial async Python 3.12 scaffold, normalized models, Typer CLI, tests, linting, and CI.
