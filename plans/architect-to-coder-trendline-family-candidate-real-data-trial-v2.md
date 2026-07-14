# Architect → Coder: Trendline-Family Candidate/Geometry Real-Data Trial v2

## Objective

Correct the v1 runner’s local input-artifact persistence defect and execute one
new, bounded BTCUSDT 4h candidate/geometry trial under a distinct execution
attempt identity.

The v1 request was consumed but produced no persisted market input and no
Phase-I evidence. The v2 task must preserve the exact research semantics while
changing only the execution-attempt identity and persistence safety.

Approved retry decision:

```text
plans/approval-decision-trendline-family-candidate-real-data-trial-retry-v1.md
```

## Scope Boundaries

### In scope

- create the input-artifact directory before any network call;
- make raw and normalized CSV persistence atomic;
- add regression tests covering the exact v1 failure path;
- preserve the exhausted v1 execution root unchanged;
- create a new immutable v2 execution root;
- make exactly one new Binance USD-M Futures request after pre-network gates
  pass;
- execute the unchanged Phase-I candidate/geometry trial if data preflight
  passes;
- verify the persisted Phase-I artifact bundle independently;
- write a v2 reviewer handoff.

### Out of scope

- another request after the v2 adapter invocation;
- Binance adapter redesign, pagination, chunking, or retries;
- changing asset, timeframe, date range, row contract, objective, policy, fold
  plan, grid, seed, or holdout behavior;
- modifying canonical model or optimization semantics;
- tracker, interaction/event, MTF, RegimeV2, signal, selection, strategy, risk,
  execution, portfolio, or runtime work;
- YAML mutation or config-patch application;
- PnL or trading interpretation.

## Affected Symbols / Modules / Flows

Read first:

- `.agents/skills/quant-coder/SKILL.md`
- `plans/approval-decision-trendline-family-candidate-real-data-trial-retry-v1.md`
- `plans/architect-to-coder-trendline-family-candidate-real-data-trial-v1.md`
- `plans/coder-to-review-trendline-family-candidate-real-data-trial-v1.md`
- `scripts/run_trendline_family_candidate_geometry_trial.py`
- `tests/scripts/test_trendline_family_candidate_geometry_trial.py`

Expected implementation scope:

```text
scripts/run_trendline_family_candidate_geometry_trial.py
tests/scripts/test_trendline_family_candidate_geometry_trial.py

artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
    execution_scope.json                  # preserve unchanged

  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    execution_scope.json
    input/
      raw_binance_response.csv
      raw_fetch_manifest.json
      normalized_ohlcv.csv
      input_manifest.json
    phase_i/
    trial_report.md

plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
```

Do not modify canonical trendline-family, optimization, research-lab, adapter,
or runtime files.

## Execution Identity Contract

Change only the execution-attempt identity:

```python
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
EXECUTION_ATTEMPT = 2
AUTHORIZATION_ID = "trendline_family_candidate_geometry_retry_v2"
SUPERSEDES_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
```

The v2 `execution_scope.json` must include at least:

```text
trial_name
execution_attempt
Authorization ID
supersedes_trial_name
previous_attempt_status = local_persistence_failure_before_normalization
single_execution = true
phase_i_semantics_unchanged = true
asset / market / timeframe / start / end
```

Use a consistent JSON key spelling such as `authorization_id`.

Do not change the Phase-I semantic versions merely to represent the retry.
Keep exactly:

```text
CandidateOutcomePolicy.policy_version:
  candidate_structural_outcome_btcusdt_4h_v1

ObjectiveSpec.objective_version:
  candidate_geometry_reaction_btcusdt_4h_v1
```

A Phase-I run identity is content-derived from the actual dataset and research
semantics. It may therefore match the semantic identity that v1 would have had
if v1 had reached evaluation. This is acceptable because v1 produced no
Phase-I bundle. The enclosing execution root must still be v2.

## Fixed Data Request

Use exactly one call:

```python
BinanceNativeAdapter.get_historical_ohlcv(
    "BTCUSDT",
    "4h",
    since=1754006400000,
    until=1764547200000,
    limit=1000,
)
```

Equivalent fixed contract:

```text
market:                Binance USD-M Futures
asset:                 BTCUSDT
timeframe:             4h
start:                 2025-08-01T00:00:00Z
end:                   2025-12-01T00:00:00Z
expected confirmed rows: 732
first timestamp:       2025-08-01T00:00:00Z
last timestamp:        2025-11-30T20:00:00Z
```

No pagination, alternate request, retry, fallback source, or changed boundary is
permitted.

The new authorization is consumed when `get_historical_ohlcv(...)` is invoked.
If any later step fails, preserve evidence and stop.

## Persistence Remediation Contract

### Trial-root preparation

`prepare_trial_root()` must, before the adapter is constructed or called:

1. reject an existing v2 root;
2. create the v2 root;
3. create `<trial_root>/input/`;
4. atomically write `execution_scope.json`.

The function must not touch the v1 root.

### Raw response evidence

`persist_raw_fetch_evidence()` must not call `DataFrame.to_csv(path)` directly.
Serialize deterministically and use the existing `_atomic_write()` boundary, for
example:

```python
payload = raw.to_csv(index=False).encode("utf-8")
_atomic_write(raw_path, payload)
```

Then write `raw_fetch_manifest.json` atomically and bind:

- exact request parameters;
- adapter identity;
- execution attempt / authorization ID / trial name;
- raw column names and row count;
- SHA-256 of the exact persisted raw CSV bytes.

Do not normalize before raw evidence is safely persisted.

### Normalized input evidence

`persist_input()` must also persist `normalized_ohlcv.csv` through
`_atomic_write()` instead of direct path-based `to_csv()`.

The input manifest must retain all v1 fields and additionally bind the v2
execution-attempt identity. Its file hash must be calculated from the exact
persisted bytes.

No overwrite is allowed for raw, normalized, manifest, Phase-I, or report
artifacts.

## Configuration Contract

Resolve exactly:

```python
TrendlineFamilyConfigResolver.from_path(
    "configs/trendline_family.yaml"
).resolve(asset="BTCUSDT", timeframe="4h")
```

Expected unchanged identity:

```text
config version:       1
model version:        trendline_family_v1
resolved config hash: da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
candidate lookback:   180
candidate min bars:   40
fractal left/right:   3 / 3
minimum pivots:       2
minimum quality:      0.35
```

Stop before the request on drift. Do not edit YAML.

## Unchanged Outcome, Fold, Grid, and Objective Contracts

Use exactly the v1 contracts.

### Outcome policy

```python
CandidateOutcomePolicy(
    horizon_bars=12,
    atr_window=14,
    touch_tolerance_atr=0.25,
    survival_penetration_atr=0.75,
    reaction_threshold_atr=0.50,
    policy_version="candidate_structural_outcome_btcusdt_4h_v1",
)
```

### Fold plan

```python
build_walk_forward_fold_plan(
    dataset,
    initial_train_bars=240,
    validation_bars=96,
    fold_count=3,
    holdout_bars=96,
    warmup_bars=180,
    purge_bars=12,
    embargo_bars=0,
    label_horizon_bars=12,
    train_mode="expanding",
)
```

### Search grid

```python
{
    "candidate.lookback_bars": (120, 180, 240),
    "candidate.min_candidate_quality": (0.30, 0.40),
}
```

Exactly six primary trials, `maximum_trial_count=6`, `seed=0`.

### Objective

```python
ObjectiveSpec(
    objective_version="candidate_geometry_reaction_btcusdt_4h_v1",
    primary_metric="reaction_quality",
    maximize=True,
    minimum_sample_count=100,
    minimum_fold_coverage=1.0,
    maximum_failure_rate=0.0,
    allowed_degradation=0.0,
    require_comparable_population=True,
)
```

### Phase-I execution

Use `CandidateGeometryEvaluator` and `run_phase_i_evaluation(...)` exactly as in
v1, including `open_holdout=True`. Holdout may open only through validation
finalist freeze and audited Phase-I paths.

## Required Regression Tests Before Network Access

Add focused tests proving:

1. `TRIAL_NAME` is the v2 name and v1 root is not selected;
2. `prepare_trial_root()` creates `input/` before any adapter invocation;
3. `execution_scope.json` contains the v2 attempt, authorization, supersession,
   previous-status, and unchanged-semantics fields;
4. raw response persistence succeeds under a fresh root;
5. raw CSV manifest SHA-256 equals the exact persisted file hash;
6. normalized input persistence succeeds and its manifest hash matches;
7. a mocked `run_trial()` makes exactly one adapter call and reaches beyond both
   raw and normalized persistence boundaries;
8. the mocked adapter can assert that `<trial_root>/input/` already exists at
   call time;
9. existing-root reuse still rejects;
10. the exhausted v1 root is not modified by the tests or runner;
11. request/config/fold/grid/objective/holdout identities remain identical to
    v1.

The mocked top-to-bottom test may patch Phase-I execution, verified-artifact
loading, and report generation after proving both persistence boundaries. It
must not use network access.

## Pre-Network Validation Gate

Run all commands below before making the new request:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider

/Users/aloobhujia/.local/bin/ruff check \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py

git diff --check
```

Also verify before network access:

- v1 `execution_scope.json` bytes are unchanged;
- v2 root does not already exist;
- `configs/trendline_family.yaml` bytes are unchanged;
- exact request, config, fold, grid, policy, objective, and holdout assertions
  pass;
- no runtime or canonical package file changed.

If any pre-network gate fails, stop without consuming the request authorization.

## Remote Execution and Stop Rules

After every pre-network gate passes, invoke the fixed runner once.

The following outcomes are valid and must stop the task:

- request failure;
- raw persistence failure;
- row-count or timestamp-boundary rejection;
- gap, duplicate, incomplete-bar, or OHLCV rejection;
- config drift;
- fold/grid identity failure;
- no validation finalist;
- Phase-I trial failure;
- holdout audit failure;
- artifact-bundle verification failure;
- report-generation failure.

Never issue a second v2 request. Never switch source, date range, symbol,
timeframe, limit, or grid to work around a failure.

If preflight succeeds:

1. persist normalized input and manifest;
2. construct and validate the fixed fold plan;
3. execute Phase I once;
4. independently load and verify the persisted bundle;
5. generate `trial_report.md` only from persisted input and verified artifacts;
6. write the v2 coder-to-review handoff;
7. reindex codebase-memory and stop.

## Acceptance Criteria

- v1 execution root preserved byte-for-byte;
- v2 root uniquely identifies execution attempt 2;
- input directory exists before the only network call;
- raw and normalized CSVs are atomically persisted and hash-bound;
- exactly one new Binance request occurs;
- exact 732-row preflight enforced;
- all v1 research semantics unchanged;
- Phase-I holdout opens only through frozen-finalist/audit flow;
- artifact bundle independently verifies before reporting;
- no runtime, YAML, adapter, canonical model, optimizer-semantic, or RegimeV2
  change;
- no further request or tracker trial.

## Validation Checklist After Execution

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2 \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

/Users/aloobhujia/.local/bin/ruff check \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_retry_v2_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py

git diff --check
```

Reindex codebase-memory and report project, nodes, edges, status,
`run_phase_i_evaluation` callers, and changed-file scope.

## Explicit Non-Goals

Do not:

- retry v1 or reuse its root;
- make more than one v2 request;
- change policy/objective version to v2;
- modify BinanceNativeAdapter;
- implement pagination;
- use a local alternative dataset;
- widen or rerank the grid;
- retune after validation or holdout;
- change YAML or runtime state;
- begin tracker, interaction, MTF, RegimeV2, or strategy work;
- interpret structural metrics as trading performance.

## Mandatory Completion Report

Return exactly:

- Scope Executed
- Files Changed
- Retry Authorization
- Preserved V1 Evidence
- V2 Execution Identity
- Persistence Remediation
- Pre-Network Validation
- Data Request
- Raw Evidence Persistence
- Data Preflight
- Resolved Config
- Outcome Policy
- Fold Plan
- Search Grid
- Objective
- Validation Results
- Holdout Handling
- Verified Artifact Bundle
- Candidate Metrics
- Parameter-Effect Audits
- Recommendation
- Runtime And Regime Isolation
- Tests
- Codebase-Memory
- Known Gaps
- Next Handoff

Write:

```text
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
```

Stop after the v2 attempt. Do not begin the tracker trial.
