# Coder To Review: Candidate Evidence Report Integrity v1

## Scope Executed

Closed external source-inventory provenance gap only. Added strict pure
inventory validation and cross-binding inside `validate_report_bundle(...)`.
No report generation, trial execution, network access, or runtime work.

## Files Changed

- `scripts/build_trendline_family_candidate_evidence_report.py`
- `tests/scripts/test_trendline_family_candidate_evidence_report.py`
- `plans/coder-to-review-trendline-family-candidate-evidence-report-integrity-v1.md`

## Root Cause

Prior validator trusted `report_manifest.source_inventory_sha256`. Forged nested
source file hash plus recomputed outer file hash passed. Per-source inventory
hashes and aggregate source inventory ID were not independently rederived.

## Source Inventory Validation

Added `validate_source_inventory_payload(...)`. It requires:

- exact top-level schema fields and report schema version;
- exact `v1`/`v2` keys, source names, and expected trial names;
- exact source/file-record field sets;
- non-empty, canonical, sorted, unique, safe POSIX relative paths;
- non-negative non-boolean integer sizes;
- lowercase 64-character SHA-256 values;
- recomputed per-source inventory hashes;
- recomputed aggregate source-inventory ID.

It returns only independently derived `{v1, v2}` inventory hashes.

## Cross-Binding

Derived source hashes must exactly equal both:

- `evidence_report.report_identity.source_inventory_hashes`;
- `report_manifest.source_inventory_hashes`.

Existing report ID, input, Phase-I artifact, dataset, recommendation, JSON,
Markdown, and outer source-inventory file-hash checks remain active.

## Adversarial Tests

Temporary copied report bundles cover:

- confirmed nested-SHA exploit with rebound outer manifest SHA;
- forged per-source inventory hash and aggregate inventory ID;
- duplicate and unsorted paths;
- `../escape`, absolute, backslash, and dot-segment paths;
- swapped source/trial names;
- missing/extra source keys and unknown top-level key;
- negative, boolean, string sizes and uppercase/short/non-hex SHA values.

All reject fail-closed. Existing generated bundle validates unchanged.

## Existing Bundle Validation

Read-only validation passes for report ID:

`trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41`

Recommendation remains winner `None`, decision `REJECT`, rationale
`no_validation_trial_passed_stage_owned_gates`.

## Source And Report Byte Integrity

Pre/post SHA inventories match exactly:

- V1 trial root: 1 file.
- V2 trial root: 30 files.
- Report bundle: 4 files.

Report file SHA-256 values unchanged:

- `source_inventory.json`: `45197651e25e65561fdb16e2676117ac6409527e233dbb5c7055fcd27efcf6ab`
- `evidence_report.json`: `07e50ea26318db77ecd034085bd068792227a165d5872cb71f9d818a2e533242`
- `evidence_report.md`: `b68adbb22707097ea352b3fb8baa238c5b2a88542a7b24d9bc6744703c6a4cf0`
- `report_manifest.json`: `7c6bd0d76501296dde5353d389daa5a0695a986468f59bb205298c84aae5378d`

## Runtime And Regime Isolation

No Binance, network, evaluator, holdout, YAML, runtime, canonical model,
optimizer, tracker, interaction, MTF, RegimeV2, signal, or selection changes.
`validate_report_bundle(...)` caller path remains report builder/main only.

## Tests

- Focused report suite: `25 passed`.
- Optimization and research support: `54 passed`.
- Full trendline-family: `347 passed`.
- Family/adapter/projected isolation: passed.
- RegimeV2/selection/signals isolation: `148 passed`, one existing OpenTelemetry deprecation warning.
- Ruff, compileall, `git diff --check`: passed.

## Codebase-Memory

Graph MCP transport unavailable. CLI fallback inspected validator callers and
reindexed after this handoff. No production runtime caller found.

## Known Gaps

Validator proves external inventory semantic chain only. It intentionally does
not reread or rehash live trial-root files during report validation.

## Next Handoff

Independent integrity review. Do not regenerate report or begin tracker work
without separate approval.
