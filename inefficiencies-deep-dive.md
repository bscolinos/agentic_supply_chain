# NERVE Inefficiencies Deep Dive

## Goal

Document architectural and implementation inefficiencies in the current repo, separate from the demo-gimmick audit. This file focuses on avoidable work, redundant queries, unnecessary polling, and runtime patterns that will not scale cleanly.

## Executive Summary

The main inefficiency patterns are:

1. The frontend polls multiple endpoints on independent intervals while also reacting to WebSocket events.
2. The dashboard triggers per-card fetches, which creates N+1 network traffic as disruptions grow.
3. Several backend routes do multiple serial DB queries where the same response could be assembled with fewer round-trips.
4. Intervention execution performs many one-row writes in loops.
5. Risk scoring and disruption detection repeatedly rescan the same shipment population per weather event.
6. Some endpoints compute or fetch data that the frontend does not currently use.

## Findings

### 1. The dashboard combines polling and event-driven refreshes in a way that duplicates work [fixed]

Evidence:

- The main page polls `healthPulse()` and `disruptions()` every 5 seconds in [`frontend/app/page.tsx:118`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L118) through [`frontend/app/page.tsx:140`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L140).
- The same page also calls `refreshData()` again when disruption or intervention WebSocket events arrive in [`frontend/app/page.tsx:142`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L142) through [`frontend/app/page.tsx:151`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L151).

Impact:

- The page can refetch immediately after a WebSocket event and then refetch again on the next timer tick.
- As update frequency rises, the app does more work than necessary on both frontend and backend.

Recommendation:

- Pick a clearer strategy:
  - event-driven refresh for disruption-related state with periodic reconciliation, or
  - consolidated polling if WebSocket events are not trustworthy enough
- If both remain, debounce or coalesce refreshes.

### 2. The frontend uses multiple independent polling loops instead of a coordinated data model [fixed]

Evidence:

- Main page polls every 5 seconds in [`frontend/app/page.tsx:136`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L136).
- `MetricsBar` polls every 3 seconds in [`frontend/app/components/MetricsBar.tsx:71`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx#L71) through [`frontend/app/components/MetricsBar.tsx:75`](/Users/billscolinos/Documents/fedex/frontend/app/components/MetricsBar.tsx#L75).
- Every `InterventionPanel` instance polls every 5 seconds in [`frontend/app/components/InterventionPanel.tsx:50`](/Users/billscolinos/Documents/fedex/frontend/app/components/InterventionPanel.tsx#L50) through [`frontend/app/components/InterventionPanel.tsx:79`](/Users/billscolinos/Documents/fedex/frontend/app/components/InterventionPanel.tsx#L79).

Impact:

- The app does not have a single refresh cadence.
- As disruption count increases, each card adds another recurring polling loop.
- The backend receives a growing number of overlapping requests that could be consolidated.

Recommendation:

- Centralize polling or use a shared client-side cache/store.
- Move repeated per-disruption status fetches into a batched list response if the dashboard needs them all at once.

### 3. Disruption cards create an N+1 fetch pattern for explanations [fixed]

Evidence:

- Each `DisruptionCard` fetches `/api/explain/disruption/{id}` on mount in [`frontend/app/components/DisruptionCard.tsx:62`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L62) through [`frontend/app/components/DisruptionCard.tsx:99`](/Users/billscolinos/Documents/fedex/frontend/app/components/DisruptionCard.tsx#L99).

Impact:

- If 10 disruptions are visible, the page generates 10 additional explanation requests.
- Each explanation request itself performs multiple DB queries and potentially model work.
- This is expensive for initial page load and wasteful if many cards are off-screen or not being inspected.

Recommendation:

- Lazy-load explanations only when a card expands or is selected.
- Cache explanation responses by disruption ID.
- Consider returning a cheap summary in the disruption list route and reserving streaming explanation for detail views.

### 4. Each explanation request does multiple serial queries

Evidence:

- `/api/explain/disruption/{id}` performs:
  - one disruption query
  - one top-shipments query
  - one disruption-history query
- See [`api/routes/explain.py:16`](/Users/billscolinos/Documents/fedex/api/routes/explain.py#L16) through [`api/routes/explain.py:58`](/Users/billscolinos/Documents/fedex/api/routes/explain.py#L58).

Impact:

- Explanation generation latency includes three serial DB round-trips before any AI work begins.
- Under concurrent card loads, this compounds quickly.

Recommendation:

- Reassess which context is essential.
- Cache stable context like disruption history or precompute compact explanation context when a disruption is created.
- Avoid loading this route for every card automatically.

### 5. `health-pulse` duplicates work already done in `get_risk_summary()` [fixed]

Evidence:

- `get_risk_summary()` already computes active disruption count in [`api/services/risk_scorer.py:409`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L409) through [`api/services/risk_scorer.py:418`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L418).
- `health_pulse()` issues another active disruption count query in [`api/routes/health.py:30`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L30) through [`api/routes/health.py:34`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L34).

Impact:

- The same logical metric is counted twice on every health-pulse request.

Recommendation:

- Use the value already returned by `get_risk_summary()`, or move all health-pulse aggregation into one service function with a clear contract.

### 6. `health-pulse` returns data the dashboard does not use [fixed]

Evidence:

- `health_pulse()` fetches recent shipment events and active weather in [`api/routes/health.py:36`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L36) through [`api/routes/health.py:49`](/Users/billscolinos/Documents/fedex/api/routes/health.py#L49).
- The page stores the result in `health` but uses only `network_health`, `active_disruptions`, and `query_ms` in [`frontend/app/page.tsx:114`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L114) through [`frontend/app/page.tsx:211`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L211).
- The live event feed comes from WebSocket events, not `recent_events`.

Impact:

- Every `health-pulse` request pays for queries whose results are not rendered on the main page.

Recommendation:

- Split the route into smaller purpose-built endpoints, or stop querying unused sections until the UI needs them.

### 7. `get_risk_summary()` is four separate scans over `shipments` plus a fifth top-risk query

Evidence:

- Total in-transit count in [`api/services/risk_scorer.py:367`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L367).
- At-risk count in [`api/services/risk_scorer.py:378`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L378).
- Priority breakdown in [`api/services/risk_scorer.py:390`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L390).
- Active disruption count in [`api/services/risk_scorer.py:409`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L409).
- Top 5 highest risk shipments in [`api/services/risk_scorer.py:420`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L420).

Impact:

- The health path performs multiple separate aggregation queries against the same core table.
- This is acceptable for small demos, but not ideal for a live dashboard route that is polled repeatedly.

Recommendation:

- Consolidate compatible aggregates.
- Consider a materialized or periodically refreshed network summary if this page remains high-traffic.

### 8. Risk scoring rescans shipments once per active weather event [fixed]

Evidence:

- `score_shipments()` loops through each active weather event and runs a shipment lookup per event in [`api/services/risk_scorer.py:85`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L85) through [`api/services/risk_scorer.py:115`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L115).

Impact:

- If several weather events are active, the same shipment population can be scanned repeatedly.
- Shipments that intersect multiple facility sets can be evaluated multiple times and appended multiple times.

Recommendation:

- Rework scoring around a single joined candidate set or a precomputed facility-to-weather mapping.
- Decide how overlapping events should combine risk instead of overwriting shipment scores in repeated passes.

### 9. Risk scoring writes can update the same shipment multiple times in one cycle [fixed]

Evidence:

- `score_updates.append((score, shipment["shipment_id"]))` occurs inside the event loop in [`api/services/risk_scorer.py:132`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L132).
- The final batch update writes every collected pair without deduplicating shipment IDs in [`api/services/risk_scorer.py:150`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L150) through [`api/services/risk_scorer.py:170`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L170).

Impact:

- A shipment matched by more than one weather event can appear multiple times in the `CASE` statement.
- That inflates the SQL payload and makes the final score dependent on ordering rather than an explicit aggregation rule.

Recommendation:

- Deduplicate by shipment ID before writing.
- Define whether the final score should be max, sum-with-cap, or some other explicit combination.

### 10. Historical similarity is queried once per weather event [fixed]

Evidence:

- `_check_historical_similarity()` runs a DB query per event in [`api/services/risk_scorer.py:527`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L527) through [`api/services/risk_scorer.py:543`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L543).

Impact:

- Additional round-trips are added to each scoring cycle.
- The current query only returns a boolean-like count and could be cached or folded into broader event preparation.

Recommendation:

- Cache similarity lookups by `(weather_type, severity)` during the cycle.
- Or prefetch a set of qualifying combinations once.

### 11. Disruption detection rescans the same candidate shipment population multiple times per event [fixed]

Evidence:

- For each event, `detect_disruptions()` runs:
  - an existence check
  - an at-risk count by priority
  - an average risk query
  - an insert
  - a follow-up select to retrieve the inserted row
- See [`api/services/risk_scorer.py:219`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L219) through [`api/services/risk_scorer.py:332`](/Users/billscolinos/Documents/fedex/api/services/risk_scorer.py#L332).

Impact:

- The same facility-matched at-risk shipment subset is scanned at least twice per event.
- The insert-followed-by-select pattern adds another round-trip.

Recommendation:

- Consolidate count and average into one aggregation query where possible.
- Avoid re-selecting the inserted disruption if the required response fields are already known.

### 12. Intervention option generation uses extra round-trips per option [fixed]

Evidence:

- For each of three options, `generate_options()` performs one insert and then one select to fetch the inserted ID in [`api/services/intervention.py:186`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L186) through [`api/services/intervention.py:222`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L222).

Impact:

- Three logical options become six DB round-trips.

Recommendation:

- Use a safer batched insert/returning strategy if available.
- If the ID is not immediately necessary for all callers, return the options after a single follow-up read for the disruption.

### 13. Intervention execution is highly chatty against the database [fixed]

Evidence:

- `execute_intervention()` does multiple serial writes before rerouting even starts in [`api/services/intervention.py:297`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L297) through [`api/services/intervention.py:329`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L329).
- It then loops over rerouted shipments and performs:
  - one `UPDATE shipments`
  - one `INSERT shipment_events`
  for each shipment in [`api/services/intervention.py:356`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L356) through [`api/services/intervention.py:388`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L388).
- It then loops again to insert audit rows one by one in [`api/services/intervention.py:403`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L403) through [`api/services/intervention.py:411`](/Users/billscolinos/Documents/fedex/api/services/intervention.py#L411).

Impact:

- Large interventions can turn into many individual round-trips.
- Total latency grows linearly with shipment count.

Recommendation:

- Batch shipment updates where possible.
- Batch event inserts.
- Batch audit inserts.
- Wrap the workflow more explicitly as a transaction boundary if consistency matters.

### 14. Intervention-related frontend polling scales with disruption count [fixed]

Evidence:

- Every `InterventionPanel` polls `api.interventionStatus(disruptionId)` every 5 seconds in [`frontend/app/components/InterventionPanel.tsx:53`](/Users/billscolinos/Documents/fedex/frontend/app/components/InterventionPanel.tsx#L53) through [`frontend/app/components/InterventionPanel.tsx:78`](/Users/billscolinos/Documents/fedex/frontend/app/components/InterventionPanel.tsx#L78).

Impact:

- Ten visible disruptions means ten recurring status requests.
- Completed interventions may also trigger follow-up savings report fetches.

Recommendation:

- Move intervention summaries into the disruption list/detail payload when rendering many cards.
- Poll once at the page level or use event-driven updates for intervention state.

### 15. WebSocket state management stores an ever-changing array that drives broad rerenders [fixed]

Evidence:

- `useWebSocket()` prepends every event to state and keeps the last 100 in [`frontend/app/hooks/useWebSocket.ts:26`](/Users/billscolinos/Documents/fedex/frontend/app/hooks/useWebSocket.ts#L26) through [`frontend/app/hooks/useWebSocket.ts:30`](/Users/billscolinos/Documents/fedex/frontend/app/hooks/useWebSocket.ts#L30).
- The page listens to the full `wsEvents` array in its effect dependency in [`frontend/app/page.tsx:143`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L143).

Impact:

- Every new event changes the array identity and can trigger downstream work.
- The page only needs the latest relevant event to decide on refresh, but tracks the whole array for that effect.

Recommendation:

- Drive refresh behavior from `lastEvent` instead of the entire array.
- Keep the event list for display, but avoid coupling page-wide refresh logic to the list reference.

### 16. `health-pulse` and `disruptions` are fetched together, but the page still tolerates total failure silently [fixed]

Evidence:

- `Promise.all([api.healthPulse(), api.disruptions()])` is used in [`frontend/app/page.tsx:121`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L121).
- Any failure drops both results and is ignored in [`frontend/app/page.tsx:131`](/Users/billscolinos/Documents/fedex/frontend/app/page.tsx#L131).

Impact:

- One endpoint failure wastes the successful work from the other endpoint.
- The UI provides no degraded mode or partial rendering.

Recommendation:

- Fetch independently or use `Promise.allSettled()` if partial rendering is acceptable.
- This is both a resilience problem and an efficiency problem.

### 17. The DB layer commits after read queries [fixed]

Evidence:

- `get_connection()` commits after yielding regardless of whether the caller only read in [`api/services/db.py:137`](/Users/billscolinos/Documents/fedex/api/services/db.py#L137) through [`api/services/db.py:140`](/Users/billscolinos/Documents/fedex/api/services/db.py#L140).
- `_run_query()` uses that same context manager in [`api/services/db.py:182`](/Users/billscolinos/Documents/fedex/api/services/db.py#L182) through [`api/services/db.py:195`](/Users/billscolinos/Documents/fedex/api/services/db.py#L195).

Impact:

- It introduces unnecessary transaction finalization for plain reads.
- The overhead may be small per query, but this path is on every DB call.

Recommendation:

- Separate read and write transaction handling, or make read queries non-committing when supported cleanly.

### 18. The async wrappers exist, but many expensive routes still run synchronous DB calls directly in async handlers

Evidence:

- Async wrappers are defined in [`api/services/db.py:243`](/Users/billscolinos/Documents/fedex/api/services/db.py#L243) through [`api/services/db.py:256`](/Users/billscolinos/Documents/fedex/api/services/db.py#L256).
- Routes like `health_pulse()`, `list_disruptions()`, and `explain_disruption_endpoint()` call synchronous `db.execute_query()` directly from async handlers.

Impact:

- Blocking DB work occurs inside async route handlers.
- This can reduce concurrency under load, depending on driver behavior and deployment characteristics.

Recommendation:

- Either adopt the async wrappers consistently, or keep handlers synchronous where appropriate.
- Be explicit about the concurrency model instead of mixing both styles.

## Most Important Fixes First

1. Eliminate per-card explanation fetches on initial render.
2. Replace per-panel polling with batched or page-level intervention loading.
3. Consolidate `health-pulse` work and remove unused queried payload.
4. Reduce DB round-trips inside `execute_intervention()`.
5. Rework `score_shipments()` and `detect_disruptions()` to avoid repeated scans and duplicate shipment writes.
6. Use `lastEvent`-driven refresh logic instead of coupling page refreshes to the whole WebSocket event array.

## Bottom Line

The current repo is not inefficient because it uses Python or SQL. It is inefficient because the same state is fetched repeatedly at multiple layers, heavy work is triggered automatically per visual component, and backend workflows are decomposed into many small serial round-trips.

The fastest wins are:

- fewer polling loops
- fewer per-card requests
- fewer duplicated aggregation queries
- batched writes during intervention execution
- a more deliberate dashboard data model
