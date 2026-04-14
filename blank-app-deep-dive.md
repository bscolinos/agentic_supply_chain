# Blank App Deep Dive

## Context

The app appeared blank after a SingleStore Cloud restart.

Important constraints:

- The app is not using Docker in this workflow.
- The app should not be using a local SingleStore cluster.
- The app process was not restarted.
- The SingleStore Cloud cluster was restarted.

## Core Observation

The frontend suppresses API failures aggressively. That means many distinct backend or transport failures collapse into the same visible symptom: a dashboard that looks blank or empty.

The initial render path is:

- The page polls `/api/health-pulse` and `/api/disruptions` together.
- If either request fails, the catch block does nothing.
- Metrics are fetched separately, and failures are also swallowed.
- HTTP helpers throw on any non-2xx response.

Relevant code:

- [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)
- [`frontend/app/components/MetricsBar.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx)
- [`frontend/app/lib/api.ts`](/Users/billscolinos/Documents/fedex/frontend/app/lib/api.ts)

## What The Dashboard Depends On

The first screenful of data depends on these backend routes:

- `/api/health-pulse`
- `/api/disruptions`
- `/api/metrics`

Those routes depend on these tables and fields being queryable:

- `shipments`
- `shipment_events`
- `disruptions`
- `weather_events`
- `facilities`

Relevant code:

- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)
- [`api/routes/disruptions.py`](/Users/billscolinos/Documents/fedex/api/routes/disruptions.py)
- [`api/services/risk_scorer.py`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py)

## High-Probability Failure Modes

### 1. API is running, but DB-backed endpoints are failing after the cloud restart

This is the strongest general explanation.

Why it fits:

- The frontend hides request failures.
- The health and disruption endpoints both require live DB queries.
- A DB error in either endpoint can make the page look empty.

Relevant code:

- [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)
- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)
- [`api/routes/disruptions.py`](/Users/billscolinos/Documents/fedex/api/routes/disruptions.py)

### 2. The app is connected to the right cluster, but the wrong logical database

The DB name is loaded from env and used directly by the DB client.

Why it fits:

- A connection can succeed while targeting an empty or incorrect database.
- This would produce empty or failing queries even if the cluster still contains the expected data elsewhere.

Relevant code:

- [`api/services/db.py`](/Users/billscolinos/Documents/fedex/api/services/db.py)
- [`/Users/billscolinos/Documents/fedex/.env`](/Users/billscolinos/Documents/fedex/.env)

### 3. The cluster came back, but required tables are missing or partially missing

This is not the same as “the schema is entirely gone.” A partial mismatch is enough to break the dashboard.

Why it fits:

- `health-pulse` depends on multiple tables in one route.
- Missing just one table such as `weather_events` or `shipment_events` can break the endpoint.

Relevant code:

- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)

### 4. The tables exist, but expected columns or values changed

Examples:

- missing `status`
- missing `risk_score`
- missing `event_timestamp`
- missing `is_active`
- changed status values
- malformed JSON in `affected_facilities`

Why it fits:

- The queries are not defensive.
- The risk summary and disruption logic assume specific schemas and values.

Relevant code:

- [`api/services/risk_scorer.py`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py)
- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)

### 5. The API’s reconnect behavior is not recovering cleanly in practice

The DB layer retries queries and invalidates thread-local connections, so in theory it should recover from a DB restart.

Why it still remains possible:

- connections are thread-local
- intermittent failures can appear across different request paths
- the selected database could still be wrong or unavailable after reconnect

Relevant code:

- [`api/services/db.py`](/Users/billscolinos/Documents/fedex/api/services/db.py)

## Frontend And Transport Possibilities

### 6. The frontend is pointing at the wrong API instance

All requests depend on `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000`.

Why it fits:

- If the frontend is targeting the wrong backend process, the UI symptom is identical.

Relevant code:

- [`frontend/app/lib/api.ts`](/Users/billscolinos/Documents/fedex/frontend/app/lib/api.ts)

### 7. HTTP is failing while WebSocket still works

The event feed uses WebSocket. The metrics and main dashboard cards use HTTP.

Why it fits:

- You can have a connected event feed and still have an empty main dashboard.
- That can make the app seem partially alive while core API routes are broken.

Relevant code:

- [`frontend/app/hooks/useWebSocket.ts`](/Users/billscolinos/Documents/fedex/frontend/app/hooks/useWebSocket.ts)
- [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)

### 8. Browser fetch failures or CORS issues are being swallowed

Why it fits:

- The frontend throws on any non-2xx response.
- The page catches and ignores those failures.

Relevant code:

- [`frontend/app/lib/api.ts`](/Users/billscolinos/Documents/fedex/frontend/app/lib/api.ts)
- [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)

## Data-State Possibilities That Are Not “Blank Database”

### 9. The database is populated, but the specific dashboard tables are empty

The app needs more than “some data.” It specifically needs:

- `shipments` for risk summary
- `shipment_events` for recent activity
- `disruptions` for disruption cards
- `weather_events` for active weather

Why it fits:

- A populated cluster can still produce an empty-feeling dashboard if those specific tables are empty.

Relevant code:

- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)
- [`api/services/risk_scorer.py`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py)

### 10. There are no active disruptions, but the app is otherwise functioning

This does not explain a truly blank page, but it can explain why disruption cards disappeared.

Why it fits:

- The page intentionally renders an all-clear state when there are zero disruptions.

Relevant code:

- [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)

### 11. `shipment_events` is empty while other core tables still have rows

Why it fits:

- The app would lose recent-event visibility and feel inactive even if shipments still exist.

Relevant code:

- [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)

## Lower-Probability Causes

### 12. API route shape drift

The route may be returning a structure the frontend no longer expects.

Why lower probability:

- The issue correlates with a cloud restart rather than a code change.

### 13. Background task interference

The app starts an autonomous loop and a demo event broadcaster at startup.

Why lower probability:

- These are not primary dependencies for the first dashboard render.
- They are not strong explanations for the main HTTP panels going empty.

Relevant code:

- [`api/main.py`](/Users/billscolinos/Documents/fedex/api/main.py)
- [`api/services/autonomous.py`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py)

### 14. AI explanation failures

Why lower probability:

- Explanation loading happens after disruption cards exist.
- A failure there should not blank the main dashboard.

Relevant code:

- [`frontend/app/components/DisruptionCard.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx)
- [`api/routes/explain.py`](/Users/billscolinos/Documents/fedex/api/routes/explain.py)

## What This Probably Is Not

- Pure CSS or layout collapse
- WebSocket failure alone
- AI explanation failure alone

Those do not line up well with the architecture of the first render path.

## Best Current Hypothesis

The highest-probability explanation is:

- the frontend is healthy
- the API process is reachable
- one or more DB-backed endpoints began failing or returning empty critical tables after the SingleStore Cloud restart
- the frontend masks that failure and leaves the page looking blank

This does not imply the entire database is gone. It only implies that the specific queries the app depends on are no longer succeeding against the expected data shape and database target.

## Recommended Verification Order

When ready to resume active investigation, verify in this order:

1. `GET /api/status`
2. `SELECT DATABASE()`
3. `SHOW TABLES`
4. row counts for:
   - `shipments`
   - `shipment_events`
   - `weather_events`
   - `disruptions`

This will separate:

- connectivity failure
- wrong-database failure
- partial-schema failure
- empty-critical-table failure

## Useful Follow-Up Improvements

These are product hardening items that would make this class of outage easier to diagnose next time:

- Show visible dashboard errors instead of swallowing fetch failures.
- Add a degraded-state banner when `/api/health-pulse` fails.
- Log the selected DB host and database in a user-visible health endpoint.
- Add a lightweight “dashboard prerequisites” endpoint that checks the presence of critical tables.
- Distinguish “no active disruptions” from “data unavailable.”
