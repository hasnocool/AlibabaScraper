# Production Operations Guide

## 1. Upgrade and migrate

```bash
python -m pip install -e '.[dev]'
alibaba-scraper migrate
```

The service also runs the same migration function automatically at startup.

## 2. Create the first administrator key

```bash
alibaba-scraper api-key-create local-admin --scopes admin
```

Copy the returned `api_key` immediately. Only its hash is stored.

Additional least-privilege examples:

```bash
alibaba-scraper api-key-create dashboard-read --scopes read
alibaba-scraper api-key-create automation --scopes read,write --expires-days 90
alibaba-scraper api-keys
alibaba-scraper api-key-revoke 2
```

## 3. Configure `.env`

Start from `.env.example`. Important production values:

```env
ALIBABA_SCRAPER_DATABASE_PATH=data/alibaba.sqlite3
ALIBABA_SCRAPER_SERVICE_HOST=127.0.0.1
ALIBABA_SCRAPER_SERVICE_PORT=8787
ALIBABA_SCRAPER_AUTH_REQUIRED=true
ALIBABA_SCRAPER_WATCH_SCHEDULER_ENABLED=true
ALIBABA_SCRAPER_WATCH_SCHEDULER_POLL_SECONDS=60
ALIBABA_SCRAPER_ALERT_DISPATCH_INTERVAL_SECONDS=10
```

## 4. Install systemd service

For a normal per-user installation:

```bash
alibaba-scraper service-install --user --env-file .env
alibaba-scraper service-status --user
```

The installer writes `~/.config/systemd/user/alibaba-scraper.service`, reloads the user manager, enables the service, and restarts it unless `--no-start` is supplied.

System-wide installation is also supported but requires appropriate permissions:

```bash
sudo -E alibaba-scraper service-install --system --env-file /etc/alibaba-scraper.env
```

Remove the unit with:

```bash
alibaba-scraper service-uninstall --user
```

## 5. Health checks

Liveness:

```bash
curl http://127.0.0.1:8787/api/health/live
```

Authenticated health:

```bash
curl -H 'X-API-Key: abs_...' http://127.0.0.1:8787/api/health
```

Prometheus-style metrics:

```bash
curl -H 'X-API-Key: abs_...' http://127.0.0.1:8787/metrics
```

## 6. Category-specific scoring

Create scoring profiles with the existing profile commands, then bind categories:

```bash
alibaba-scraper profile-bind-category '*solar*' 2 --priority 200
alibaba-scraper profile-bind-category '*battery*' 3 --priority 150
alibaba-scraper profile-bindings
alibaba-scraper category-rescore
```

## 7. Saved landed-cost scenarios

```bash
alibaba-scraper landed-scenario-save '100-unit import' 12.50 100 \
  --currency CAD --shipping 180 --duty-pct 5 --tax-pct 12

alibaba-scraper landed-scenarios
```

## 8. External alert delivery

Configure a webhook:

```bash
alibaba-scraper alert-sink-add ops https://example.invalid/alibaba-alerts \
  --secret 'replace-me' \
  --event-kinds high_score,watchlist_change \
  --minimum-severity info
```

The service dispatcher handles delivery automatically. For an immediate manual delivery pass:

```bash
alibaba-scraper alert-deliver
```

When a sink secret is configured, requests include `X-AlibabaScraper-Signature: sha256=<hex>` over the exact JSON request body.

## 9. Dashboards

- Production operations: `http://127.0.0.1:8787/`
- Classic control dashboard: `http://127.0.0.1:8787/classic`
- OpenAPI: `http://127.0.0.1:8787/docs`

Enter an API key on the production dashboard first. It establishes an HttpOnly same-site session cookie for the browser dashboards.
