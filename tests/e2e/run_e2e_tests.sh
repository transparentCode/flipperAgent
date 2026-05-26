#!/usr/bin/env bash

set -e

# Configuration
COMPOSE_FILE="docker-compose.yml"
INGESTION_SCHEMA="src/apps/ingestion_app/storage/schema.sql"
PIPELINE_SCHEMA="sql/pipeline_schema.sql"

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

echo "=== Applying schemas ==="
cat $INGESTION_SCHEMA | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db
cat $PIPELINE_SCHEMA  | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db

echo "=== Starting all workers ==="
docker-compose up -d --build worker-streams worker-queue signal-worker strategy-worker risk-worker execution-worker portfolio-worker

echo "=== Waiting for workers to stabilize (15s) ==="
sleep 15

echo "=== Running E2E tests ==="
if .venv/bin/python -m pytest tests/e2e/test_docker_integration.py -v --timeout=300; then
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

exit $TEST_RESULT
