#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  NERVE — Autonomous Engine Startup"
echo "=========================================="

# Check for .env
if [ ! -f .env ]; then
    echo "[!] No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "[!] Please edit .env with your API keys, then re-run this script."
    exit 1
fi

# Source env for local commands
set -a; source .env; set +a

echo "[1/6] Starting SingleStore..."
docker compose up -d singlestore
echo "       Waiting for SingleStore to be healthy..."
until docker compose exec singlestore singlestore -p"${SINGLESTORE_PASSWORD:-password}" -e "SELECT 1" &>/dev/null; do
    sleep 2
    echo "       Still waiting..."
done
echo "       SingleStore is ready."

echo "[2/6] Creating schema..."
docker compose exec singlestore singlestore -p"${SINGLESTORE_PASSWORD:-password}" < schema/create_tables.sql
echo "       Schema created."

echo "[3/6] Seeding data..."
docker compose run --rm api python -m simulator.seed
echo "       Data seeded (10,000 shipments, 15 facilities, 50 historical disruptions)."

echo "[4/6] Creating S3 pipelines (if configured)..."
if [ -n "$S3_BUCKET_PATH" ] && [ -n "$AWS_ACCESS_KEY_ID" ]; then
    envsubst < schema/create_pipelines.sql | docker compose exec -T singlestore singlestore -p"${SINGLESTORE_PASSWORD:-password}"
    echo "       Pipelines created and started."
else
    echo "       Skipping (S3 not configured). Set S3_BUCKET_PATH and AWS credentials in .env to enable."
fi

echo "[5/6] Starting API and Frontend..."
docker compose up -d api frontend
sleep 3

echo "[6/6] Verifying..."
STATUS=$(curl -s http://localhost:8000/api/status || echo '{"error": "API not responding"}')
echo "       API Status: $STATUS"

echo ""
echo "=========================================="
echo "  NERVE is running in AUTONOMOUS mode!"
echo "=========================================="
echo ""
echo "  Console:    http://localhost:3000"
echo "  API:        http://localhost:8000/api/status"
echo "  Metrics:    http://localhost:8000/api/metrics"
echo "  API Docs:   http://localhost:8000/docs"
echo ""
echo "  The autonomous engine monitors for disruptions every ${AUTONOMOUS_LOOP_INTERVAL_SECONDS:-5}s."
echo "  Insert weather events into SingleStore (or via S3 pipeline)"
echo "  and watch NERVE detect, analyze, and resolve them automatically."
echo ""
