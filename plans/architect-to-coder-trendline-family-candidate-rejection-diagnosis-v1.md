# Architect → Coder: Trendline-Family Candidate Rejection Diagnosis v1

## Objective

Diagnose why the approved BTCUSDT 4h candidate/geometry Phase-I trial produced no validation finalist.

Use only the existing local, verified evidence:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/

artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

The task must explain, with validation-only causal replay evidence:

- why the baseline and five of six primary configurations produced zero accepted candidates;
- how much of the scarcity came from insufficient data, pivot scarcity, fitting failure, or the minimum-quality gate;
- what pre-threshold candidate-quality distributions existed behind `rejected_low_quality_candidates`;
- why the one productive configuration still failed the stage objective;
- what exact evidence should shape the next research plan.

This is diagnosis, not optimization. Do not change any parameter, objective, gate, artifact, report, or runtime configuration.

## Fixed Source Identity

Require the existing source bundle to validate before any diagnostic replay.

```text
asset:                 BTCUSDT
market:                Binance USD-M Futures
timeframe:             4h
start:                 2025-08-01T00:00:00Z
end:                   2025-12-01T00:00:00Z
confirmed rows:        732
dataset hash:          trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53
resolved config hash:  da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
Phase-I run ID:        trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7
report ID:             trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41
recommendation ID:     trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc
winner:                None
decision:              REJECT
rationale:             no_validation_trial_passed_stage_owned_gates
```

Any mismatch must stop the task. Do not repair, regenerate, or reinterpret the source artifacts.

## Scope Boundaries

### In scope

- read-only validation of the existing report and Phase-I bundles;
- rebuilding the immutable 732-row dataset from the persisted normalized CSV;
- resolving the current BTCUSDT/4h YAML config and requiring the original resolved-config hash;
- replaying the canonical candidate provider on the exact three validation windows only;
- baseline plus the exact six persisted primary trial configurations only;
- diagnostic-only pre-threshold inspection for bars whose actual result is `rejected_low_quality_candidates`;
- deterministic evidence aggregation and an external diagnosis report;
- focused tests and broad non-interference validation.

### Out of scope

- network access or Binance calls;
- any new asset, timeframe, date range, or data request;
- `run_phase_i_evaluation`, `run_stage_grid`, optimization, trial selection, or reranking;
- `CandidateGeometryEvaluator` or new future-outcome calculation;
- holdout access, holdout replay, holdout inference, or holdout metrics;
- adding parameter values outside the baseline and exact six persisted trials;
- changing the search grid, objective, minimum sample gate, outcome policy, or recommendation;
- canonical provider, pivot, fitting, candidate, optimization, artifact, or report-code changes;
- YAML writes or runtime promotion;
- tracker, interaction/event, MTF, RegimeV2, signal, selection, strategy, risk, execution, or portfolio work;
- PnL, trade simulation, signal interpretation, or live-trading claims.

## Expected Implementation Scope

Create only:

```text
scripts/diagnose_trendline_family_candidate_rejection.py

tests/scripts/test_trendline_family_candidate_rejection.py

artifacts/trendline_family_candidate_diagnostics/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_binding.json
    rejection_diagnosis.json
    rejection_diagnosis.md
    diagnosis_manifest.json

plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-v1.md
```

Generated codebase-memory index files may change. Do not modify any existing canonical model or report implementation.

## Mandatory Read Boundaries

Use the existing canonical validation and contracts:

```python
validate_report_bundle(<external report root>)
load_verified_phase_i_artifacts(<v2 phase_i root>)
ImmutableHistoricalFrame(...)
TrendlineFamilyConfigResolver.from_path(...).resolve(asset="BTCUSDT", timeframe="4h")
apply_stage_overrides(...)
NativeDeterministicLineProvider.generate(...)
```

The diagnosis script must not import or call:

```text
BinanceNativeAdapter
get_historical_ohlcv
run_phase_i_evaluation
run_stage_grid
run_validation_trial
CandidateGeometryEvaluator
evaluate_holdout_once
open/freeze holdout helpers
tracker APIs
```

## Source Immutability Contract

Before execution, capture sorted relative-path, byte-size, and SHA-256 inventories for:

- the v1 trial root;
- the v2 trial root;
- the four approved external report files;
- `configs/trendline_family.yaml`.

After execution, recompute all inventories and require byte equality.

All diagnosis outputs must be outside the source trial/report roots.

## Dataset And Fold Contract

Rebuild the dataset from:

```text
<v2 root>/input/normalized_ohlcv.csv
```

Require:

- all existing input-manifest and CSV hash checks;
- exactly 732 complete UTC rows;
- exact first/last timestamps and four-hour spacing;
- exact dataset hash;
- exact Phase-I fold-plan data hash.

Use only the three persisted validation windows:

```text
fold count:             3
validation bars/fold:  96
total validation bars: 288
purge bars:            12
label horizon:         12
planned holdout bars:  96
```

The provider replay must never request a position inside the planned holdout window.

Assert the exact replay counts:

```text
configurations:              7  # baseline + six primary configurations
actual provider generations: 7 * 288 = 2016
```

Additional diagnostic shadow calls are allowed only for actual low-quality rejections, as defined below.

## Configuration Contract

Resolve the baseline from:

```text
configs/trendline_family.yaml
```

Require its resolved hash to equal the fixed source identity.

Build exactly these configuration identities:

1. Baseline with no overrides.
2. The six primary trial override maps loaded from the verified Phase-I bundle.

Require the six override maps to equal the Cartesian set:

```text
candidate.lookback_bars in {120, 180, 240}
candidate.min_candidate_quality in {0.30, 0.40}
```

Do not enumerate a new search space. The verified trial IDs and override maps are the authority.

For every actual configuration, persist:

- label (`baseline` or primary trial ID);
- exact overrides;
- resolved config hash;
- lookback, minimum bars, fractal left/right, minimum pivots, and quality threshold;
- source result ID and objective-gate identity when applicable.

## Actual Provider Replay

For every configuration and every validation position:

```python
provider.generate(
    dataset.prefix(position),
    asset="BTCUSDT",
    timeframe="4h",
    observed_at=<timestamp at position>,
    config=<exact resolved configuration>,
)
```

This must remain point-in-time and confirmed-bar-only.

Record per bar:

- config/trial identity;
- fold ID and observed timestamp;
- provider status;
- reason codes;
- provider metadata already returned by the canonical provider;
- accepted candidate count and roles when status is valid;
- accepted candidate quality, coverage, path length, anchor IDs, and anchor timestamps.

Aggregate a status funnel by configuration and fold for every canonical status, including:

- insufficient data;
- no confirmed pivots;
- no valid fitted paths;
- rejected low quality;
- valid;
- provider config error.

The aggregated actual status counts must exactly reconcile to the persisted `provider_status_counts` for the corresponding baseline or primary trial. Any mismatch must stop the task.

## Diagnostic-Only Pre-Threshold Replay

The existing provider does not expose rejected fitted-line quality values. For an actual bar whose status is exactly:

```text
rejected_low_quality_candidates
```

perform one diagnostic-only shadow provider call with a cloned configuration where only:

```text
candidate.min_candidate_quality = 0.0
```

is changed.

Strict rules:

- this is instrumentation, not a trial;
- do not calculate structural outcomes or objective metrics from shadow candidates;
- do not rank, select, or recommend the shadow configuration;
- preserve every other resolved field exactly;
- bind the source config hash, shadow config hash, and exact diagnostic delta;
- assert the actual low-quality metadata `fitted_paths` equals the shadow candidate count;
- require the shadow result to be valid and all exposed candidates to have quality below the actual threshold;
- stop if any invariant fails.

For each shadow candidate capture:

- role;
- normalized quality and coverage;
- actual acceptance threshold;
- absolute threshold gap;
- path length;
- anchor timestamps and elapsed anchor span;
- source-line index;
- quality method.

Do not call the shadow path for any other actual provider status.

## Required Diagnosis Sections

### 1. Source and execution identity

- dataset/config/run/report/recommendation IDs;
- source inventories and hashes;
- validation-window IDs and timestamp boundaries;
- exact actual and shadow call counts;
- explicit holdout exclusion proof.

### 2. Configuration matrix

Baseline and six verified primary configurations, canonically ordered by:

```python
(canonical_json(parameter_overrides), trial_id)
```

### 3. Status funnel

Per configuration and fold:

- count and ratio for every provider status;
- reconciliation against persisted Phase-I counts;
- first/last timestamp for each non-empty status category.

### 4. Low-quality rejection decomposition

Per configuration and fold:

- low-quality rejected bar count;
- fitted/shadow candidate count;
- support/resistance counts;
- min, max, mean, median, and deterministic quantiles of pre-threshold quality;
- threshold-gap distribution;
- near-miss counts within `0.01`, `0.02`, `0.05`, and `0.10` of the actual threshold;
- path-length and anchor-span summaries;
- quality-method identity.

### 5. Exact parameter contrasts

Descriptive paired comparisons only:

- `0.30` versus `0.40` at the same lookback;
- `120` versus `180` and `240` at the same threshold;
- baseline `180/0.35` versus exact neighboring persisted configurations.

Report:

- bars where status changed;
- valid-to-rejected and rejected-to-valid counts;
- changes in accepted-candidate count;
- changes in maximum pre-threshold quality where both sides expose comparable candidates.

Do not label these as causal effects beyond the fixed observed dataset.

### 6. Productive-trial gate deficit

Identify the only configuration with defined persisted `reaction_quality` and report from verified Phase-I evidence:

- trial/result identity;
- per-fold and aggregate reaction-quality values;
- exact sample count and required minimum sample count;
- sample deficit;
- defined-primary-fold count and required fold count;
- fold-coverage ratio;
- failure rate;
- outcome-horizon exclusions;
- objective-gate rejection reasons;
- accepted/producing bar and candidate counts.

Do not recompute reaction outcomes. Use only verified persisted evidence.

### 7. Evidence-based observations

Separate observations from hypotheses.

Allowed observations must quote counts or distributions, for example:

- scarcity occurs before the quality gate versus at the quality gate;
- quality values cluster materially below or close to thresholds;
- lookback changes alter pivot/path availability or anchor-span coverage;
- the productive configuration has insufficient labeled samples despite non-zero candidate production.

Potential hypotheses may be listed only as questions for the next planner stage, such as:

- whether `anchor_span_coverage_v1` is too restrictive for this timeframe/window;
- whether the minimum-quality grid is misaligned with the observed quality distribution;
- whether the objective minimum sample gate requires a longer validation dataset;
- whether lookback and pivot settings need a separately approved structural-density trial.

Do not issue a parameter recommendation or promotion decision.

## Output Contract

Write deterministic external outputs:

```text
source_binding.json
rejection_diagnosis.json
rejection_diagnosis.md
diagnosis_manifest.json
```

Requirements:

- canonical ordering;
- no wall-clock fields in semantic identities;
- content-addressed diagnosis ID derived from the complete semantic diagnosis payload;
- manifest binds source inventories, report ID, Phase-I run ID, dataset/config identities, diagnosis ID, and SHA-256 of JSON/Markdown;
- atomic writes;
- existing identical output may validate idempotently;
- existing non-identical output must reject before writing any file.

## Tests

Add focused coverage proving:

1. No network, Phase-I runner, evaluator, holdout, or tracker boundary exists.
2. Source report and Phase-I bundles must validate before diagnosis.
3. Baseline plus exactly six primary configurations are used.
4. Only validation positions are replayed; holdout overlap rejects.
5. Actual replay count is exactly 2016.
6. Actual status totals reconcile to persisted provider-status counts.
7. Shadow replay occurs only for actual low-quality rejections.
8. Shadow config differs only in `candidate.min_candidate_quality=0.0`.
9. Shadow candidate count/quality invariants reject tampering.
10. Quality quantiles, threshold gaps, and near-miss counts are deterministic.
11. Productive-trial sample deficit is sourced from verified persisted evidence.
12. Reordered trial inputs produce the same diagnosis payload and ID.
13. Source/report/YAML bytes remain unchanged.
14. Non-identical output overwrite rejects.
15. No synthetic holdout, PnL, ranking, or promotion fields appear.

Use temporary copied sources for destructive tests. Never alter the real trial or report roots.

## Stop Conditions

Stop without broadening scope if:

- any source identity or inventory check fails;
- current resolved YAML no longer matches the fixed config hash;
- fold boundaries or primary trial membership differ;
- actual status counts do not reconcile with persisted evidence;
- a diagnostic shadow call violates its invariants;
- any replay position enters the holdout;
- canonical model/provider changes appear necessary;
- the existing evidence bundle needs regeneration;
- a new parameter value or objective would be required.

Preserve bounded failure evidence outside source roots and return for planner review.

## Implementation Order

1. Read the approved evidence-report integrity handoffs and this plan.
2. Confirm codebase-memory is ready and inspect provider/config helper callers.
3. Capture source/report/YAML inventories.
4. Add pure source loading, config reconstruction, replay, aggregation, and output helpers.
5. Add focused fixture and adversarial tests.
6. Run focused tests and static checks.
7. Execute the diagnosis once against existing local evidence.
8. Independently reload and validate the diagnosis bundle.
9. Recompute source/report/YAML inventories and prove byte equality.
10. Run broader trendline-family and passive isolation tests.
11. Reindex codebase-memory.
12. Write the coder-to-review handoff and stop.

## Acceptance Criteria

- no network or new market data;
- no Phase-I, outcome, holdout, or tracker execution;
- exact 732-row dataset and original config identity;
- exactly 7 configurations and 2016 actual validation-only provider calls;
- exact status reconciliation with persisted Phase-I evidence;
- pre-threshold diagnostics only for actual low-quality rejections;
- deterministic explanation of candidate scarcity and productive-trial gate failure;
- content-addressed external diagnosis bundle;
- all source/report/YAML bytes unchanged;
- no parameter recommendation, promotion, or runtime claim;
- focused and broad tests pass.

## Validation Checklist

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_rejection.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

/Users/aloobhujia/.local/bin/ruff check \
  scripts/diagnose_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_rejection.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_rejection_diagnosis_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/diagnose_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_rejection.py

git diff --check
```

Confirm codebase-memory is reindexed and ready. Confirm the diagnosis script has no production runtime caller.

## Mandatory Completion Report

Return exactly:

- Scope Executed
- Files Changed
- Source Identity
- Source Immutability
- Dataset And Fold Boundaries
- Configuration Matrix
- Replay Call Accounting
- Status Reconciliation
- Low-Quality Decomposition
- Parameter Contrasts
- Productive-Trial Gate Deficit
- Evidence-Based Observations
- Diagnosis Bundle Identity
- Runtime And Regime Isolation
- Tests
- Codebase-Memory
- Known Gaps
- Next Handoff

Write:

```text
plans/coder-to-review-trendline-family-candidate-rejection-diagnosis-v1.md
```

Stop after this diagnosis. Do not start a new candidate trial or tracker work.
