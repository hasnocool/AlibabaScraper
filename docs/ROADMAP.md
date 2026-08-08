# Roadmap

## 0.1 — Foundation ✅
Async client, normalized product model, CLI, tests, CI.

## 0.2 — Discovery + historical storage ✅
Real discovery, parsing, SQLite history, resumable crawl jobs.

## 0.3 — Data platform + sourcing intelligence ✅
Suppliers, exports, changes, watchlists, recurring recrawls, scoring.

## 0.4 — Service + dashboards ✅
FastAPI, browser/terminal dashboards, live task control, landed cost, profiles, alerts.

## 0.5 — Production operations ✅
Authentication, migrations, systemd, telemetry, comparisons, saved scenarios, category policies, external alert delivery.

## 0.6 — Operational resilience ✅

- Targeted failed-queue recovery.
- API-key rotation and short-lived tokens.
- Structured logs with bounded retention.
- SQLite backup/integrity/restore.
- Alert exponential retry and dead-letter queue.
- Supplier observed-data quality history.
- TLS/reverse-proxy deployment tooling.

## 0.7 — Audit + disaster recovery

- Administrative audit event history.
- Backup retention schedules and remote targets.
- Scheduled restore verification / disaster-recovery drills.
- Encrypted local secret storage.
- Retry classification and automatic transient/permanent error policy.

## 0.8 — Rendering + measured scale

- Optional normal-browser rendering for public JS-only pages.
- PostgreSQL only if SQLite is shown to be a bottleneck.
- Multi-worker coordination and distributed job leasing if workload requires it.

## Guardrails

Publicly accessible data only. Honor applicable terms, robots directives, rate limits, and access controls. Do not add CAPTCHA bypass, authentication bypass, fingerprint spoofing, or other anti-abuse circumvention.
