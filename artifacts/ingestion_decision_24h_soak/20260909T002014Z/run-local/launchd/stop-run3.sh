#!/bin/zsh
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RUN3_ROOT="/Users/kajukatli/projects/flipperAgent"
RUN3_ID="20260909T002014Z"
RUN3_DIR="$RUN3_ROOT/artifacts/ingestion_decision_24h_soak/$RUN3_ID"
RUN3_PLIST="$RUN3_DIR/run-local/launchd/ingestion-decision-soak-run3.plist"
RUN3_DOMAIN="gui/$(id -u)"
RUN3_PROJECT="flipper-id-soak-20260909t002014z"
RUN3_OVERRIDE="$RUN3_DIR/run-local/soak-compose.override.yml"
RUN3_PYTHON="$RUN3_ROOT/.venv/bin/python"
RUN3_BOUND="$RUN3_DIR/run-local/bounded_command.py"
RUN3_STOP_DEADLINE=$(( $(date +%s) + 180 ))

touch "$RUN3_DIR/STOP_REQUESTED"
"$RUN3_PYTHON" "$RUN3_BOUND" --timeout 30 --deadline "$RUN3_STOP_DEADLINE" -- launchctl bootout "$RUN3_DOMAIN" "$RUN3_PLIST" 2>/dev/null || true
# Retain the final interval before removing containers. A failed capture
# deliberately leaves runtime objects intact for root inspection.
mkdir -p "$RUN3_DIR/raw-docker-logs"
chmod 700 "$RUN3_DIR/raw-docker-logs"
RUN3_LOG_DIR="$(mktemp -d "$RUN3_DIR/raw-docker-logs/stop.XXXXXX")"
RUN3_LOG_SINCE="$("$RUN3_PYTHON" -B - "$RUN3_DIR/RUN_STATE.json" <<'PY'
import json
import sys
from datetime import datetime, timedelta
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        state = json.load(handle)
    value = state.get("raw_log_cursor")
    if not value:
        value = min([state["created_at"], *[item["started_at"] for item in state.get("sut_container_baseline", {}).values()]])
    print((datetime.fromisoformat(value.replace("Z", "+00:00")) - timedelta(seconds=1)).isoformat())
except (OSError, ValueError, KeyError, TypeError):
    print("1970-01-01T00:00:00Z")
PY
)"
RUN3_LOG_UNTIL="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
RUN3_LOG_PIDS=()
for RUN3_SERVICE in db broker ingestion decision otel-collector prometheus grafana; do
  (
    RUN3_LOG_CODE=0
    "$RUN3_PYTHON" "$RUN3_BOUND" --timeout 40 --deadline "$RUN3_STOP_DEADLINE" --max-file-bytes 16777216 -- \
      docker compose -p "$RUN3_PROJECT" -f "$RUN3_OVERRIDE" --profile prod logs \
      --no-color --timestamps --since "$RUN3_LOG_SINCE" --until "$RUN3_LOG_UNTIL" "$RUN3_SERVICE" \
      >"$RUN3_LOG_DIR/$RUN3_SERVICE.log" 2>&1 || RUN3_LOG_CODE=$?
    RUN3_LOG_BYTES="$(wc -c < "$RUN3_LOG_DIR/$RUN3_SERVICE.log" | tr -d ' ')"
    (( RUN3_LOG_BYTES < 16777216 )) || RUN3_LOG_CODE=125
    print -r -- "service=$RUN3_SERVICE exit=$RUN3_LOG_CODE bytes=$RUN3_LOG_BYTES since=$RUN3_LOG_SINCE until=$RUN3_LOG_UNTIL" >"$RUN3_LOG_DIR/$RUN3_SERVICE.status"
    shasum -a 256 "$RUN3_LOG_DIR/$RUN3_SERVICE.log" >>"$RUN3_LOG_DIR/$RUN3_SERVICE.status"
    exit "$RUN3_LOG_CODE"
  ) &
  RUN3_LOG_PIDS+=($!)
done
RUN3_LOG_FAILED=0
for RUN3_LOG_PID in "${RUN3_LOG_PIDS[@]}"; do
  wait "$RUN3_LOG_PID" || RUN3_LOG_FAILED=1
done
if (( RUN3_LOG_FAILED )); then
  print -u2 "final raw log capture failed; containers and volumes retained; evidence: $RUN3_LOG_DIR"
  exit 1
fi
"$RUN3_PYTHON" "$RUN3_BOUND" --timeout 180 --deadline "$RUN3_STOP_DEADLINE" -- docker compose -p "$RUN3_PROJECT" -f "$RUN3_OVERRIDE" --profile prod down --remove-orphans
print "stopped $RUN3_PROJECT; run volumes preserved"
