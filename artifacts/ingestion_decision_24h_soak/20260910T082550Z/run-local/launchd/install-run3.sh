#!/bin/zsh
set -euo pipefail

RUN3_PLIST="/Users/kajukatli/projects/flipperAgent/artifacts/ingestion_decision_24h_soak/20260910T082550Z/run-local/launchd/ingestion-decision-soak-run3.plist"
RUN3_DOMAIN="gui/$(id -u)"

RUN3_DIR="/Users/kajukatli/projects/flipperAgent/artifacts/ingestion_decision_24h_soak/20260910T082550Z"
if launchctl print "$RUN3_DOMAIN/com.flipperagent.ingestion-decision-soak-0610082550" >/dev/null 2>&1; then
  print -u2 "refusing to replace an existing launchd job"
  exit 78
fi
for RUN3_MARKER in GUARDED_LAUNCH_STATE.json RUN_STATE.json STOP_REQUESTED final_audit.json; do
  if [[ -e "$RUN3_DIR/$RUN3_MARKER" ]]; then
    print -u2 "refusing an existing or terminal attempt: $RUN3_MARKER"
    exit 78
  fi
done
launchctl bootstrap "$RUN3_DOMAIN" "$RUN3_PLIST"
print "prepared com.flipperagent.ingestion-decision-soak-0610082550"
