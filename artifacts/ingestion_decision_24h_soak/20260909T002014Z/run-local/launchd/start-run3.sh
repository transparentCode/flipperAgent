#!/bin/zsh
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RUN3_ROOT="/Users/kajukatli/projects/flipperAgent"
RUN3_ID="20260909T002014Z"
RUN3_DIR="$RUN3_ROOT/artifacts/ingestion_decision_24h_soak/$RUN3_ID"
RUN3_PROJECT="flipper-id-soak-20260909t002014z"
RUN3_LOCAL="$RUN3_DIR/run-local"
RUN3_COMPOSE="$RUN3_LOCAL/soak-compose.override.yml"
RUN3_SOURCE="$RUN3_LOCAL/source"
RUN3_CONFIG="$RUN3_SOURCE/configs/ingestion/global.yaml"
RUN3_PYTHON="/Users/kajukatli/projects/flipperAgent/.venv/bin/python"

if [[ ! -x "$RUN3_PYTHON" ]]; then
  for RUN3_CANDIDATE in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [[ -x "$RUN3_CANDIDATE" ]]; then
      RUN3_PYTHON="$RUN3_CANDIDATE"
      break
    fi
  done
fi
[[ -x "$RUN3_PYTHON" ]] || exit 78

[[ -f "$RUN3_CONFIG" ]] || { print -u2 "missing frozen ingestion config"; exit 66; }

RUN3_RECOVERY_DAYS=$("$RUN3_PYTHON" - "$RUN3_CONFIG" <<'PY'
import sys

try:
    import yaml
except ImportError as exc:
    raise SystemExit(f"PyYAML is required to read frozen config: {exc}")

with open(sys.argv[1], encoding="utf-8") as stream:
    document = yaml.safe_load(stream)

ingestion = document.get("ingestion") if isinstance(document, dict) else None
base_timeframe = ingestion.get("base_timeframe") if isinstance(ingestion, dict) else None
retention = ingestion.get("retention") if isinstance(ingestion, dict) else None
days = retention.get("candle_days") if isinstance(retention, dict) else None
if base_timeframe != "1m":
    raise SystemExit(f"unexpected frozen recovery base timeframe: {base_timeframe!r}")
if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
    raise SystemExit("frozen ingestion retention.candle_days must be a positive integer")
print(days)
PY
)

RUN3_PREPARATION_TIMEOUT_SECONDS=7200
RUN3_DEADLINE=$(( $(date +%s) + RUN3_PREPARATION_TIMEOUT_SECONDS ))

# All startup Docker CLIs share the preparation deadline. Output streams to
# the caller; the helper owns and reaps CLI/plugin descendants on termination.
docker() {
  "$RUN3_PYTHON" "$RUN3_LOCAL/bounded_command.py" \
    --timeout 180 --deadline "$RUN3_DEADLINE" -- /usr/bin/env docker "$@"
}

run3_remaining_seconds() {
  local remaining=$(( RUN3_DEADLINE - $(date +%s) ))
  (( remaining > 0 )) || return 1
  print "$remaining"
}

validate_recovery_response() {
  "$RUN3_PYTHON" -c '
import json
import sys

try:
    value = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)
if not isinstance(value, dict):
    raise SystemExit(1)
if value.get("desired_state") != "running":
    raise SystemExit(1)
# An asynchronously scheduled replacement supervisor can acknowledge STOPPED
# before its first turn. The separate LIVE gate below is still mandatory.
if value.get("state") not in {"stopped", "starting", "live", "recovering"}:
    raise SystemExit(1)
if "last_error" not in value or value["last_error"] is not None:
    raise SystemExit(1)
if isinstance(value.get("enabled_asset_count"), bool) or not isinstance(value.get("enabled_asset_count"), int):
    raise SystemExit(1)
if value["enabled_asset_count"] < 1:
    raise SystemExit(1)
'
}

validate_live_runtime() {
  "$RUN3_PYTHON" -c '
import json
import sys

try:
    value = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)
if not isinstance(value, dict) or value.get("state") != "live":
    raise SystemExit(1)
if value.get("desired_state") != "running" or value.get("last_error") is not None:
    raise SystemExit(1)
'
}

cd "$RUN3_ROOT"

# Ingestion owns canonical history recovery. Decision is created only after
# Ingestion reaches LIVE, its recovery path completes, and required streams are
# published. This is run-local lifecycle ordering only.
docker compose -p "$RUN3_PROJECT" \
  -f "$RUN3_COMPOSE" \
  --profile prod up -d \
  db broker ingestion

RUN3_DB_CONTAINER="${RUN3_PROJECT}-db-1"
RUN3_BROKER_CONTAINER="${RUN3_PROJECT}-broker-1"
RUN3_STREAM_KEYS=(
  "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
  "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h"
  "stream:ohlcv:ingestion:binance:ETH-USDT-PERP:4h"
)
RUN3_RECOVERY_SINCE="$(date -u -v-${RUN3_RECOVERY_DAYS}d '+%Y-%m-%dT%H:%M:00Z')"
RUN3_RECOVERY_UNTIL="$(date -u '+%Y-%m-%dT%H:%M:00Z')"
RUN3_ZERO_OUTBOX_STREAK=0

# The runtime only reports LIVE after a closed provider observation has been
# committed.  History repair must therefore be initiated from readiness, not
# gated on LIVE; otherwise startup can wait forever for the very recovery this
# script is responsible for requesting.
while true; do
  if [[ "$(date +%s)" -ge "$RUN3_DEADLINE" ]]; then
    print -u2 "Ingestion did not become ready before the startup deadline"
    exit 1
  fi
  if curl -fsS --max-time 10 http://127.0.0.1:8003/health/ready >/dev/null 2>&1; then
    break
  fi
  sleep 15
done

for RUN3_RECOVERY_LANE in "BTC|BTC-USDT-PERP" "ETH|ETH-USDT-PERP"; do
  RUN3_RECOVERY_ASSET="${RUN3_RECOVERY_LANE%%|*}"
  RUN3_RECOVERY_INSTRUMENT="${RUN3_RECOVERY_LANE#*|}"
  print "canonical history recovery: asset=$RUN3_RECOVERY_ASSET"
  while true; do
    if [[ "$(date +%s)" -ge "$RUN3_DEADLINE" ]]; then
      print -u2 "Canonical recovery did not complete before the startup deadline"
      exit 1
    fi
    RUN3_REMAINING="$(run3_remaining_seconds)" || {
      print -u2 "canonical recovery preparation deadline reached"
      exit 1
    }
    if RUN3_RECOVERY_RESPONSE="$(curl -fsS --max-time "$RUN3_REMAINING" \
      -X POST http://127.0.0.1:8003/runtime/recover \
      -H 'Content-Type: application/json' \
      -d "{\"asset\":\"$RUN3_RECOVERY_ASSET\",\"instrument_id\":\"$RUN3_RECOVERY_INSTRUMENT\",\"since\":\"$RUN3_RECOVERY_SINCE\",\"until\":\"$RUN3_RECOVERY_UNTIL\"}" \
      2>/dev/null)" && print -r -- "$RUN3_RECOVERY_RESPONSE" | validate_recovery_response; then
      break
    fi
    print -u2 "canonical recovery request did not complete; retrying asset=$RUN3_RECOVERY_ASSET"
    sleep 15
  done
done

# Recovery returns after the runtime supervisor has been recreated, but LIVE
# still requires one valid closed observation from the live provider.
while true; do
  if [[ "$(date +%s)" -ge "$RUN3_DEADLINE" ]]; then
    print -u2 "Ingestion did not return to LIVE after canonical recovery"
    exit 1
  fi
  RUN3_REMAINING="$(run3_remaining_seconds)" || {
    print -u2 "runtime readiness deadline reached"
    exit 1
  }
  RUN3_RUNTIME="$(curl -fsS --max-time "$RUN3_REMAINING" http://127.0.0.1:8003/runtime 2>/dev/null || true)"
  if print -r -- "$RUN3_RUNTIME" | validate_live_runtime; then
    break
  fi
  sleep 15
done

while true; do
  if [[ "$(date +%s)" -ge "$RUN3_DEADLINE" ]]; then
    print -u2 "Canonical publication did not become ready before the deadline"
    exit 1
  fi
  RUN3_PENDING="$(docker exec "$RUN3_DB_CONTAINER" env PGOPTIONS='-c statement_timeout=10s' \
    psql -X -A -t -U flipper -d flipper_db \
    -c "SELECT count(*) FROM ingestion.outbox WHERE published_at IS NULL;" \
    2>/dev/null | tr -d '[:space:]' || true)"
  RUN3_STREAMS_READY=1
  for RUN3_STREAM_KEY in "${RUN3_STREAM_KEYS[@]}"; do
    RUN3_STREAM_LENGTH="$(docker exec "$RUN3_BROKER_CONTAINER" valkey-cli --raw XLEN "$RUN3_STREAM_KEY" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ ! "$RUN3_STREAM_LENGTH" =~ '^[0-9]+$' ]] || (( RUN3_STREAM_LENGTH <= 0 )); then
      RUN3_STREAMS_READY=0
    fi
  done
  if [[ "$RUN3_PENDING" == "0" ]] && (( RUN3_STREAMS_READY == 1 )); then
    (( RUN3_ZERO_OUTBOX_STREAK += 1 ))
  else
    RUN3_ZERO_OUTBOX_STREAK=0
  fi
  if (( RUN3_ZERO_OUTBOX_STREAK >= 2 )); then
    break
  fi
  sleep 15
done

docker compose -p "$RUN3_PROJECT" \
  -f "$RUN3_COMPOSE" \
  --profile prod up -d \
  decision otel-collector prometheus grafana
