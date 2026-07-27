# Coder-to-Orchestrator Handoff: Phase 11V.2 Generic Viewer Runner

## Status

`READY_FOR_TRENDLINE_V2_GENERIC_VIEWER_RUNNER_REVIEW`

Implementation is complete on branch
`research/trendline-v2-phase-11v2-generic-asset-timeframe-viewer-v1`.
No commit, merge, push, Binance request, or generated repository artifact was
made.

## Branch and Scope

- HEAD: `9de4226106f61140ea940f2e92f372ed148c970f`
- Worktree: four implementation/test files plus two handoff files, six
  untracked files total; nothing staged; no tracked modifications.
- Added implementation:
  - `src/libs/models/trendline_v2/tools/viewer/runner.py`
  - `scripts/run_trendline_v2_viewer.py`
- Added tests:
  - `tests/models/trendline_v2/tools/viewer/test_runner.py`
  - `tests/scripts/test_run_trendline_v2_viewer.py`
- Added handoffs:
  - `plans/architect-to-coder-trendline-v2-phase-11v2-generic-asset-timeframe-viewer-v1.md`
  - this file
- No fixed smoke, diagnostic path, payload, server, web, source-model, YAML,
  runtime, provider, tracker, MTF, Regime, or canonical plural Trendlines file
  changed.

## CLI

`--help` exposes:

```text
--asset --timeframe --input-csv --source {csv,binance} --start --as-of
--output --serve --port --verify-output
```

CSV mode is offline-first. Binance mode requires
`TRENDLINE_V2_ALLOW_VIEWER_FETCH=1` before adapter construction and output
staging. Pagination uses injected fake adapters in tests, limit 1,000, no retry,
strict page continuity, and bounded page count.

## Synthetic Offline Smoke

Input: synthetic `ETHUSDT` / `1h` ISO-UTC CSV, 48 rows, causal boundary
`2026-07-22T00:00:00Z`. No Binance adapter or network request occurred.

- Viewer status: `VIEWER_READY_WITH_LINES`
- Provider status: `success`
- Candidates: `26` (`13` support, `13` resistance)
- Source binding ID: `7c5628ddee1c50252b834449b090992fee6533467e68f0631c38064d2d008a9f`
- Input identity: `4ab76b40a0abd3f353d699f8a795c00c75e10021a66311fa78acb18f8ef09649`
- Provider result ID: `a31fc2218a67d5a907467c65e812ef40c5cbc76725e63213631ae125eb0b7834`
- Provider identity: `b1721806600f5486f244cc987644918f6af061777803512c46eca92ace8794f8`
- Viewer payload ID: `1399b973a6747030020293566e98ccc902f242f55dec0c9673a3828e4c382c23`
- Viewer bundle ID: `f069b4391af96cf26dfd0b4fd9b8303726b304fea6fa9965e7cb936ba823f098`
- Strict `--verify-output`: passed.
- HTTP smoke: chart payload `200`; `/manifest.json` `404`.

The smoke executed canonical `discover_trendlines` once on synthetic input.
External provider/adapter calls: `0`. Network calls: `0`.

## Atomicity and Verification

Tests prove nonempty output refusal before CSV access, Binance guard before
adapter construction and output creation, failed pagination cleanup, no retry,
payload/provider mutation rejection, extra-file rejection, deterministic IDs,
and source mutation identity changes. Publication uses sibling staging, staged
verification, cleanup on failure, and atomic rename.

Remediation probes now reject rebound second-page `since` metadata, impossible
extra request pages, late first pages, within-page gaps and duplicates,
fractional timestamps, and every non-exact Binance close time. CLI verification
rejects explicit `--source` and `--port`; `--port` without `--serve` is rejected.

## Validation

- Focused runner/API tests: `40 passed`.
- Viewer Python directory: `69 passed` after remediation.
- Review baseline: `Viewer Python: 61 passed` before added adversarial tests.
- Frontend: `20 passed`; `npm ci` reported `0 vulnerabilities`.
- Full requested V2 command: `1080 passed, 38 skipped`.
- Historical requested V2 baseline: `294 passed`.
- Canonical plural Trendlines: `473 passed`.
- Historical viewer baseline: Python `36`; frontend `20`.
- Ruff: passed after removing one unused import.
- Compileall: passed.
- `git diff --check`: passed.

The full V2 command is broader than the historical `294` baseline because it
includes the current research-script matrix and all V2 model tests.

## Protected Boundaries

No real Binance execution, evidence regeneration, R3B/R4/R5 access, fixed
BTCUSDT smoke modification, frontend modification, or canonical Trendlines
modification occurred. Commit, merge, push, and real viewer fetch remain
unauthorized pending review.

## Codebase-Memory

Reindex was attempted with the repository indexer in moderate mode. The worker
exited nonzero after crashing on one file; the codebase-memory server survived.
Existing split indexes remain available and nonzero. Status reported current
projects for `src`, `tests`, `scripts`, `plans`, `docs`, and `conductor`; GitNexus
remains stale on an older research branch. This is tooling evidence only and
does not change source or validation results.

## Review Stop

Return the required status string and stop without committing, merging, pushing,
fetching Binance, or regenerating protected evidence.
