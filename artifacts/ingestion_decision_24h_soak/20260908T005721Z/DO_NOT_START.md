# Historical pre-launch hold — resolved

The earlier incomplete-tooling and AC holds are resolved. Root independently
verified 37 tests, all seven Python lint/format checks, shell/plist/Compose
validation, source/image identity and the real AC sleep guard. The 21 approved
tooling hashes are recorded in APPROVED_TOOLING_HASHES.json. Use only the reviewed
launchd entrypoint; do not manually set measurement_start_at or edit tooling.

macOS reported Battery Power at 2026-09-08T01:34Z; the real sleep guard correctly
refused to start a harmless child. AC must be reverified before runtime work.

See plans/orchestrator-decision-guarded-soak-launch-v1.md for current operational
state. Historical battery failure above remains evidence, not a current blocker.
