# Repository Guidelines

## Project Structure & Module Organization
This repository is split into three main areas:

- `api/`: FastAPI backend, with route modules in `api/routes/` and shared services in `api/services/`.
- `simulator/`: scenario generation and seed scripts used to populate demo data.
- `frontend/`: Next.js App Router UI; page entrypoints live in `frontend/app/`, reusable UI in `frontend/app/components/`, and API helpers in `frontend/app/lib/`.
- `schema/`: SQL used to create database tables.
- `docker-compose.yml` and `demo.sh`: preferred local orchestration for SingleStore, API, and frontend.

## Build, Test, and Development Commands
- `./demo.sh`: boots SingleStore, applies `schema/create_tables.sql`, seeds data, and starts the full demo stack.
- `docker compose up --build`: rebuilds and starts all services defined in `docker-compose.yml`.
- `python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000`: runs the API locally from the repo root.
- `python -m simulator.seed`: reseeds demo data after the database schema exists.
- `cd frontend && npm install && npm run dev`: starts the Next.js app on `http://localhost:3000`.
- `cd frontend && npm run build` or `npm run lint`: validate production build and frontend linting.

## Coding Style & Naming Conventions
Use 4-space indentation in Python and follow PEP 8 with type hints where practical. Keep backend modules snake_case (`risk_scorer.py`) and React components PascalCase (`DisruptionCard.tsx`). Frontend code is TypeScript-first, uses ESLint via `frontend/eslint.config.mjs`, and currently follows the existing 2-space indentation and functional component style.

## Testing Guidelines
This snapshot does not include a dedicated automated test suite. Before opening a PR, at minimum run `npm run lint`, `npm run build`, start the API, and exercise the demo flow through `./demo.sh`. When adding tests, place frontend tests alongside the feature or under `frontend/__tests__/`, and place backend tests under a new `tests/` package with names like `test_health.py`.

## Commit & Pull Request Guidelines
Git history is not available in this workspace snapshot, so follow a conservative default: short, imperative commit subjects such as `Add disruption cost summary`. Keep commits scoped to one concern. PRs should include a clear summary, local verification steps, linked issue or ticket if applicable, and screenshots or short recordings for UI changes.

## Configuration & Data
Copy `.env.example` to `.env` before running the stack. Never commit secrets. Treat `schema/create_tables.sql` and simulator seed behavior as contract changes: update both intentionally when changing persisted data shapes.
