# Production Operations

## Bootstrap

```bash
alibaba-scraper migrate
alibaba-scraper api-key-create local-admin --scopes admin
alibaba-scraper service-install --user --env-file .env
alibaba-scraper service-status --user
```

## Routine checks

```bash
alibaba-scraper db-integrity
alibaba-scraper log-status
alibaba-scraper alert-dead-letters
alibaba-scraper supplier-quality
```

## Backups

```bash
alibaba-scraper db-backup
```

Keep backup files outside the live data directory when possible and copy verified backups to storage with a different failure domain.

## Restore

Stop the service, validate the backup, and only then restore:

```bash
systemctl --user stop alibaba-scraper.service
alibaba-scraper db-integrity --database /path/to/backup.sqlite3
alibaba-scraper db-restore /path/to/backup.sqlite3 --yes
systemctl --user start alibaba-scraper.service
```

A pre-restore safety backup is enabled by default.

## Key rotation

```bash
alibaba-scraper api-keys
alibaba-scraper api-key-rotate 1 --grace-minutes 15
```

Update clients to the newly returned key before the grace period expires.

For automation that does not need a long-lived secret:

```bash
alibaba-scraper token-mint 2 --ttl-minutes 30 --scopes read
```

## Failed crawl rows

```bash
alibaba-scraper queue-errors 12 --contains timeout
alibaba-scraper queue-retry 12 --queue-ids 44,47
alibaba-scraper resume 12
```

Do not retry queue rows while the job is running; the repository enforces this.

## Alert dead letters

```bash
alibaba-scraper alert-dead-letters
alibaba-scraper alert-dead-retry 8
```

Investigate the stored error before requeueing.

## Internet exposure

Keep `ALIBABA_SCRAPER_SERVICE_HOST=127.0.0.1`. Generate a TLS reverse-proxy configuration:

```bash
alibaba-scraper proxy-render caddy scraper.example.com --output Caddyfile
```

or:

```bash
alibaba-scraper proxy-render nginx scraper.example.com \
  --cert-file /etc/letsencrypt/live/scraper.example.com/fullchain.pem \
  --key-file /etc/letsencrypt/live/scraper.example.com/privkey.pem \
  --output alibaba-scraper.conf
```

API keys provide authentication/authorization; TLS protects those credentials and response data in transit.
