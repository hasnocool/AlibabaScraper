# TODO

## 0.2 follow-up

- [x] Add current Alibaba search-result discovery.
- [x] Extract and canonicalize product IDs and URLs.
- [x] Extract supplier details, prices, MOQ, categories, attributes, and images.
- [x] Add retry/backoff for transient HTTP failures.
- [x] Add crawl checkpoint/resume support.
- [x] Add SQLite persistence with async access.
- [x] Add price/MOQ history.

## Next

- [ ] Capture real response fixtures from several public Alibaba categories and grow parser regression coverage.
- [ ] Add CSV and JSONL bulk exports from SQLite.
- [ ] Add product-change diff reports beyond price/MOQ.
- [ ] Add supplier tables and supplier-to-product relationships.
- [ ] Add optional Playwright normal-browser rendering for JavaScript-only public pages.
- [ ] Add scheduled watchlists for searches and products.
- [ ] Add FastAPI service and dashboard.
- [ ] Add search/product quality scoring and sourcing analytics.
