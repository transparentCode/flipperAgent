# Coder to Review: Trendline-Family Candidate/Geometry Real-Data Trial v2

## Scope Executed

Executed only `plans/architect-to-coder-trendline-family-candidate-real-data-trial-v2.md`.

- Applied bounded runner persistence remediation and regression tests.
- Made exactly one approved Binance USD-M Futures request.
- Stopped after canonical Phase-I artifact verification rejected its own persisted bundle.
- Did not retry, alter research semantics, or start tracker work.

## Files Changed

```text
scripts/run_trendline_family_candidate_geometry_trial.py
tests/scripts/test_trendline_family_candidate_geometry_trial.py
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
.codebase-memory/  # regenerated index only
```

## Retry Authorization

```text
authorization_id: trendline_family_candidate_geometry_retry_v2
execution_attempt: 2
single_execution: true
```

Authorization consumed at one `get_historical_ohlcv(...)` invocation. No second V2 request occurred.

## Preserved V1 Evidence

V1 root remained unchanged.

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
    execution_scope.json

SHA-256 before/after: 20df6747ee9098e5cf6a5b507521944d06262debbdd31e3a68ac304c0f58c901
```

## V2 Execution Identity

```text
trial_name: btcusdt_4h_20250801_20251201_candidate_geometry_v2
execution_attempt: 2
authorization_id: trendline_family_candidate_geometry_retry_v2
supersedes_trial_name: btcusdt_4h_20250801_20251201_candidate_geometry_v1
previous_attempt_status: local_persistence_failure_before_normalization
phase_i_semantics_unchanged: true
```

## Persistence Remediation

- `prepare_trial_root()` rejects existing root, creates V2 root and `input/` before adapter construction/call, atomically writes scope.
- Raw CSV serialized in-memory then passed through `_atomic_write()`.
- Normalized CSV serialized in-memory then passed through `_atomic_write()`.
- Atomic writer rejects existing targets. Raw/normalized CSV, manifests, and report cannot overwrite evidence.
- Raw and normalized manifests hash exact persisted CSV bytes and bind V2 retry identity.

## Pre-Network Validation

Passed before network access:

```text
runner persistence/preflight tests: 8 passed
Phase-I optimization and research-lab tests: 53 passed
Ruff: passed
compileall: passed
git diff --check: passed
```

Verified before request:

```text
V2 root: absent
V1 scope SHA-256: 20df6747ee9098e5cf6a5b507521944d06262debbdd31e3a68ac304c0f58c901
trendline_family.yaml SHA-256: 7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

Mocked coverage proves V2 root/input exists before adapter construction and call, both atomic boundaries, exact manifest hashes, exact request, config, policy, folds, grid, seed, objective, and holdout wrapper semantics.

## Data Request

Exactly one request:

```text
Binance USD-M Futures
BTCUSDT / 4h
since: 1754006400000
until: 1764547200000
limit: 1000
```

## Raw Evidence Persistence

Persisted before normalization:

```text
raw_binance_response.csv
raw_fetch_manifest.json
raw rows: 733
raw SHA-256: aff33fd802c1ca4727ae3a9ded7add445f8e48605c8fc7b20f5c6ab4b959501b
```

Independent exact-byte hash check passed.

## Data Preflight

Passed. Normalized confirmed dataset:

```text
rows: 732
first: 2025-08-01T00:00:00Z
last: 2025-11-30T20:00:00Z
dataset_hash: trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53
normalized SHA-256: b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150
```

Exact-byte normalized-input manifest hash check passed.

## Resolved Config

```text
config version: 1
model version: trendline_family_v1
resolved config hash: da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
lookback/min_bars: 180 / 40
fractal left/right: 3 / 3
minimum pivots: 2
minimum quality: 0.35
```

No YAML write. Config identity matched V1 contract.

## Outcome Policy

Unchanged:

```text
horizon: 12
ATR window: 14
touch tolerance: 0.25 ATR
survival penetration: 0.75 ATR
reaction threshold: 0.50 ATR
policy_version: candidate_structural_outcome_btcusdt_4h_v1
```

## Fold Plan

Unchanged expanding plan:

```text
initial train: 240
validation: 96
folds: 3
holdout: 96
warmup: 180
purge: 12
embargo: 0
label horizon: 12
```

## Search Grid

Unchanged six-trial grid:

```text
candidate.lookback_bars: 120, 180, 240
candidate.min_candidate_quality: 0.30, 0.40
maximum_trial_count: 6
seed: 0
```

## Objective

Unchanged:

```text
objective_version: candidate_geometry_reaction_btcusdt_4h_v1
primary_metric: reaction_quality
maximize: true
minimum_sample_count: 100
minimum_fold_coverage: 1.0
maximum_failure_rate: 0.0
allowed_degradation: 0.0
require_comparable_population: true
```

## Validation Results

`run_phase_i_evaluation(..., open_holdout=True)` executed using persisted, preflighted V2 input. Phase-I reached artifact writing, then canonical artifact verification raised:

```text
ContractValidationError:
persisted promotion recommendation does not match derived evidence
```

This failure occurred after partial Phase-I files were written. It is not a data, config, policy, fold, grid, or runner-persistence failure.

## Holdout Handling

No independent verified bundle exists. Do not trust or report holdout status from partial Phase-I files. No holdout was opened outside canonical frozen-finalist/audited Phase-I flow.

## Verified Artifact Bundle

Rejected twice:

1. Canonical `write_phase_i_artifacts()` self-verification failed.
2. Read-only independent `load_verified_phase_i_artifacts(...)` reproduced same `ContractValidationError`.

Therefore `trial_report.md` was not generated. Reviewer-facing report must derive only from verified artifacts.

## Candidate Metrics

Not reported. Partial Phase-I bundle is unverified.

## Parameter-Effect Audits

Not reported. Partial Phase-I bundle is unverified.

## Recommendation

No recommendation. Promotion recommendation payload cannot be trusted because canonical verification rejected derived-truth consistency.

## Runtime And Regime Isolation

No changes to Binance adapter, canonical model/optimization semantics, YAML, runtime, RegimeV2, signal, selection, strategy, risk, execution, portfolio, or tracker paths. No runtime configuration write or promotion occurred.

## Tests

Post-attempt validation passed:

```text
tests/scripts/test_trendline_family_candidate_geometry_trial.py: 8 passed
tests/models/trendline_family: 346 passed
trendline-family + RegimeV2 adapter + projected-signal integration: 374 passed
RegimeV2 + selection + signals: 148 passed, 1 existing OpenTelemetry deprecation warning
Ruff: passed
compileall: passed
git diff --check: passed
```

## Codebase-Memory

```text
project: Users-aloobhujia-flipperAgent
nodes: 45012
edges: 142590
status: ready
```

`run_phase_i_evaluation` callers in trial flow:

```text
_run_phase_i -> run_trial -> main
```

Changed scope remains runner/tests, V2 artifacts, this handoff, and generated codebase-memory index. Existing unrelated dirty worktree files were not altered.

## Known Gaps

- V2 execution root is exhausted. No retry is authorized.
- Raw/normalized market evidence is valid and hash-bound, but Phase-I bundle is unverified.
- Canonical artifact consistency failure is outside approved V2 remediation scope. No canonical patch applied.
- No candidate-quality, parameter-effect, holdout, promotion, PnL, or runtime claim is valid from this attempt.

## Next Handoff

Separate bounded review/approval required to diagnose `persisted promotion recommendation does not match derived evidence` in canonical Phase-I artifact verification. That task must preserve V2 artifacts and must not request remote data, rerun this trial, or begin tracker work.
