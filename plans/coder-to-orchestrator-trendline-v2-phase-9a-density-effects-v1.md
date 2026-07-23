# Coder to Orchestrator: Trendline V2 Phase 9A

## Status

`READY_FOR_ORCHESTRATOR_REVIEW`

Phase 9A remediation was executed as a descriptive, read-only candidate-density
study from the already verified local Phase 8V.1 BTCUSDT/4h bundle. No
parameter was selected, promoted, written to YAML, or written to runtime
configuration.

## Scope

Only these tracked source files were added:

- `scripts/analyze_trendline_v2_candidate_density.py`
- `tests/scripts/test_trendline_v2_candidate_density.py`
- `plans/coder-to-orchestrator-trendline-v2-phase-9a-density-effects-v1.md`

No Trendline V2 model/provider/viewer files, configuration files, or legacy
Trendline Family files were modified. Generated study artifacts remain outside
Git under:

`/tmp/trendline_v2_phase9a_density/btcusdt_4h_20250801_20251201/`

The superseded pre-remediation output was moved intact to:

`/tmp/trendline_v2_phase9a_density_superseded/btcusdt_4h_20250801_20251201/`

It must not be used for review or downstream analysis.

## Source Verification

The source root was validated before replay:

`/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201/`

Checks passed:

- source schema: `trendline_v2_real_asset_smoke_v1`;
- BTCUSDT / 4h identity;
- Binance USD-M Futures market identity;
- raw row count `733`, request limit `1000`, network request count `1`;
- normalized row count `732`;
- first bar `2025-08-01T00:00:00Z`;
- last bar `2025-11-30T20:00:00Z`;
- exact whole-second four-hour spacing;
- provider-result SHA, typed provider result, candidate/evidence binding;
- TVLC payload and bundle identities and semantic validation;
- `2697` provider candidates and `2697` provider evidence records;
- smoke-only provider configuration classification.

Source identity recorded by the study:

`079b7cec1dde131fb91180ee910cdb84499d27bb4ac64cd1ca46eaf355fc0358`

The generated `source_audit.json` contains the pre-replay byte inventory for
all four source files. A post-replay inventory matched every recorded path,
byte length, and SHA-256 value.

## Fixed Experiment

Baseline provider configuration:

```text
lookback_duration_seconds = 10540800.0
left_confirmation_bars = 1
right_confirmation_bars = 1
min_extrema_per_role = 2
max_hypotheses = 100000
max_output_candidates = 10000
```

The one-at-a-time matrix contains exactly `13` unique configurations:

- lookback: `1382400.0`, `2764800.0`, `5270400.0`, `10540800.0` seconds;
- left confirmation: `1`, `2`, `4`, `8` bars;
- right confirmation: `1`, `2`, `4`, `8` bars;
- minimum extrema per role: `2`, `4`, `8`, `16`;
- baseline combinations are deduplicated;
- workload limits remain unchanged in every configuration.

Each configuration was run on both causal prefixes:

- boundary policy: `confirmed_through_is_close_boundary_v1`;
- `mid`: `366` rows, last candle open `2025-09-30T20:00:00Z`,
  `observed_at=confirmed_through=2025-10-01T00:00:00Z`;
- `full`: `732` rows, last candle open `2025-11-30T20:00:00Z`,
  `observed_at=confirmed_through=2025-12-01T00:00:00Z`.

Per-run physical lookback history rows are persisted. Inclusive boundary
counts are exactly `96`, `192`, `366`, and `732` for 16, 32, 61, and 122 days,
respectively, capped by causal window length.

Execution counts are exact:

- semantic runs: `26`;
- deterministic baseline repeats: `2`;
- total provider executions: `28`;
- network requests: `0`.

Finite candidate activity uses only anchor-to-anchor intervals. No candidate
segment is extended to the observed timestamp.

## Evidence Results

All `28` runs returned `success`; no run failed or abstained.

Baseline density:

| Window | Rows | Candidates | Candidates/bar |
| --- | ---: | ---: | ---: |
| mid | 366 | 1091 | 2.980874316939891 |
| full | 732 | 2697 | 3.6844262295081966 |

Observed output effects in both windows:

- `left_confirmation_bars`: output effects for `2`, `4`, and `8`;
- `right_confirmation_bars`: output effects for `2`, `4`, and `8`.

Lookback results:

- 16-day lookback: mid `140` candidates / `96` history rows; full `175`
  candidates / `96` history rows;
- 32-day lookback: mid `488` candidates / `192` history rows; full `455`
  candidates / `192` history rows;
- 61-day lookback: mid `1091` candidates / `366` history rows; full `1069`
  candidates / `366` history rows;
- 122-day lookback: causal-window capped at `366` and `732` history rows.

16-day and 32-day values produced output effects in both windows. The 61-day
value produced an output effect in full and no output effect in mid.

`min_extrema_per_role` values `4`, `8`, and `16` showed
`NO_OUTPUT_EFFECT_IN_TESTED_RANGE` in both windows. This is only evidence that
the tested source did not exercise that field; it is not a removal or tuning
decision.

Deterministic baseline repeats matched semantic signatures, request identity,
and snapshot identity in both windows. Candidate and evidence hashes, provider
identities, configuration identities, snapshot identities, role counts, anchor
reuse, spans, finite active-density metrics, and history-row counts are
persisted per run.

Canonical candidate IDs remain observation-bound and are retained for per-window
hashes and deterministic repeat checks. Cross-window comparison uses the
research-only `candidate_structure_id`, excluding `observed_at` and canonical
candidate ID. Structure persistence was nonzero for `10/13` configurations.
This fingerprint is descriptive only; it is not model identity or tracking
identity.

## Artifacts

The output directory contains exactly:

- `source_audit.json`;
- `matrix.json`;
- `summary.csv`;
- `decision.json`;
- `runs/` with `28` run records.

JSON artifacts were independently reloaded and matched canonical JSON bytes.
CSV rows were independently verified in the declared deterministic ordering.
Private in-memory candidate/evidence ID sets used only for cross-window audit
were not persisted in run records or decision output.

`decision.json` contains the required descriptive fields and:

```text
PARAMETER_PROMOTION: NOT_AUTHORIZED
```

It contains no winner, best, recommendation, recommended value, or optimal
field. No chart or viewer-comparison artifact was generated.

## Implementation Notes

- The runner consumes the existing public `discover_trendlines` API and typed
  source contracts.
- Source provider JSON is reconstructed and compared by canonical semantic JSON
  so persisted JSON arrays correctly match immutable tuple fields.
- Viewer evidence comparisons use the same canonical semantic normalization.
- The runner supplies close-boundary timestamps explicitly and records exact
  physical lookback row counts.
- Cross-window structure fingerprints separate descriptive persistence from
  observation-bound canonical candidate identity.
- Output writes are atomic and refuse an existing output root or file.
- No network client, Binance adapter, Plotly, Matplotlib, browser launcher,
  Regime, legacy Trendline, or runtime configuration import was added.

## Validation

Focused study tests:

```text
11 passed
```

Required regression suites:

```text
Trendline V2 + viewer: 135 passed
Protected Trendline Family: 400 passed
Provider benchmark harness: 4 passed
Frontend Node/TypeScript: 13 passed
npm ci: 0 vulnerabilities
```

Static validation:

- Ruff: passed;
- compileall: passed;
- `git diff --check`: passed.

Codebase-memory status:

- full-root reindex was attempted and the worker returned a contained crash;
- repository CLI retry was unavailable because `codebase-memory-mcp` is not on
  PATH;
- existing per-directory indexes were healthy at the time of validation;
- targeted reindex attempts for `scripts`, `tests`, and `plans` also returned
  the same contained worker crash; their existing non-zero indexes remain
  intact but do not include this uncommitted change.
- post-remediation `scripts` reindex retry reproduced the same contained
  worker crash; no index was replaced with a zero-node result.

## Boundaries and Risks

- One BTCUSDT 4h source window and two causal prefixes only.
- Candidate density is not predictive quality, trading performance, or visual
  usability evidence.
- Results do not establish global, timeframe, or asset parameter scope.
- Workload limits were fixed and are not candidate-quality controls.
- No parameter promotion, canonical YAML change, frontend filtering, tracking,
  lifecycle, MTF, RegimeV2, or trading integration is authorized.

## Stop Conditions

No stop condition was triggered. The study used the existing local source and
performed no Binance request. The implementation stops at descriptive evidence
and is awaiting independent orchestrator review.

```text
PHASE_9A_DENSITY_EFFECTS: EXECUTED
PARAMETER_PROMOTION: NOT_AUTHORIZED
CANONICAL_YAML_CHANGE: NOT_AUTHORIZED
FRONTEND_CANDIDATE_HIDING: NOT_AUTHORIZED
TRACKING_AND_LIFECYCLE: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PUSH: NOT_AUTHORIZED
```
