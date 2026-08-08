# Changelog

All notable changes to this project will be documented in this file.

The project follows Semantic Versioning.

## [0.4.0] - 2026-08-08

### Added

- FastAPI control plane with local browser dashboard and OpenAPI docs.
- Live crawl start, resume, runtime-state, and cancellation controls.
- Product browser with query, supplier, currency, minimum-score, and maximum-price filters.
- Supplier browser backed by normalized supplier/product relationships.
- Dependency-free terminal dashboard with optional async refresh loop.
- Configurable named scoring profiles with component weights and high-score thresholds.
- Profile-specific score persistence and rescoring without new network collection.
- Local alert inbox for watchlist status/changes and high-scoring sourcing candidates.
- Generic landed-cost calculator with shipping, insurance, duty, tax, brokerage, packaging, other fees, and optional target-sale analysis.
- Dedicated service entrypoint and service host/port configuration.
- Service/control-plane, scoring-profile, landed-cost, runtime-cancellation, and API tests.
- `docs/SERVICE.md` architecture and operating guide.

### Changed

- Version bumped from 0.3.0 to 0.4.0.
- Main `alibaba-scraper` console entrypoint now registers the v0.4 control-plane commands while preserving existing commands.
- Watchlist runs now create control-plane alerts and active-profile scores even when launched from the existing CLI daemon.
- Live task cancellation persists a `cancelled` job state and returns in-progress queue items to `pending` for later resume.
- Default user agent updated to `AlibabaScraper/0.4`.

## [0.3.0] - 2026-08-08

### Added

- Sanitized regression fixtures derived from current public Alibaba layouts.
- CSV and JSONL exports.
- Normalized suppliers and supplier-product relationships.
- Field-level product change tracking.
- Saved-search watchlists, recurring recrawls, and watchlist run history.
- Deterministic sourcing/deal scoring and CLI ranking output.
- Additional public Alibaba product URL variants.

## [0.2.0] - 2026-08-08

### Added

- Current Alibaba public search-page discovery and canonical product URL extraction.
- Product/supplier/category/origin/attribute/image/price/MOQ normalization.
- JSON-LD-first parsing with conservative HTML fallbacks.
- Async SQLite WAL persistence, product observations, crawl queues, and resume support.
- Async retry/backoff and coroutine-safe request-start limiting.

## [0.1.0] - 2026-08-08

### Added

- Initial Python 3.12 project scaffold.
- Async HTTP scraper with bounded concurrency and non-blocking rate limiting.
- Normalized product model, Typer CLI, tests, linting, CI, and project governance docs.
