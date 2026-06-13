#!/usr/bin/env bash
# Usage: ./tests/e2e/run_e2e_tests.sh [--slow]
#   --slow: Include slow tests (organic candle, persistence)
#   Default: Skip slow tests for faster CI feedback

set -euo pipefail
SECONDS=0

# Configuration
COMPOSE_FILE="docker-compose.yml"
E2E_WAIT_ATTEMPTS="${E2E_WAIT_ATTEMPTS:-60}"
E2E_WAIT_DELAY_SECONDS="${E2E_WAIT_DELAY_SECONDS:-2}"
INGESTION_HEALTH_URL="${INGESTION_HEALTH_URL:-http://127.0.0.1:8002/health}"

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
else
  echo "Docker Compose CLI not found."
  exit 1
fi

compose() {
  "${DOCKER_COMPOSE[@]}" "$@"
}

wait_for_postgres() {
  echo "Waiting for PostgreSQL to be ready..."
  for ((i = 1; i <= E2E_WAIT_ATTEMPTS; i++)); do
    if compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD:-flipperpass}" db \
      pg_isready -U "${POSTGRES_USER:-flipper}" -h localhost >/dev/null; then
      echo "PostgreSQL is ready!"
      return 0
    fi
    echo "PostgreSQL not ready yet, waiting... (${i}/${E2E_WAIT_ATTEMPTS})"
    sleep "${E2E_WAIT_DELAY_SECONDS}"
  done
  echo "PostgreSQL did not become ready in time."
  return 1
}

wait_for_valkey() {
  echo "Waiting for Valkey (Broker) to be ready..."
  for ((i = 1; i <= E2E_WAIT_ATTEMPTS; i++)); do
    if compose exec -T broker redis-cli ping | grep -q "PONG"; then
      echo "Valkey is ready!"
      return 0
    fi
    echo "Valkey not ready yet, waiting... (${i}/${E2E_WAIT_ATTEMPTS})"
    sleep "${E2E_WAIT_DELAY_SECONDS}"
  done
  echo "Valkey did not become ready in time."
  return 1
}

wait_for_ingestion_health() {
  echo "Waiting for ingestion runtime health endpoint..."
  for ((i = 1; i <= E2E_WAIT_ATTEMPTS; i++)); do
    if PYTHONPATH=src .venv/bin/python - "$INGESTION_HEALTH_URL" <<'PY'
import json
import sys
from urllib import request

url = sys.argv[1]
try:
    with request.urlopen(url, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or payload.get("status") != "ok":
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
    then
      echo "Ingestion runtime is healthy!"
      return 0
    fi
    echo "Ingestion runtime not healthy yet, waiting... (${i}/${E2E_WAIT_ATTEMPTS})"
    sleep "${E2E_WAIT_DELAY_SECONDS}"
  done
  echo "Ingestion runtime did not become healthy in time."
  return 1
}

# Parse arguments
PYTEST_ARGS=(-v)
if PYTHONPATH=src .venv/bin/python -m pytest --help 2>/dev/null | grep -q -- "--timeout"; then
    PYTEST_ARGS+=(--timeout=300)
else
    echo "pytest-timeout plugin not available; running without --timeout"
fi
if [[ "${1:-}" != "--slow" ]]; then
    PYTEST_ARGS+=(-m "not slow")
fi

echo "=== E2E Test Run — $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="
echo "=== Tearing down previous run ==="
compose down -v

echo "=== Starting infrastructure ==="
compose up -d --build db broker
wait_for_postgres
wait_for_valkey

# Schemas auto-applied via docker-entrypoint-initdb.d volume mount
echo "=== Schema auto-applied via docker-entrypoint-initdb.d ==="

echo "=== Starting all workers ==="
compose up -d --build worker-streams worker-queue signal-worker strategy-worker risk-worker execution-worker portfolio-worker
wait_for_ingestion_health

echo "=== Running E2E tests ==="
if PYTHONPATH=src .venv/bin/python -m pytest tests/e2e "${PYTEST_ARGS[@]}"; then
    echo "E2E tests passed."
    TEST_RESULT=0
else
    echo "E2E tests FAILED! Dumping logs:"
    compose logs --tail=100 signal-worker
    compose logs --tail=100 strategy-worker
    compose logs --tail=100 risk-worker
    compose logs --tail=100 execution-worker
    compose logs --tail=100 portfolio-worker
    compose logs --tail=50 worker-streams
    compose logs --tail=50 worker-queue
    TEST_RESULT=1
fi

echo "=== Cleanup ==="
compose down -v

echo "Total E2E time: ${SECONDS}s"
exit $TEST_RESULT
