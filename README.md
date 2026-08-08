# AlibabaScraper

Async-first Python 3.12 toolkit for collecting and normalizing publicly accessible Alibaba product and supplier data.

## Goals

- Search/discover public product listings.
- Extract normalized product, supplier, price, MOQ, category, image, and URL data.
- Store results in JSONL/CSV/SQLite-friendly structures.
- Keep network and browser operations asynchronous and bounded.
- Respect site terms, robots directives, rate limits, and access controls.
- Never attempt CAPTCHA bypass, authentication bypass, or other anti-abuse circumvention.

## Status

Initial repository scaffold. Page adapters/selectors are intentionally isolated so Alibaba markup changes can be updated without rewriting the rest of the application.

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
alibaba-scraper --help
```

## Example

```bash
alibaba-scraper fetch "https://www.alibaba.com/product-detail/..." --format json
```

## Architecture

```text
src/alibaba_scraper/
├── cli.py        # CLI entrypoint
├── config.py     # Runtime settings
├── models.py     # Normalized data models
├── scraper.py    # Async fetch + parse orchestration
└── storage.py    # Async-safe output helpers
```

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for planned capabilities.
