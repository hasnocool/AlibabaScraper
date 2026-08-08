# TODO

## 0.4 control plane ✅

- [x] FastAPI service layer.
- [x] Web dashboard.
- [x] CLI dashboard mirroring the same data/control plane.
- [x] Live crawl start/resume/cancel controls.
- [x] Product browser and scoring filters.
- [x] Supplier browser.
- [x] Watchlist alert inbox.
- [x] Generic landed-cost calculator.
- [x] Configurable scoring profiles and profile-specific rescoring.
- [x] Update version, README, CHANGELOG, TODO, roadmap, and service docs.

## Next

- [ ] Add schema migrations instead of only `CREATE TABLE IF NOT EXISTS` initialization.
- [ ] Add API authentication before supporting non-localhost deployment.
- [ ] Add pagination metadata and richer product comparison views.
- [ ] Add pluggable alert delivery adapters after local alert acknowledgement is stable.
- [ ] Add regional landed-cost presets while keeping all rates visible/editable.
- [ ] Add service health metrics, crawl throughput, request latency, and queue depth charts.
- [ ] Add structured crawl retry/error controls from the dashboard.
- [ ] Add optional Playwright normal-browser rendering for JavaScript-only public pages.
- [ ] Add packaged systemd/service installer and process-health commands.
- [ ] Add PostgreSQL adapter only if SQLite becomes a measured bottleneck.
