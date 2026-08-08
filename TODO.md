# TODO

## 0.5 production operations ✅

- [x] Add scoped API-key authentication and key lifecycle management.
- [x] Add explicit transactional schema migrations.
- [x] Add packaged systemd user/system service install, uninstall, and status commands.
- [x] Add authenticated health/readiness endpoints and Prometheus-style metrics.
- [x] Add request/error/latency/uptime/service telemetry.
- [x] Add richer product comparisons, price-history charts, category charts, and score distributions.
- [x] Add saved landed-cost scenarios.
- [x] Add category-specific scoring-profile bindings and persisted category scores.
- [x] Add configurable webhook alert sinks with signing, filters, delivery state, and retries.
- [x] Run recurring watchlists and alert delivery inside the long-running service.
- [x] Update version, README, CHANGELOG, TODO, roadmap, service docs, and operations docs.

## Next

- [ ] Add retry/error queue editing and targeted retry controls from the dashboard.
- [ ] Add API-key rotation helpers and optional short-lived service tokens.
- [ ] Add regional landed-cost presets while keeping every rate visible/editable.
- [ ] Add richer supplier-quality history and supplier comparison reports.
- [ ] Add configurable webhook exponential backoff/dead-letter retention.
- [ ] Add structured JSON logging and retention/rotation policies.
- [ ] Add backup/restore and SQLite integrity-check commands.
- [ ] Add optional TLS/reverse-proxy deployment examples.
- [ ] Add optional Playwright normal-browser rendering for JavaScript-only public pages.
- [ ] Add PostgreSQL only if telemetry shows SQLite is a measured bottleneck.
