# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is NERVE

NERVE (Network Event Response & Visibility Engine) is an autonomous logistics disruption management system. It monitors a FedEx-like network in real time: weather events threaten shipments → the system auto-detects disruptions → generates AI-powered explanations via Claude → auto-selects the best intervention → executes reroutes — all without operator clicks. Data flows in via SingleStore Pipelines (S3) or direct inserts.

## Running the Project

### Full stack via Docker Compose
```bash
./demo.sh                          # One-shot: starts SingleStore, seeds data, launches API + frontend
docker compose up -d               # Start all services (assumes schema/seed already done)
docker compose down                # Stop everything
```

### Individual services (local dev)
```bash
# API (Python/FastAPI) — requires SingleStore running
source .venv/bin/activate
pip install -r api/requirements.txt
PYTHONPATH=/path/to/repo python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (Next.js 16 / React 19)
cd frontend && npm install && npm run dev    # http://localhost:3000

# Seed database
PYTHONPATH=/path/to/repo python -m simulator.seed

# Lint frontend
cd frontend && npm run lint
```

### Environment
Copy `.env.example` to `.env` and fill in API keys. SingleStore defaults work for the Docker dev setup. The API reads config from env vars via `python-dotenv`. Set `AUTONOMOUS_LOOP_INTERVAL_SECONDS` to control processing frequency (default 5s).

The `/api/query` "Ask NERVE" chat endpoint proxies to the **SingleStore Analyst API** via `httpx`. It requires two env vars: `ANALYST_API_URL` (base URL through `/{projectID}`, copied from Portal → "Copy Endpoint") and `ANALYST_API_KEY` (Bearer token from Portal → Analyst → Domain Settings → API Keys). Both are documented in `.env.example`.

## Architecture

**Three-service Docker Compose stack:**
- `singlestore` — SingleStore dev image (ports 3306/8080/9000), stores all data
- `api` — Python 3.13 FastAPI server on port 8000, serves `/api/*` routes + `/ws/events` WebSocket + autonomous background loop
- `frontend` — Next.js 16 app on port 3000, live operations dashboard with Tailwind CSS

**Backend layout (`api/`):**
- `main.py` — FastAPI app, lifespan (starts autonomous loop), CORS, WebSocket endpoint, route mounting. All routes are under `/api` prefix.
- `routes/` — FastAPI routers: `health` (includes `/api/metrics`), `disruptions`, `explain`, `interventions`, `query`
- `services/autonomous.py` — Core autonomous processing loop (asyncio background task). Every N seconds: scores shipments, detects disruptions, generates options, auto-selects best, executes intervention, broadcasts via WebSocket. Handles recovery of unhandled disruptions on restart.
- `services/db.py` — SingleStore connection pool (singleton `ConnectionPool`), retry logic, `Database` facade. All queries return `(list[dict], execution_time_ms)` tuples. Async wrappers (`async_execute_query`) run sync queries in thread executor.
- `services/ai_explainer.py` — Claude API integration (streaming). Has template fallback when AI is unavailable. Three prompt modes: disruption explanation, decision explanation, customer notification.
- `services/risk_scorer.py` — Rules-based risk scoring (0-100) combining weather severity, shipment priority, SLA urgency, and historical similarity. `detect_disruptions()` creates disruption records when conditions are met.
- `services/intervention.py` — Generates 3 intervention options (full reroute, priority-only reroute, hold and wait) with cost/savings math. `auto_select_best_option()` picks highest savings excluding hold_and_wait. `execute_intervention()` handles the full lifecycle: select → execute → reroute shipments → audit trail → complete.

**Simulator (`simulator/`):**
- `seed.py` — Deterministic seeder (RNG seed=42). Generates 15 facilities, 10K shipments, 50 historical disruption records with vector embeddings.

**Frontend (`frontend/app/`):**
- `page.tsx` — Main dashboard: event feed (left), metrics bar + disruption cards + read-only intervention panels (center), audit trail (right). Polls `/api/health-pulse` every 5s, refreshes on WebSocket events.
- `lib/api.ts` — API client with typed methods for all endpoints. `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` env vars.
- `hooks/useWebSocket.ts` — WebSocket hook for live event feed at `/ws/events`.
- `components/` — `MetricsBar` (animated counters polling `/api/metrics`), `EventFeed`, `DisruptionCard`, `InterventionPanel` (read-only, auto-fetches), `NLQuery`, `QueryBadge`, `CostTicker`

**Database (`schema/`):**
- `create_tables.sql` — SingleStore with both rowstore (shipments) and columnstore (shipment_events, weather_events) tables. `disruption_history` has a `VECTOR(1536)` column with `DOT_PRODUCT` vector index.
- `create_pipelines.sql` — S3 Pipeline definitions for real-time ingestion of shipment_events and weather_events from S3. Requires AWS credentials.
- Key tables: `facilities`, `shipments`, `shipment_events`, `weather_events`, `disruptions`, `interventions`, `audit_trail`, `disruption_history`
- All monetary values stored in cents (BIGINT)

## Coding Style

- Python: 4-space indentation, PEP 8, type hints where practical, snake_case module names
- TypeScript/React: 2-space indentation, functional components, PascalCase component filenames
- ESLint config at `frontend/eslint.config.mjs`; run `npm run build` to catch type errors

## Key Patterns

- The `Database` facade (`api/services/db.py`) is the only DB access path. Routes get it via `request.app.state.db`. It returns `(rows_as_dicts, execution_time_ms)` for reads and `(rows_affected, execution_time_ms)` for writes.
- WebSocket broadcast is stored on `app.state.broadcast` — the autonomous loop and routes call it to push real-time events to the frontend.
- AI calls always have template fallback — if Claude is unavailable (no key, timeout, rate limit), the system still works with structured data templates.
- The autonomous loop runs as an asyncio background task started in lifespan. It is the primary driver of disruption detection and resolution — no operator clicks needed.
- `auto_select_best_option()` picks the intervention with highest savings (excluding hold_and_wait unless it's the only option).
- The frontend is fully read-only for interventions — it polls and displays what the autonomous engine has done.
