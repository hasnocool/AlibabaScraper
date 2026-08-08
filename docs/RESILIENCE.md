# Operational Resilience

## Failure model

v0.6 assumes failures will occur: remote requests time out, parser inputs change, webhook destinations go down, API keys need rotation, and local storage eventually needs recovery. The objective is to make each failure bounded, observable, and recoverable without replaying unrelated successful work.

## Crawl queue recovery

Only rows in `crawl_queue.status='error'` are eligible for targeted retry. Operators can filter by queue ID or an error substring. The operation uses `BEGIN IMMEDIATE` and refuses to proceed while the owning crawl job is `running`.

Selected rows return to `pending`; successful rows are never reset. The job returns to `pending` and can then be resumed through the normal pipeline.

## API credentials

Long-lived API keys remain opaque random values with only SHA-256 digests stored. Rotation creates a new key first, links old/new metadata, then either revokes the old key immediately or gives it a bounded overlap before expiry.

Short-lived tokens are the same opaque credential format with:

- `kind=token`
- parent key ID
- explicit expiration
- maximum TTL of 24 hours
- scopes that cannot exceed the parent key

This is intentionally simpler than adding JWT signing/key-distribution infrastructure to a local-first service.

## Alert backoff and dead letters

Every sink stores:

- `max_attempts`
- `base_backoff_seconds`
- `max_backoff_seconds`

Failed delivery delay is exponential and capped. Once the maximum number of attempts is reached the alert/sink delivery moves to `dead_letter` and is no longer automatically attempted. An operator can inspect and requeue it after correcting connectivity, credentials, or destination configuration.

## Database recovery

Online backups use SQLite's native backup API rather than copying a live WAL database file directly. Every produced backup is integrity checked and hashed.

Restore is deliberately CLI/operator controlled. The service should be stopped first. The candidate backup is verified, the current live DB is copied to a safety backup by default, the backup is restored into a temporary SQLite file and verified again, and only then is the target atomically replaced.

## Supplier quality history

Supplier quality is derived only from data observed by AlibabaScraper:

- average product sourcing score
- normalized field completeness
- count of tracked product changes over 30 days relative to observed catalog size
- observed catalog breadth

It is not a supplier trust, legal, safety, or financial rating. Each snapshot preserves all components for later trend inspection.

## Logs

Logs are JSON lines. Request bodies and authentication values are not intentionally logged. Rotating file retention prevents indefinite disk growth while systemd deployments can additionally retain the same stream in journald.

## TLS

The application server still defaults to loopback. TLS is terminated by a reverse proxy. Caddy output is intended for automatic HTTPS; Nginx output requires certificate paths supplied by the operator. Generated configs proxy to the loopback Uvicorn service and add baseline browser security headers.
