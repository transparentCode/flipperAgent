#!/usr/bin/env bash

set -e

# Configuration
COMPOSE_FILE="docker-compose.yml"
SCHEMA_FILE="src/flipper_agent/ingestion/storage/schema.sql"

echo "Bringing down any existing containers..."
docker-compose down -v

echo "Starting Docker containers..."
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

echo "Applying Database Schema..."
cat $SCHEMA_FILE | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db

echo "Starting Docker workers..."
docker-compose up -d --build worker-streams worker-queue

echo "Running E2E tests..."
if .venv/bin/python -m pytest tests/e2e/test_docker_integration.py -v; then
    echo "E2E tests passed."
    TEST_RESULT=0
else
    echo "E2E tests failed! Extracting logs:"
    docker-compose logs
    TEST_RESULT=1
fi

echo "Cleaning up..."
docker-compose down -v

exit $TEST_RESULT
