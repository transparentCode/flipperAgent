# Architect → Coder: Trendline-Family Candidate/Geometry Real-Data Trial v1

## Objective

Execute the first bounded real-data candidate/geometry evaluation for the approved canonical trendline-family model.

This task must produce one reproducible, verified Phase-I artifact bundle for:

```text
asset:      BTCUSDT
market:     Binance USD-M Futures
timeframe:  4h
start:      2025-08-01T00:00:00Z
end:        2025-12-01T00:00:00Z
```

The experiment must answer only candidate/geometry questions:

- whether the canonical provider produces usable candidate coverage;
- whether candidate reaction/survival/touch evidence is stable across walk-forward folds;
- whether a small candidate-owned parameter grid improves validation and untouched holdout evidence;
- whether provider failures, candidate density, balance, and penetration remain acceptable.

Do not infer trading profitability or runtime readiness.

## Scope Boundaries

### In scope

- one Binance USD-M Futures historical-kline request through `BinanceNativeAdapter`;
- one bounded BTCUSDT 4h dataset;
- strict UTC, confirmed-bar, duplicate, gap, and row-count validation;
- resolving the existing non-smoke config from `configs/trendline_family.yaml`;
- `CandidateGeometryEvaluator` with a versioned `CandidateOutcomePolicy`;
- one deterministic six-trial candidate-owned search grid;
- three walk-forward validation folds and one untouched holdout;
- Phase-I artifact writing and independent artifact verification;
- a compact human-readable trial report;
- tests for the new research runner/preflight only.

### Out of scope

- Binance adapter redesign or pagination;
- any second asset, timeframe, date range, or rerun with a changed grid;
- tracker, interaction/event, MTF, RegimeV2, signal, selection, strategy, risk, execution, or portfolio work;
- PnL, trade simulation, transaction costs, or signal interpretation;
- runtime YAML mutation or config-patch application;
- automatic promotion;
- notebook redesign;
- multi-year history;
- holdout-driven retuning.

## Affected Symbols / Modules / Flows

Read first:

- `.agents/skills/quant-coder/SKILL.md`
- `plans/trendline-family-phase-i-approval.md`
- `plans/coder-to-review-trendline-family-research-lab-final-remediation-v2.md`
- `src/apps/ingestion_app/adapters/binance_native.py`
- `src/libs/models/trendline_family/config_loader.py`
- `src/libs/models/trendline_family/config_resolver.py`
- `src/libs/models/trendline_family/optimization/candidate_optimizer.py`
- `src/libs/models/trendline_family/optimization/folds.py`
- `src/libs/models/trendline_family/optimization/runner.py`
- `src/libs/models/trendline_family/research_lab/replay.py`
- `src/libs/models/trendline_family/research_lab/artifacts.py`

Expected implementation scope:

```text
scripts/run_trendline_family_candidate_geometry_trial.py

tests/scripts/test_trendline_family_candidate_geometry_trial.py

artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/
    input/
    phase_i/
    trial_report.md

plans/coder-to-review-trendline-family-candidate-real-data-trial-v1.md
```

A slightly different focused test path is acceptable. Do not modify canonical model or optimization semantics unless an independently reproducible blocker makes execution impossible; stop and report instead.

## Data Contract

Use only:

```python
BinanceNativeAdapter.get_historical_ohlcv(
    "BTCUSDT",
    "4h",
    since=<2025-08-01T00:00:00Z milliseconds>,
    until=<2025-12-01T00:00:00Z milliseconds>,
    limit=1000,
)
```

This must be one request. Do not paginate or chunk.

Normalize with the approved research helper:

```python
normalize_binance_ohlcv(..., timeframe="4h", closed_before=end_utc)
```

Then build:

```python
ImmutableHistoricalFrame(asset="BTCUSDT", timeframe="4h", ...)
```

Mandatory preflight:

- UTC-aware start/end;
- exact timeframe identity `4h`;
- exact expected confirmed row count: `732`;
- first timestamp: `2025-08-01T00:00:00Z`;
- last timestamp: `2025-11-30T20:00:00Z`;
- strictly increasing unique timestamps;
- every adjacent timestamp exactly four hours apart;
- no missing OHLCV values;
- finite positive OHLC prices;
- `high >= max(open, close)` and `low <= min(open, close)`;
- non-negative volume;
- every retained row confirmed/complete;
- no row opening before start or closing after end.

Any preflight failure must stop before fold construction or holdout access.

Persist the exact normalized input and metadata under the trial root. Prefer deterministic CSV plus a JSON manifest if Parquet dependency behavior is uncertain. The input manifest must include:

- asset, market, timeframe, start/end;
- adapter class identity;
- request parameters including `limit=1000`;
- row count and UTC first/last timestamps;
- dataset hash;
- resolved config version/hash;
- SHA-256 of the persisted input file.

Do not overwrite a non-identical existing input artifact.

## Configuration Contract

Resolve the existing config without runtime overrides:

```python
TrendlineFamilyConfigResolver.from_path(
    "configs/trendline_family.yaml"
).resolve(asset="BTCUSDT", timeframe="4h")
```

Mandatory checks:

- config is not `research_smoke_v1`;
- provenance is not the deterministic smoke fixture;
- asset/timeframe are exactly BTCUSDT/4h;
- model is enabled;
- baseline candidate values match the currently resolved YAML identity and are reported, not assumed silently.

Expected current baseline values for planning purposes:

```text
candidate.lookback_bars          = 180
candidate.min_bars               = 40
candidate.fractal_left_bars      = 3
candidate.fractal_right_bars     = 3
candidate.min_pivots_per_side    = 2
candidate.min_candidate_quality  = 0.35
```

If the actual resolved values differ, stop and report config drift before running the trial. Do not edit YAML.

## Outcome Policy

Use exactly:

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

This is offline structural labeling only. It must never be passed into runtime model decisions.

## Fold Plan

Use exactly:

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

Persist and report all fold and holdout UTC boundaries.

The purge must cover the 12-bar structural outcome horizon. The holdout must remain unopened until the Phase-I runner has frozen a validation finalist.

## Search Grid

Use only candidate-owned parameters:

```python
search_space = {
    "candidate.lookback_bars": (120, 180, 240),
    "candidate.min_candidate_quality": (0.30, 0.40),
}
```

This is exactly six primary trials:

```text
maximum_trial_count = 6
seed = 0
```

Do not widen, shrink, or rerun the grid after seeing validation or holdout evidence.

## Objective

Use exactly:

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

Do not add a guessed worst-window floor before observing the first real distribution.

Secondary review metrics are mandatory but must not rerank trials outside the approved Phase-I recommendation logic:

- `candidate_coverage_ratio`;
- `candidate_count`;
- `candidates_per_bar`;
- `support_balance`;
- `resistance_balance`;
- `provider_failure_rate`;
- `exact_line_future_touch_rate`;
- `geometry_survival_rate`;
- `reaction_quality`;
- `normalized_penetration`;
- excluded outcome count/reasons;
- provider status counts;
- runtime seconds and evaluated-bar counts.

## Execution Contract

Construct:

```python
evaluator = CandidateGeometryEvaluator(
    dataset=dataset,
    outcome_policy=outcome_policy,
)
```

Run exactly once with:

```python
run_phase_i_evaluation(
    stage=OptimizationStage.CANDIDATE_GEOMETRY,
    dataset=dataset,
    fold_plan=fold_plan,
    baseline_config=resolved_config,
    objective=objective,
    search_space=search_space,
    evaluator=evaluator,
    output_root=<trial_root>/"phase_i",
    maximum_trial_count=6,
    seed=0,
    open_holdout=True,
    codebase_project="Users-aloobhujia-flipperAgent",
)
```

Do not provide a hand-written evaluator specification when the concrete evaluator can supply its own identity.

After execution, independently load and verify the persisted bundle through:

```python
load_verified_phase_i_artifacts(<trial_root>/"phase_i")
```

The report must use verified persisted artifacts, not only in-memory return values.

## Trial Report

Write `trial_report.md` containing:

1. Dataset identity and preflight evidence.
2. Resolved config identity and baseline candidate values.
3. Outcome-policy identity.
4. Fold/holdout boundaries.
5. Exact requested primary trial IDs and completion status.
6. Baseline validation metrics by fold and aggregate.
7. Every trial’s overrides, status, per-fold metrics, aggregate, worst-window values, and rejection reasons.
8. Every marginal counterfactual and parameter-effect/leakage audit.
9. Frozen finalist identity, or explicit reason no finalist exists.
10. Baseline and finalist untouched-holdout metrics when holdout was opened.
11. Provider status and failure counts.
12. Candidate density and support/resistance balance.
13. Final persisted recommendation: `PROMOTE`, `HOLD`, or `REJECT`.
14. A separate reviewer-facing assessment of residual risks without changing the persisted recommendation.
15. Explicit statement that no config or runtime promotion occurred.

Do not claim model quality from one asset/window. Do not convert structural metrics into trading claims.

## Stop Conditions

Stop without broadening the task when any of these occurs:

- Binance returns anything other than the exact bounded one-request dataset;
- preflight row count, timestamp, gap, duplicate, completeness, or OHLCV validation fails;
- resolved config differs from the expected approved baseline;
- search enumeration is not exactly six primary trials;
- any trial tries to override a non-candidate-owned parameter;
- artifact verification fails;
- holdout identity/audit verification fails;
- runtime, YAML, RegimeV2, signal, or selection files would need modification;
- a canonical optimization semantic bug is discovered.

If no validation finalist exists, preserve all artifacts, report the result, and stop. Do not change the objective, grid, dataset, or thresholds.

Once holdout has been opened, do not rerun this experiment with changed inputs in the same task.

## Implementation Order

1. Confirm codebase-memory is ready and inspect callers for the candidate evaluator/runner.
2. Add the narrow fixed-scope research runner and pure preflight helpers.
3. Add mocked tests proving request construction, exact normalization/preflight, config rejection, fixed grid/folds/objective, and no YAML mutation.
4. Run focused tests and static checks before network access.
5. Execute the single remote fetch.
6. Persist and hash the normalized input.
7. Execute the Phase-I run once.
8. Verify persisted artifacts independently.
9. Write the trial report and coder-to-review handoff.
10. Reindex codebase-memory and stop.

## Acceptance Criteria

- one exact Binance USD-M Futures request only;
- exactly 732 valid confirmed BTCUSDT 4h bars;
- non-smoke resolved config from current YAML;
- exact outcome policy, fold plan, objective, and six-trial grid above;
- validation finalist selected only from validation evidence;
- holdout opened only through the approved freeze/audit path;
- complete verified artifact bundle;
- no missing, extra, or retyped requested trials;
- parameter-effect audits and counterfactuals present for every override;
- trial report generated from verified persisted evidence;
- no runtime/config/RegimeV2 changes;
- no second experiment or parameter adjustment.

## Validation Checklist

Run focused runner tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py \
  -q -p no:cacheprovider
```

Run optimization and research support tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider
```

Run full trendline-family tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider
```

Run family plus adapters/projected runtime:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider
```

Run passive non-interference:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider
```

Run static checks:

```bash
ruff check \
  scripts/run_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_real_trial_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_candidate_geometry_trial.py

git diff --check
```

Verify:

- `configs/trendline_family.yaml` is byte-identical before/after;
- no runtime module imports the trial runner;
- no RegimeV2, signal, selection, strategy, risk, execution, or portfolio file changed;
- `run_phase_i_evaluation` still has no production callers;
- codebase-memory is reindexed and ready.

## Explicit Non-Goals

Do not:

- implement Binance pagination;
- fetch more than this one bounded window;
- run another asset/timeframe;
- change canonical model or optimization semantics;
- tune tracker, interaction/event, MTF, or regime parameters;
- open holdout outside the approved Phase-I runner;
- apply a config patch;
- change `configs/trendline_family.yaml`;
- activate anything in runtime;
- interpret results as a trading signal or PnL claim.

## Mandatory Completion Report

Return exactly these sections:

- Scope Executed
- Files Changed
- Data Request
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

The next handoff must be:

```text
plans/coder-to-review-trendline-family-candidate-real-data-trial-v1.md
```

Stop after this one trial. Do not begin the tracker trial.