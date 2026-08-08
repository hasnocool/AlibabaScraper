# Changelog

All notable changes to this project will be documented in this file.

The project follows Semantic Versioning.

## [0.2.0] - 2026-08-08

### Added

- Current Alibaba public search-page discovery and canonical product URL extraction.
- Product ID, supplier, category, origin, attributes, image, price, MOQ, and quantity-tier normalization.
- JSON-LD-first parsing with conservative HTML fallbacks.
- Async SQLite persistence using WAL mode through `aiosqlite`.
- Latest product snapshots and change-only price/MOQ observations.
- Persisted crawl jobs, queue claiming, interruption recovery, and resume commands.
- Crawl, resume, jobs, and product history CLI commands.
- Async retry/backoff and a coroutine-safe global request-start limiter.
- Discovery, parser, database, history, and pipeline tests.

### Changed

- Version bumped from 0.1.0 to 0.2.0.
- Dependency minimums updated to current tested package generations.
- Default user agent updated to `AlibabaScraper/0.2`.

## [0.1.0] - 2026-08-08

### Added

- Initial Python 3.12 project scaffold.
- Async HTTP scraper with bounded concurrency and non-blocking rate limiting.
- Normalized product model and basic HTML parser.
- Async-safe JSON persistence helper.
- Typer CLI, tests, linting, and GitHub Actions CI.
- Initial roadmap and project guardrails.
