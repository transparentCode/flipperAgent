#!/usr/bin/env bash
# Usage: ./tests/e2e/run_e2e_tests.sh [--slow]
#   --slow: Include slow tests (organic candle, persistence)
#   Default: Skip slow tests for faster CI feedback

set -euo pipefail
SECONDS=0

# Configuration
COMPOSE_FILE="docker-compose.yml"

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
docker-compose down -v

echo "=== Starting infrastructure ==="
docker-compose up -d --build db broker

echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
  if docker-compose exec -T -e PGPASSWORD=flipperpass db pg_isready -U flipper -h localhost; then
    echo "PostgreSQL is ready!"
    break
  fi
  echo "PostgreSQL not ready yet, waiting... ($i/30)"
  sleep 2
done

# Wait for Valkey (Redis compatible) to be ready
echo "Waiting for Valkey (Broker) to be ready..."
for i in {1..30}; do
  if docker-compose exec -T broker redis-cli ping | grep -q "PONG"; then
    echo "Valkey is ready!"
    break
  fi
  echo "Valkey not ready yet, waiting... ($i/30)"
  sleep 2
done

# Schemas auto-applied via docker-entrypoint-initdb.d volume mount
echo "=== Schema auto-applied via docker-entrypoint-initdb.d ==="

echo "=== Starting all workers ==="
docker-compose up -d --build worker-streams worker-queue signal-worker strategy-worker risk-worker execution-worker portfolio-worker

echo "=== Waiting for workers to stabilize (15s) ==="
sleep 15

echo "=== Running E2E tests ==="
if PYTHONPATH=src .venv/bin/python -m pytest tests/e2e "${PYTEST_ARGS[@]}"; then
    echo "E2E tests passed."
    TEST_RESULT=0
else
    echo "E2E tests FAILED! Dumping logs:"
    docker-compose logs --tail=100 signal-worker
    docker-compose logs --tail=100 strategy-worker
    docker-compose logs --tail=100 risk-worker
    docker-compose logs --tail=100 execution-worker
    docker-compose logs --tail=100 portfolio-worker
    docker-compose logs --tail=50 worker-streams
    docker-compose logs --tail=50 worker-queue
    TEST_RESULT=1
fi

echo "=== Cleanup ==="
docker-compose down -v

echo "Total E2E time: ${SECONDS}s"
exit $TEST_RESULT
