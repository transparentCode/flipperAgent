#!/bin/zsh
set -euo pipefail

RUN3_ROOT="/Users/kajukatli/projects/flipperAgent"
RUN3_ID="20260908T030738Z"
RUN3_DIR="$RUN3_ROOT/artifacts/ingestion_decision_24h_soak/$RUN3_ID"
RUN3_LOCAL="$RUN3_DIR/run-local"
RUN3_PROJECT="flipper-id-soak-20260908t030738z"
RUN3_SOURCE_SHA="72e88a6b38077b0d3c29c2d5f7518a0a072b6664"
RUN3_START="$RUN3_LOCAL/launchd/start-run3.sh"
RUN3_HARNESS="$RUN3_LOCAL/soak_harness.py"
RUN3_OVERRIDE="$RUN3_LOCAL/soak-compose.override.yml"

RUN3_MODE="${1:-}"
if [[ -n "$RUN3_MODE" && "$RUN3_MODE" != "--warmup-only" ]]; then
  print -u2 "unsupported run mode: $RUN3_MODE"
  exit 64
fi

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

[[ -e "$RUN3_DIR/STOP_REQUESTED" ]] && exit 0

# This script is the sole child of guarded_launch.py, so startup, canonical
# preparation, observer startup, warm-up, measurement, and evidence freeze all
# remain inside one owned SleepAssertionGuard lifetime.
"$RUN3_START"

RUN3_MODE_ARGS=()
if [[ "$RUN3_MODE" == "--warmup-only" ]]; then
  RUN3_MODE_ARGS+=(--warmup-only)
fi

exec "$RUN3_PYTHON" "$RUN3_HARNESS" \
  --worktree "$RUN3_ROOT" \
  --run-dir "$RUN3_DIR" \
  --project "$RUN3_PROJECT" \
  --override-file "$RUN3_OVERRIDE" \
  --source-sha "$RUN3_SOURCE_SHA" \
  --status-port 8765 \
  --warmup-seconds 900 \
  --preparation-timeout-seconds 7200 \
  --measurement-seconds 86400 \
  --cotenant mcp-cbm \
  --cotenant mcp-gitnexus \
  "${RUN3_MODE_ARGS[@]}"
