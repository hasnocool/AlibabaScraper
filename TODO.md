# TODO

## 0.6 operational resilience ✅

- [x] Targeted failed-queue inspection and retry.
- [x] API-key rotation with grace periods.
- [x] Short-lived scoped API tokens.
- [x] Structured JSON logging and bounded retention.
- [x] SQLite online backup and integrity verification.
- [x] Guarded restore with safety backup and atomic replacement.
- [x] Exponential webhook retry/backoff and dead-letter queue.
- [x] Dead-letter inspection and operator requeue.
- [x] Supplier observed-data quality history.
- [x] TLS/reverse-proxy config generation for Caddy/Nginx.
- [x] FastAPI and CLI resilience controls.
- [x] Update version, README, CHANGELOG, TODO, roadmap, and operations docs.

## Next

- [ ] Add encrypted-at-rest secret storage for webhook signing secrets.
- [ ] Add backup retention/pruning policies and optional remote backup targets.
- [ ] Add restore rehearsal/scheduled backup verification jobs.
- [ ] Add audit-event persistence for administrative actions.
- [ ] Add structured retry classification (transient/permanent/parser/content errors).
- [ ] Add supplier quality profile customization and comparison thresholds.
- [ ] Add optional PostgreSQL adapter only after measured SQLite contention warrants it.
- [ ] Add optional Playwright rendering for public JavaScript-only pages.
