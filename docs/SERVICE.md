# Service and Dashboard Architecture

## Purpose

v0.4 adds an operating/control layer above the existing crawler. The crawler remains responsible for collection and normalization; the service does not duplicate parser or persistence logic.

## Process model

```text
FastAPI
  |
  +-- Database ---------------- core product/crawl state
  +-- IntelligenceRepository -- suppliers, changes, watchlists, baseline scores
  +-- ControlRepository ------- profile scores, alerts, dashboard read models
  +-- AlibabaScraper ---------- bounded async network collection
  +-- RuntimeManager ---------- in-process crawl/watchlist asyncio tasks
```

FastAPI keeps these connections open for the process lifespan. Runtime tasks reuse them, while each repository retains its own write serialization.

## Live task behavior

Starting a crawl through the API:

1. creates a durable crawl job in SQLite;
2. schedules an asyncio task;
3. returns immediately with the runtime task key;
4. updates durable crawl/queue state as collection progresses;
5. computes active-profile scores after completion;
6. creates a high-score alert when candidates exceed the configured threshold.

Cancellation cancels the asyncio task, marks the durable crawl `cancelled`, and returns any `in_progress` queue rows to `pending`. The job can therefore be resumed later.

Runtime task state is intentionally in-process. Durable product/crawl/watchlist state remains in SQLite so a service restart does not lose collected data or resumability.

## Scoring profiles

Baseline scoring still computes the five normalized components. A profile stores relative weights and an alert threshold. `ControlRepository.rescore()` applies the chosen profile to persisted normalized products and stores results in `profile_scores`.

No Alibaba requests are made during profile rescoring.

## Alerts

The local alert inbox currently records:

- watchlist failures / partial failures;
- watchlist runs with field changes;
- high-scoring candidates produced by a crawl/watchlist run.

Alerts are stored in SQLite and can be acknowledged/read from both the web and CLI surfaces.

## Landed cost

The landed-cost calculator is deliberately transparent. The caller supplies currency, unit price, quantity, shipping, insurance, duty/tax rates, brokerage, packaging, and other fees. The application does not infer jurisdiction-specific customs rules.

## Web dashboard

The dashboard is served directly by FastAPI and uses lightweight embedded HTML/CSS/JavaScript. There is no Node/frontend build step. The UI calls the same API routes exposed through OpenAPI.

## CLI dashboard

The terminal dashboard loads the same underlying repositories and renders a compact monospaced view. `--watch` refreshes with `asyncio.sleep()`, so it does not use a blocking polling loop.

## Network exposure

The default bind address is `127.0.0.1`. The current service does not include user authentication. Keep it local unless you intentionally put an authenticated/TLS reverse proxy in front of it.
