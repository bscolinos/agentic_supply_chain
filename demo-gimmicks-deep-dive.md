# NERVE Demo Gimmicks Deep Dive

## Goal

Document everything in the current repo that appears to have been added or altered to make the demo look alive, but which breaks the product requirement that runtime behavior be driven by the database and real query flows.

This file does not propose code changes yet. It is a remediation map.

## Executive Summary

The repo still has a workable core shape:

- SingleStore is the primary system of record.
- FastAPI owns the data and decisioning APIs.
- The frontend polls backend endpoints and listens to a WebSocket feed.
- Seed and S3 generator scripts are acceptable as demo-data bootstrap tools if they only populate the database.

The main regressions are runtime shortcuts:

1. The autonomous engine is effectively disabled and replaced with fake WebSocket traffic.
2. The chat experience is mocked twice: once in the frontend and again in the backend with canned keyword routes and a generic fallback summary.
3. Several dashboard numbers and audit entries are fabricated in the frontend instead of using backend data.
4. The metrics endpoint returns drifting synthetic values rather than DB-derived values.
5. Some frontend logic actively hides real disruptions or substitutes deterministic fake counts.

## Intended Architecture vs Current Runtime

### Intended DB-backed flow

1. Seed or ingest data into SingleStore tables in [`schema/create_tables.sql`](/Users/billscolinos/Documents/fedex/schema/create_tables.sql).
2. API reads and writes those tables through [`api/services/db.py`](/Users/billscolinos/Documents/fedex/api/services/db.py).
3. Risk scoring and disruption detection derive state from `shipments`, `shipment_events`, `weather_events`, `disruptions`, `interventions`, and `audit_trail`.
4. Frontend renders API responses and WebSocket events that correspond to persisted or queryable state.
5. Chat sends a real NL request to the backend, which translates it to a real analyst or SQL workflow, then returns actual query results.

### Current runtime flow

1. API startup launches a fake event broadcaster in addition to the real app lifecycle in [`api/main.py:13`](/Users/billscolinos/Documents/fedex/api/main.py#L13) and [`api/main.py:40`](/Users/billscolinos/Documents/fedex/api/main.py#L40).
2. The autonomous loop itself does nothing except sleep in [`api/services/autonomous.py:27`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py#L27) through [`api/services/autonomous.py:42`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py#L42).
3. The WebSocket feed is populated by random in-memory events in [`api/services/autonomous.py:224`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py#L224).
4. The frontend `Ask NERVE` component never calls the backend and instead generates hardcoded results locally in [`frontend/app/components/NLQuery.tsx:32`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx#L32) and [`frontend/app/components/NLQuery.tsx:125`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx#L125).
5. Even if the frontend were wired back up, the backend `/api/query` route still intercepts prompts with canned SQL and falls back to a generic summary in [`api/routes/query.py:30`](/Users/billscolinos/Documents/fedex/api/routes/query.py#L30) and [`api/routes/query.py:270`](/Users/billscolinos/Documents/fedex/api/routes/query.py#L270).
6. Several dashboard widgets display deterministic or drifting fake numbers instead of API fields.

## Findings

### 1. Autonomous processing is disabled at runtime

Evidence:

- [`api/services/autonomous.py:40`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py#L40) explicitly says demo mode skips real processing.
- `_run_cycle()` contains the real logic, but `autonomous_loop()` never calls it.

Impact:

- No automatic scoring, disruption detection, intervention generation, or intervention execution is occurring during normal app runtime.
- The UI can appear active while the actual logistics state in the database is stale.

What needs to change:

- Restore `autonomous_loop()` so it actually runs `_run_cycle()` on an interval.
- The system should remain autonomous by default. runtime path must mutate DB state rather than just emit visuals.

### 2. WebSocket activity is fake

Evidence:

- Startup launches `demo_event_broadcaster()` in [`api/main.py:41`](/Users/billscolinos/Documents/fedex/api/main.py#L41).
- `demo_event_broadcaster()` randomly invents shipment IDs, tracking numbers, facilities, intervention descriptions, and savings values in [`api/services/autonomous.py:224`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py#L224).

Impact:

- The live event feed is not a trustworthy view of `shipment_events`, `disruptions`, or `interventions`.
- Users can see events for shipments that do not correspond to actual DB changes.
- The UI can imply interventions happened when no intervention row changed.

What needs to change:

- Remove the fake broadcaster from startup.
- Emit WebSocket messages only when a DB-backed action occurs.
- Prefer broadcasting from the same code path that persists the event or state change.
- Consider backfilling the event feed from `shipment_events` and `audit_trail` instead of relying on ephemeral WebSocket-only narratives.

### 3. Frontend chat is completely mocked

Evidence:

- `buildDemoResults()` hardcodes answers for a few prompts in [`frontend/app/components/NLQuery.tsx:32`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx#L32).
- `send()` waits 250ms and appends local fake results without any network call in [`frontend/app/components/NLQuery.tsx:125`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx#L125).
- The header literally labels the feature as demo mode in [`frontend/app/components/NLQuery.tsx:170`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx#L170).

Impact:

- `Ask NERVE` is not querying the backend at all.
- The feature does not reflect the DB, the analyst service, or the current state of the network.

What needs to change:

- Replace the local `buildDemoResults()` path with a real POST to either [`frontend/app/api/analyst/route.ts`](/Users/billscolinos/Documents/fedex/frontend/app/api/analyst/route.ts) or direct backend API helpers.
- Remove demo-mode copy from the UI.
- The implementation guide is located in Analyst-API-Customer-Guide.md and the env variables are set in .env

### 4. Backend chat is also canned

Evidence:

- `_CANNED` keyword matching is defined in [`api/routes/query.py:30`](/Users/billscolinos/Documents/fedex/api/routes/query.py#L30).
- `/api/query` checks canned matches before doing anything else in [`api/routes/query.py:280`](/Users/billscolinos/Documents/fedex/api/routes/query.py#L280).
- Unmatched prompts are forced into the same fallback disruption summary in [`api/routes/query.py:299`](/Users/billscolinos/Documents/fedex/api/routes/query.py#L299).

Impact:

- Even if the frontend is reconnected, the backend still does not provide open-ended query behavior.
- The chat system is currently not a genuine NL interface. It is a fixed decision tree over a handful of reports.
- User trust is damaged because unrelated questions still return a plausible-looking answer.

What needs to change:

- Remove `_CANNED`, `_match_canned()`, `_run_canned()`, and the fallback-summary behavior from the runtime path.
- Keep the `/analyst/chat` workaround if it is still required, but make it the real path for all prompts.
- Return a failure or clear “query could not be answered” state when analyst translation fails. Do not substitute a generic disruption summary for arbitrary user intent.
- If analyst reliability remains an issue, build a proper SQL-generation and validation pipeline, not keyword canned answers.

### 5. Dashboard metrics endpoint returns synthetic values

Evidence:

- `_DEMO_START`, `_DEMO_SAVINGS_BASE`, `_DEMO_REROUTED_BASE`, and `_DEMO_EPM_BASE` are declared in [`api/routes/health.py:13`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L13).
- `/api/metrics` manufactures `savings`, `rerouted`, and `epm` from elapsed time and random jitter in [`api/routes/health.py:80`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L80).

Impact:

- The metrics bar cannot be trusted.
- Dashboard totals drift upward even if nothing happens in the database.

What needs to change:

- Recompute metrics from real persisted state:
  - total savings from completed interventions
  - shipments rerouted from `shipment_events` or a dedicated intervention outcome table
  - events per minute from `shipment_events`
  - completed intervention count from `interventions`
- If some business metrics are not derivable from current schema, add explicit persisted fields rather than synthesizing them in the route.

### 6. Metrics bar ignores the backend `events_per_minute`

Evidence:

- `DEMO_EVENTS_PER_MINUTE = 11996` in [`frontend/app/components/MetricsBar.tsx:14`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx#L14).
- The component uses that constant instead of the API response in [`frontend/app/components/MetricsBar.tsx:80`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx#L80).

Impact:

- Even a fixed backend metrics route would still not display the real events-per-minute number.

What needs to change:

- Use `metrics?.events_per_minute`.
- Decide whether animated counters are acceptable for presentation. Animation is fine; fake values are not.

### 7. Disruption cards display fake shipment counts

Evidence:

- `getDisplayCounts()` invents `shipmentsAtRisk` and `criticalHealthcare` from the disruption ID in [`frontend/app/components/DisruptionCard.tsx:46`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L46).
- Those fake values are rendered instead of `affected_shipment_count` and `critical_shipment_count` in [`frontend/app/components/DisruptionCard.tsx:142`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L142).
- The explanation fallback also uses the fake counts in [`frontend/app/components/DisruptionCard.tsx:91`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L91).

Impact:

- The primary disruption card numbers shown to the user are not DB-backed.

What needs to change:

- Replace `getDisplayCounts()` usage with the actual disruption fields from the API.
- If the API’s disruption summary is insufficient, extend the backend response rather than synthesizing frontend counts.

### 8. Audit trail shown on the right rail is entirely fabricated

Evidence:

- `buildDemoAuditTrail()` constructs three hardcoded narrative entries in [`frontend/app/page.tsx:91`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L91).
- The `AuditTrail` component uses only that local function in [`frontend/app/page.tsx:315`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L315).
- The backend already exposes real audit trail data on disruption detail and intervention status routes, but the dashboard is not using it.

Impact:

- The dashboard implies actions happened that may never have been persisted.
- This is one of the clearest “demo theater” paths in the repo.

What needs to change:

- Replace the right-rail audit view with real `audit_trail` entries from the backend.
- Either:
  - fetch detailed disruption data for visible disruptions, or
  - add a lightweight list endpoint for audit summaries.

### 9. A real disruption can be hidden by a UI-only special case

Evidence:

- `shouldHideDisruption()` removes `Heat Dome` in `Gulf Coast` in [`frontend/app/page.tsx:72`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L72).

Impact:

- The frontend can suppress a legitimate disruption record from the database.
- This is incompatible with “all data flows should be tied to the DB.”

What needs to change:

- Remove this filter.
- If a particular disruption type was noisy or undesirable during the demo, fix that at the data generation or business-rule layer, not in the UI render path.

### 10. Cost-of-inaction ticker is synthetic

Evidence:

- [`frontend/app/components/CostTicker.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/CostTicker.tsx) increments cost locally over time based on `estimated_cost_cents / 3600`, independent of database updates.

Impact:

- Users see a live-growing loss figure that is not persisted or recalculated anywhere.

What needs to change:

- Either remove the live ticker entirely, or back it with a real backend metric.
- If the product needs dynamic exposure growth, it should be computed on the server from a documented model and returned explicitly.

### 11. Disruption explanation fallback can still show fabricated counts

Evidence:

- On fetch failure, `DisruptionCard` falls back to a template using `displayCounts`, not DB counts, in [`frontend/app/components/DisruptionCard.tsx:91`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L91).

Impact:

- The user can receive a fake narrative precisely when the real explanation path is unavailable.

What needs to change:

- Fallback narratives must be built from known DB-backed fields already on the page.
- If explanation streaming fails, render a minimal non-fabricated summary instead of invented counts.

### 12. Health pulse query timing is partially fake

Evidence:

- `risk_summary_ms` is hardcoded to `0` in [`api/routes/health.py:66`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L66).

Impact:

- Latency instrumentation is inconsistent and partially decorative.

What needs to change:

- Either measure the risk-summary computation time properly or remove the field.

### 13. Intervention execution persists some results, but the audit narrative is still synthetic and the shipment mutation is minimal

Evidence:

- Intervention generation and execution are DB-backed in [`api/services/intervention.py`](/Users/billscolinos/Documents/fedex/api/services/intervention.py).
- But execution currently:
  - updates ETA
  - inserts a `reroute` shipment event
  - writes a canned sequence of audit entries spaced by a few seconds
- See the synthetic audit sequence around [`api/services/intervention.py:394`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L394).

Impact:

- This area is closer to “real” than the frontend gimmicks, but still carries demo-oriented simplifications.
- Audit entries are not driven by actual step completion; they are a scripted narrative.
- Reroute does not appear to update routing/facility state beyond ETA and an event record.

What needs to change:

- Decide what “fully functional” means for intervention execution:
  - update shipment route state
  - update facility assignment or alternate path fields
  - create notifications from actual rerouted shipments
  - only write audit rows for real completed steps
- If the current schema is too thin to represent reroute state, add the required tables/columns.

### 14. The frontend still contains demo/autonomous framing that may no longer match real behavior

Evidence:

- `AUTONOMOUS` badge in [`frontend/app/page.tsx:179`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L179).
- “The autonomous engine is monitoring all shipments in real time” empty-state copy in [`frontend/app/page.tsx:264`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L264).
- Footer copy references autonomous engine in [`frontend/app/page.tsx:305`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L305).
- `demo.sh` still advertises autonomous mode in [`demo.sh`](/Users/billscolinos/Documents/fedex/demo.sh).

Impact:

- Product messaging currently overstates what the system actually does.

What needs to change:

- Update labels only after the runtime behavior is corrected.
- If autonomy remains a feature, it should describe a real DB-backed engine, not a presentation mode.

## What Looks Acceptable vs What Should Be Removed

### Acceptable if kept clearly as bootstrap/test data generation

- [`simulator/seed.py`](/Users/billscolinos/Documents/fedex/simulator/seed.py)
- [`simulator/s3_data_gen.py`](/Users/billscolinos/Documents/fedex/simulator/s3_data_gen.py)

Reason:

- These are allowed to create demo or synthetic data if they write into the database and the app then reads that data normally.
- Synthetic seed data is not the problem. Runtime fabrication outside the DB is the problem.

### Should be removed or reworked because they bypass the DB/runtime truth

- Fake runtime WebSocket broadcaster in [`api/services/autonomous.py`](/Users/billscolinos/Documents/fedex/api/services/autonomous.py)
- Canned NL query backend in [`api/routes/query.py`](/Users/billscolinos/Documents/fedex/api/routes/query.py)
- Mocked chat UI in [`frontend/app/components/NLQuery.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/NLQuery.tsx)
- Fake metrics in [`api/routes/health.py`](/Users/billscolinos/Documents/fedex/api/routes/health.py)
- Fake metrics rendering in [`frontend/app/components/MetricsBar.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx)
- Fake disruption counts in [`frontend/app/components/DisruptionCard.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx)
- Fake audit trail and disruption suppression in [`frontend/app/page.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx)
- Synthetic cost ticker in [`frontend/app/components/CostTicker.tsx`](/Users/billscolinos/Documents/fedex/frontend/app/components/CostTicker.tsx)

## Recommended Remediation Order

### Phase 1: Remove fake runtime behavior

1. Remove startup wiring for `demo_event_broadcaster()`.
2. Restore real autonomous loop execution or explicitly disable autonomy without fake events.
3. Remove frontend-mocked `Ask NERVE`.
4. Remove backend canned query logic and fallback-summary behavior.
5. Remove UI-only disruption hiding and fake count generation.

### Phase 2: Reconnect UI to real backend state

1. Make `NLQuery` call the real backend.
2. Make right-rail audit content read real `audit_trail` rows.
3. Make disruption cards use returned disruption counts.
4. Make metrics bar use fully DB-backed metrics.
5. Replace synthetic “cost of inaction” with a documented backend field or remove it.

### Phase 3: Tighten domain correctness

1. Define actual reroute state transitions for shipments.
2. Ensure intervention execution changes persistent shipment/network state, not just ETA and narrative events.
3. Revisit schema if needed to support alternate routes, notification delivery records, and intervention outcomes.
4. Decide whether AI explanation fallback should exist, and if so ensure it is only built from persisted data.

## Open Questions Before Implementation

- Should the product remain autonomous by default, or should interventions become operator-approved?
- Should `Ask NERVE` depend on SingleStore Analyst only, or is there a separate approved fallback path when analyst translation fails?
- Is `shipment_events` intended to be the sole source of truth for the live event feed, or should there be a dedicated app event table/outbox?
- Do reroutes need actual route modeling, or is changing ETA plus recording an intervention sufficient for the next version?
- Should demo seed/generator scripts remain in-repo for local development, or be separated from the main product workflow?

## Bottom Line

The biggest issue is not that the repo uses synthetic data. The biggest issue is that multiple runtime paths now bypass the database and generate plausible-looking activity locally or in-memory.

To make the system fully functional again:

- all dashboard numbers must come from persisted or query-derived state
- the WebSocket feed must reflect actual DB-backed events
- `Ask NERVE` must submit real backend queries
- arbitrary prompts must not fall back to canned summaries
- UI render paths must stop inventing shipment counts, audit entries, and filtered disruptions
