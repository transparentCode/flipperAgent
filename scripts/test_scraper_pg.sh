#!/usr/bin/env bash
# Run tests/scraper against a throwaway PostgreSQL (TimescaleDB) so no
# database-gated test is skipped. Only ever touches the container "scraper-pgtest".
#
#   ./scripts/test_scraper_pg.sh [pytest args...]
#
# A healthy "scraper-pgtest" that is already running is reused and left running;
# a container this script starts itself is removed on exit.
set -euo pipefail

NAME="scraper-pgtest"
PORT="55432"
DB="scraper_test"
PASSWORD="pgtest"
IMAGE="timescale/timescaledb:latest-pg15"
URI="postgresql://postgres:${PASSWORD}@127.0.0.1:${PORT}/${DB}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STARTED=0

cleanup() {
  if [ "$STARTED" = "1" ]; then
    docker rm -f "$NAME" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ready() {
  docker exec "$NAME" pg_isready -U postgres -d "$DB" -q >/dev/null 2>&1
}

if [ "$(docker ps -q --filter "name=^${NAME}$")" != "" ]; then
  echo "reusing the running ${NAME} container"
else
  # A stopped leftover of the same name is ours to replace; nothing else is touched.
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:5432" \
    -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_DB="$DB" "$IMAGE" >/dev/null
  STARTED=1
fi

for _ in $(seq 1 60); do
  if ready; then break; fi
  sleep 1
done
if ! ready; then
  echo "${NAME} did not become ready" >&2
  exit 1
fi
# The first start restarts the server once after initialisation; confirm it stays up.
sleep 2
ready || { echo "${NAME} is not stable" >&2; exit 1; }

cd "$ROOT"
SCRAPER_TEST_POSTGRES_URI="$URI" SCRAPER_REQUIRE_PG=1 \
  .venv/bin/python -m pytest tests/scraper -q -p no:cacheprovider "$@"
