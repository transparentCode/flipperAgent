#!/bin/zsh
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

RUN3_ROOT="/Users/kajukatli/projects/flipperAgent"
RUN3_ID="20260909T010152Z"
RUN3_DIR="$RUN3_ROOT/artifacts/ingestion_decision_24h_soak/$RUN3_ID"
RUN3_LOCAL="$RUN3_DIR/run-local"
RUN3_LAUNCHER="$RUN3_LOCAL/guarded_launch.py"
RUN3_GUARD="$RUN3_LOCAL/source/scripts/host_sleep_guard.py"
RUN3_CHILD="$RUN3_LOCAL/launchd/run-guarded-child.sh"
RUN3_STOP_MARKER="$RUN3_DIR/STOP_REQUESTED"
RUN3_PROJECT="flipper-id-soak-20260909t010152z"
RUN3_SOURCE_SHA="afc70323f04445a5a08c085d0b54cb5a4b381c66"

RUN3_MODE="${1:-}"
if [[ -n "$RUN3_MODE" && "$RUN3_MODE" != "--warmup-only" ]]; then
  print -u2 "unsupported run mode: $RUN3_MODE"
  exit 64
fi

[[ -e "$RUN3_STOP_MARKER" ]] && exit 0

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

cd "$RUN3_ROOT"
RUN3_MODE_ARGS=()
if [[ -n "$RUN3_MODE" ]]; then
  RUN3_MODE_ARGS+=("$RUN3_MODE")
fi
exec "$RUN3_PYTHON" "$RUN3_LAUNCHER" \
  --run-dir "$RUN3_DIR" \
  --guard-script "$RUN3_GUARD" \
  --probe-interval 5 \
  --probe-timeout 2 \
  --startup-timeout 8 \
  --terminate-grace 2 \
  -- /bin/zsh "$RUN3_CHILD" "${RUN3_MODE_ARGS[@]}"
