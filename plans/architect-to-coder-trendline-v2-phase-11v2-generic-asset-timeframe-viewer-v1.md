# Architect-to-Coder Handoff: Phase 11V.2 Generic Viewer Runner

## Objective

Add one generic, offline-first Trendline V2 viewer runner for arbitrary
approved assets and fixed-duration timeframes. The runner must turn causal
OHLCV input into the existing `ProviderResult`, publish the existing verified
viewer bundle format, and optionally serve it on loopback.

## Authorized Scope

Create only:

- `src/libs/models/trendline_v2/tools/viewer/runner.py`
- `scripts/run_trendline_v2_viewer.py`
- `tests/models/trendline_v2/tools/viewer/test_runner.py`
- `tests/scripts/test_run_trendline_v2_viewer.py`
- this handoff
- `plans/coder-to-orchestrator-trendline-v2-phase-11v2-generic-asset-timeframe-viewer-v1.md`

Modify `viewer/__init__.py` only if an export is required. Do not modify the
fixed smoke, payload, diagnostic exporter, server, web frontend, canonical
plural trendlines, model source contracts, YAML, runtime, or research
evidence.

## Frozen Contract

- Assets: `BTCUSDT`, `ETHUSDT`, `SUIUSDT`, `SOLUSDT`, already uppercase.
- Timeframes: positive integer `<number>m`, `<number>h`, or `<number>d`.
- CSV columns: `timestamp,open,high,low,close,volume`.
- Timestamps: one whole-column epoch-millisecond format or one timezone-aware
  UTC ISO format; no sorting, deduplication, filling, resampling, or gaps.
- Causal inclusion: candle close must satisfy `open + interval <= as_of`.
- Optional `start` filters candle opens after causal filtering.
- Provider profile: `confirmed_extrema_pair_viewer_v1` with the six fixed
  values from the approved smoke profile.
- Provider execution uses `discover_trendlines(...)` and existing
  `write_viewer_bundle(...)` without fallback or parameter tuning.
- Output contains exactly `source_binding.json`, `provider_result.json`,
  `run_report.json`, and the two viewer-bundle members.
- Output publication is sibling-staging plus atomic rename. Existing nonempty
  output is refused before source access or adapter construction.
- Verification is source-independent and checks canonical bytes, identities,
  provider/result/report/bundle cross-bindings, and exact member layout.
- Binance mode is guarded by `TRENDLINE_V2_ALLOW_VIEWER_FETCH=1`, uses the
  existing adapter, explicit boundaries, pages of at most 1,000, no retry,
  bounded pagination, and injected fake adapters in tests only.
- Serving is fixed to `127.0.0.1`, with no browser launch and no silent port
  substitution.

## Forbidden Scope

- No real Binance or other network execution during implementation.
- No edits to fixed BTCUSDT smoke or R4/R5 diagnostic paths.
- No provider redesign, selector, tracker, lifecycle, MTF, Regime, YAML,
  runtime, frontend, canonical plural trendline, or evidence changes.
- No commit, merge, push, or generated artifacts in the repository.

## Acceptance Criteria

Tests cover valid ISO and epoch CSVs; strict asset/timeframe rules; malformed
timestamps and OHLCV; causal future-row invariance; unclosed candles; frozen
provider settings; success and abstention bundles; deterministic identities;
source and payload mutation detection; exact output layout; atomic cleanup;
Binance guard, pagination, gap/duplicate rejection and no-retry behavior; and
loopback-only serving. CLI help and verification mode must be usable without
source access.

## Validation

Run focused runner tests, existing viewer Python tests, frontend tests, full
Trendline V2 tests, canonical plural Trendlines tests, Ruff, compileall and
`git diff --check`. Run one synthetic offline CLI smoke and verify its output.
Do not run Binance. Reindex codebase-memory after implementation and report
the result.

## Expected Handoff

Return `READY_FOR_TRENDLINE_V2_GENERIC_VIEWER_RUNNER_REVIEW` with exact branch
and HEAD, changed files, CLI help, test counts, synthetic IDs and source
binding, atomic-failure evidence, network/provider execution accounting,
worktree status, and codebase-memory result. Commit remains unauthorized.
