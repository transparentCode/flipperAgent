# Architect → Coder: Trendline-Family Saturating-Quality Fresh-Window Trial v1

## Objective

Execute one bounded BTCUSDT 4h fresh-window candidate-stage research trial that evaluates the already approved `fixed_horizon_saturating_v1` family without changing canonical trendline-family code or runtime configuration.

The trial must answer whether a fixed-policy saturating quality gate improves structural reaction quality over an unfiltered threshold-zero candidate control on a new source window that is disjoint from the previously observed 2025-08-01 through 2025-12-01 research window.

This task may select one **research finalist horizon** only if it passes the frozen validation gates and the untouched holdout. Even a passing research decision authorizes only a later planner-reviewed canonical-design phase. It does not authorize YAML mutation, runtime promotion, tracker research, or RegimeV2 integration.

## Prior Approved Evidence

Read and validate before implementation or network access:

```text
plans/review-to-approval-trendline-family-candidate-quality-normalization-study-v1.md

artifacts/trendline_family_candidate_quality_normalization_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Required approved identities:

```text
quality study ID:
trendline-family-candidate-quality-normalization-study_b45c8006cbe5304f36305fb1131e75173f32addc181d3e48e8d5bfd5cb71b0e3

quality source-binding ID:
trendline-family-candidate-quality-normalization-source-binding_483b0f334281e27e7d9d99bf41ce86c5d7839d90148a9d025e1c72ba35e62d94

approved config SHA-256:
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

The approved study established:

- 576 complete matched candidate triplets across lookbacks 120/180/240;
- current quality is lookback-relative;
- the saturating family is deterministic, bounded, monotonic and exactly lookback-invariant;
- no horizon, threshold, runtime method or configuration was selected.

Any identity drift must stop before the network request.

## Scope Boundaries

### In scope

- one Binance USD-M Futures historical request;
- deterministic raw and normalized input persistence;
- one fixed research candidate configuration with lookback 180 and threshold-zero native generation;
- causal threshold-zero candidate-stream generation for validation positions only;
- one unfiltered validation control;
- four predeclared saturating-quality research policies;
- the existing candidate structural-outcome policy;
- deterministic validation selection and one-time holdout opening only after finalist freeze;
- external, content-addressed trial artifacts and independent verification;
- focused and broad regression tests;
- coder-to-review handoff.

### Out of scope

- a second data request or retry;
- pagination, chunking, adapter redesign or fallback data;
- any asset/timeframe/window change;
- any lookback search;
- any score-threshold search;
- linear quality formulas;
- changing `anchor_span_coverage_v1` or canonical fitter/provider behavior;
- editing `src/libs/models/trendline_family/`;
- YAML/config patching;
- tracker, interaction/event, MTF, RegimeV2, signals, selection or runtime work;
- PnL, directional, strategy or trading claims;
- treating an experimental research finalist as a runtime candidate configuration.

## Expected Implementation Scope

Create only:

```text
scripts/run_trendline_family_saturating_quality_fresh_window_trial.py

tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

artifacts/trendline_family_saturating_quality_trials/
  btcusdt_4h_20251201_20260401_saturating_quality_v1/
    execution_scope.json
    input/
      raw_binance_response.csv
      raw_fetch_manifest.json
      normalized_ohlcv.csv
      input_manifest.json
    validation/
      candidate_stream.json
      candidate_stream_manifest.json
      outcome_evidence.json
      baseline_result.json
      trial_results.json
      research_effect_audits.json
      finalist_freeze.json              # only when a finalist exists
    holdout/                            # must not exist without finalist freeze
      candidate_stream.json
      candidate_stream_manifest.json
      outcome_evidence.json
      baseline_result.json
      finalist_result.json
      holdout_open_audits.json
    research_decision.json
    trial_report.md
    bundle_manifest.json

plans/coder-to-review-trendline-family-saturating-quality-fresh-window-trial-v1.md
```

Generated `.codebase-memory/` files may change.

Do not modify the approved quality-study bundle or any earlier trial/report/diagnosis/density artifact.

## Execution Identity

Use exactly:

```text
trial_name: btcusdt_4h_20251201_20260401_saturating_quality_v1
execution_attempt: 1
research_authorization_id: trendline_family_saturating_quality_fresh_window_v1
single_network_request: true
fresh_source_window: true
prior_research_window_end: 2025-12-01T00:00:00Z
runtime_promotion_authorized: false
tracker_authorized: false
regime_authorized: false
```

`execution_scope.json` must content-bind:

- all constants in this handoff;
- approved quality-study and source-binding IDs;
- the exact request;
- config and research-config identities;
- fold plan;
- formula family, horizons and threshold policy;
- outcome policy and objective;
- selection and holdout rules;
- stop/no-retry rules.

Create the root, `input/`, and `execution_scope.json` before constructing or calling the adapter. Reject any pre-existing trial root.

## Fixed Fresh Data Request

Make exactly one call:

```python
BinanceNativeAdapter.get_historical_ohlcv(
    "BTCUSDT",
    "4h",
    since=1764547200000,
    until=1775001600000,
    limit=1000,
)
```

Equivalent contract:

```text
market: Binance USD-M Futures
asset: BTCUSDT
timeframe: 4h
start inclusive: 2025-12-01T00:00:00Z
end exclusive: 2026-04-01T00:00:00Z
expected normalized confirmed rows: 726
first normalized timestamp: 2025-12-01T00:00:00Z
last normalized timestamp: 2026-03-31T20:00:00Z
```

The request authorization is consumed when the adapter method is invoked. On any later failure, preserve the partial evidence and stop. Never make a second request.

Raw response row count may include an end-boundary row. Persist raw bytes before normalization. The normalized contract is exact and must reject:

- row count other than 726;
- timestamps outside `[start, end)`;
- missing 4h intervals;
- duplicates;
- non-UTC or unordered timestamps;
- malformed OHLCV;
- incomplete bars;
- first/last boundary drift.

No pagination is permitted because the expected normalized population is below the request limit.

## Input Persistence Contract

Reuse only safe, pure persistence/validation helpers from the earlier candidate runner, or implement local equivalents in the new script. Do not edit the earlier runner.

Required behavior:

1. persist raw CSV atomically;
2. bind exact request parameters and raw file SHA-256 in `raw_fetch_manifest.json`;
3. normalize only after raw evidence is durable;
4. persist normalized CSV atomically;
5. bind dataset identity, row/timestamp/gap/duplicate/completeness checks and exact normalized SHA-256 in `input_manifest.json`;
6. refuse non-identical overwrite;
7. independently reload normalized bytes before any candidate generation.

## Configuration Contract

Resolve exactly:

```python
resolved_config = TrendlineFamilyConfigResolver.from_path(
    "configs/trendline_family.yaml"
).resolve(asset="BTCUSDT", timeframe="4h")
```

Require:

```text
resolved config hash: da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
model version: trendline_family_v1
config version: 1
candidate lookback: 180
candidate min bars: 40
fractal left/right: 3 / 3
minimum pivots per side: 2
```

Create one immutable **research generation config** in memory only:

```python
research_config = apply_stage_overrides(
    resolved_config,
    stage=OptimizationStage.CANDIDATE_GEOMETRY,
    overrides={"candidate.min_candidate_quality": 0.0},
)
```

Requirements:

- lookback remains exactly 180;
- only `candidate.min_candidate_quality` changes;
- record the derived research config hash;
- never write it to YAML or runtime state;
- all baseline and research policies consume the same threshold-zero native candidate stream.

## Fixed Fold Plan

Build exactly:

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

For 726 normalized rows require exact positions:

```text
fold 0 validation: 252-347
fold 1 validation: 360-455
fold 2 validation: 468-563
planned holdout:   630-725
holdout warmup:    450-629
unallocated gap:   564-629
```

No validation or pre-finalist artifact may read, generate, summarize or infer positions 630-725.

## Candidate Stream Architecture

### Validation stream

After input and fold validation, invoke `NativeDeterministicLineProvider` exactly once for each validation position under `research_config`:

```text
validation provider calls: exactly 288
```

Each generation must use only:

```python
dataset.prefix(position)
```

with `observed_at` equal to the confirmed bar at that position.

Persist every validation record, including:

- fold ID/index and position;
- observed timestamp;
- provider status and reason codes;
- candidate IDs, roles, geometry, anchors and anchor timestamps;
- current diagnostics/coverage;
- path length and quality method;
- exact stream-record ID.

The content-addressed validation stream ID must bind the dataset hash, research config hash, provider identity, fold plan ID, ordered records and evaluated-index hashes.

### Holdout stream

Do not create, calculate paths for, or reference holdout stream files before a validation finalist is frozen.

When and only when a finalist exists, generate the holdout stream once for positions 630-725:

```text
holdout provider calls: exactly 96
```

Baseline and finalist holdout evaluation must share this one immutable stream. They must not call the native provider again.

Expected total provider-call accounting:

```text
no validation finalist: 288
validation finalist frozen: 384
```

Any other total must fail.

## Research Quality Policies

### Baseline control

The baseline is an unfiltered threshold-zero control over the same stream:

```text
policy_id: threshold_zero_candidate_control_v1
accepted candidates: every candidate emitted by a VALID source record
```

This control exists to test whether structural quality filtering adds value. It is not the current runtime configuration and does not alter YAML.

### Primary policies

Evaluate exactly four policies:

```text
formula family: fixed_horizon_saturating_v1
horizon bars: 12, 24, 48, 96
score threshold: 0.50 for every horizon
```

Use exact Decimal arithmetic:

```python
score = anchor_span_bars / (anchor_span_bars + horizon_bars)
accept = score >= Decimal("0.50")
```

Require and persist the exact equivalence:

```text
score >= 0.50  <=>  anchor_span_bars >= horizon_bars
```

This fixed 0.50 policy prevents horizon/threshold confounding. Do not add or tune score thresholds. Do not add horizons.

Require:

- anchor span is a positive exact integer number of 4h bars;
- score lies in `[0, 1)`;
- candidate identity/geometry is never modified;
- only acceptance status changes;
- policy calculations are deterministic and independent of role, fold, empirical distribution, path length, recency and future outcomes.

## Research Trial Contracts

Use the existing immutable optimization contracts where they fit, without modifying them:

- `TrialConfig`;
- `WindowResult`;
- `TrialResult`;
- `ObjectiveSpec`;
- `StageEvaluationSpec`;
- `ObjectiveGate`;
- `FinalistFreeze`;
- `HoldoutOpenAudit`;
- `HoldoutOpenRegistry`.

Create one external research evaluator in the new script. It must consume persisted candidate streams and trial `evaluation_context`; it must never call the native provider.

All baseline and horizon trials share one evaluation specification whose semantic inputs bind:

```text
spec type: candidate_saturating_quality_research_evaluation
spec version: candidate_saturating_quality_fresh_window_v1
source provider identity
research config hash
candidate stream schema version
formula family: fixed_horizon_saturating_v1
allowed horizons: [12, 24, 48, 96]
fixed score threshold: 0.50
baseline control identity
outcome policy
```

Build the baseline and four primary `TrialConfig` values with:

```text
stage: candidate_geometry
parameter_overrides: {}
baseline_config_hash: research_config.resolved_config_hash
seed: 0
```

Use evaluation context only for the research policy identity:

```text
baseline:
  quality_policy_id: threshold_zero_candidate_control_v1

primary:
  quality_policy_id: fixed_horizon_saturating_v1
  horizon_bars: one of 12/24/48/96
  score_threshold: "0.50"
  equivalent_min_anchor_span_bars: same as horizon_bars
```

Exactly four primary trials are authorized.

## Outcome Policy

Reuse the prior semantics exactly:

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

Candidate generation and quality acceptance must occur before future outcomes are read.

The external evaluator may implement the same outcome calculation locally, but focused tests must prove parity with `CandidateGeometryEvaluator` on deterministic fixtures. Do not change the canonical evaluator.

For each policy/fold retain at least:

- source provider status counts;
- accepted candidate IDs and producing bars;
- candidate count and candidates per bar;
- support/resistance counts;
- exact-line future touch rate;
- geometry survival rate;
- reaction quality;
- normalized penetration;
- horizon-unavailable exclusions;
- evaluated-index hash;
- source candidate-stream ID;
- stage output fingerprint;
- forbidden output fingerprint;
- `causality_ok: true`.

The forbidden fingerprint must be identical across baseline and all policies because they consume the same source stream and dataset.

## Objective

Use exactly:

```python
ObjectiveSpec(
    objective_version="candidate_saturating_quality_reaction_btcusdt_4h_v1",
    primary_metric="reaction_quality",
    maximize=True,
    minimum_sample_count=100,
    minimum_fold_coverage=1.0,
    maximum_failure_rate=0.0,
    allowed_degradation=0.0,
    require_comparable_population=True,
)
```

No worst-window floor or extra outcome gate may be added after observing results.

## Research Effect Audits

Because horizon is an external research policy and not a YAML-owned candidate parameter, do not fabricate canonical parameter-effect audits.

Create separate `research_effect_audits.json` entries for each horizon. Recompute them from persisted evidence and require:

- same evaluated-index hashes as baseline;
- same candidate-stream ID as baseline;
- same forbidden output fingerprint as baseline;
- accepted-set/stage-output change relative to baseline;
- no geometry, dataset or source-stream mutation;
- `effect_detected` and `leakage_detected` derived, not asserted.

A horizon with no acceptance effect is not finalist-eligible.

## Validation Finalist Selection

Do not call `select_validation_finalist(...)`, because it requires canonical stage-owned parameter-effect audits.

Implement one external deterministic selector with these predeclared rules.

A horizon is validation-eligible only when:

1. trial status is completed;
2. its objective gate passes against the threshold-zero baseline;
3. research effect is detected;
4. leakage is false;
5. aggregate `reaction_quality` is strictly greater than baseline;
6. worst-fold `reaction_quality` is not lower than baseline worst-fold value because `allowed_degradation=0.0`.

Rank eligible horizons by:

1. aggregate `reaction_quality`, descending;
2. worst-fold `reaction_quality`, descending;
3. semantic trial ID, ascending.

Do not add sample-count, horizon-size or support-density tie-breakers after observing results.

When no horizon is eligible:

- persist `REJECT_NO_VALIDATION_FINALIST`;
- do not create `finalist_freeze.json`;
- do not create `holdout/`;
- stop after artifact verification and reporting.

When a horizon is eligible:

- freeze exactly that validation result with `freeze_validation_finalist(...)`;
- persist `finalist_freeze.json` before any holdout candidate generation;
- only then generate the shared holdout stream.

## Holdout Opening and Research Decision

Use `HoldoutOpenRegistry`, `build_holdout_open_audit(...)`, and `evaluate_holdout_once(...)` for exactly two targets on the one shared holdout stream:

```text
baseline
finalist
```

No non-finalist horizon may access holdout.

The final research decision is:

### `ADVANCE_TO_CANONICAL_DESIGN`

Only when all conditions hold:

- validation finalist was frozen under the declared selector;
- baseline and finalist holdout results both complete;
- both holdout objective gates pass;
- holdout evaluated-index and stream IDs match;
- no leakage is detected;
- finalist holdout `reaction_quality` is strictly greater than baseline holdout;
- finalist holdout worst value is not lower than baseline under zero allowed degradation.

This decision means only that the formula family and frozen horizon deserve a separate canonical-design/parity phase. It is not runtime promotion.

### `REJECT_HOLDOUT_GATE`

Use when a validation finalist exists but any holdout requirement fails.

### `REJECT_NO_VALIDATION_FINALIST`

Use when validation produces no eligible horizon.

Never output `PROMOTE`, apply a config patch, or start tracker work in this task.

## Artifact and Provenance Contract

All JSON must be canonical and deterministic. Every file must be atomically written and non-identical overwrite must reject.

`bundle_manifest.json` must bind at least:

- execution-scope SHA;
- approved quality-study inventory and IDs;
- raw and normalized input hashes;
- dataset and fold-plan IDs;
- resolved and research config hashes;
- validation candidate-stream and outcome-evidence IDs;
- all validation result IDs and research-effect-audit ID;
- finalist freeze and holdout artifacts when present;
- research decision ID;
- Markdown report SHA;
- exact file inventory and bundle ID.

Implement an independent read-only validator that:

1. revalidates the approved quality-study bundle;
2. rehashes every source and trial artifact;
3. reloads normalized input and rederives dataset/fold identities;
4. rederives every saturating score and acceptance decision;
5. reaggregates every validation and holdout metric from persisted stream/outcome evidence;
6. rederives objective gates, effect audits, finalist selection and research decision;
7. proves holdout artifacts are absent without a freeze;
8. proves holdout artifacts bind the freeze when present;
9. rejects nested inventory, result, decision or manifest rebinding;
10. verifies all protected prior sources still match live bytes.

## Protected Source Immutability

Capture before and after exact inventories for:

```text
V1 candidate trial root:          1 file
V2 candidate trial root:         30 files
approved candidate report:        4 files
approved rejection diagnosis:     4 files
approved density study:           4 files
approved quality study:           4 files
configs/trendline_family.yaml
```

All must remain byte-identical.

The new trial root is outside every protected source root.

## Pre-Network Tests and Gates

Before consuming the request authorization, focused tests must prove at minimum:

1. exact request milliseconds, asset, timeframe and limit;
2. exact expected 726-row normalized contract;
3. trial root and `input/` exist before adapter invocation;
4. an existing root rejects without adapter use;
5. approved quality-study/config identity drift rejects;
6. exact fold positions and sealed holdout boundary;
7. research config changes only minimum quality to zero;
8. candidate lookback remains 180;
9. exact formula family, horizons and fixed threshold;
10. `score >= 0.50` equivalence to `span >= H`;
11. exactly four primary policy contexts;
12. objective and outcome-policy identity;
13. external evaluator has no native-provider call path;
14. validation stream generation uses causal prefixes and validation positions only;
15. holdout stream generation rejects before finalist freeze;
16. external selection rules and deterministic tie-break;
17. no canonical source/YAML/runtime write path;
18. raw and normalized persistence is atomic and hash-bound;
19. mocked top-to-bottom execution makes exactly one adapter request.

Run before network:

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab

/Users/aloobhujia/.local/bin/ruff check \
  scripts/run_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1-compile \
  .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

git diff --check
```

Also require before the request:

- the new trial root does not exist;
- all protected inventories match expected live bytes;
- no production/canonical file is changed;
- codebase-memory impact trace confirms the new runner has no runtime caller.

## Execution and Stop Rules

After every pre-network gate passes, execute the runner once.

Stop and preserve evidence on any of:

- request failure;
- persistence failure;
- normalized data preflight failure;
- config/fold/identity drift;
- provider failure or unexpected call count;
- candidate stream validation failure;
- outcome parity failure;
- result/objective/effect-audit failure;
- no validation finalist;
- finalist-freeze failure;
- holdout audit failure;
- independent bundle verification failure;
- report-generation failure.

Never retry the request, widen the window, change thresholds, remove horizons, lower the sample gate, open holdout manually or work around a rejection.

## Post-Execution Validation

Run:

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1 \
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals

/Users/aloobhujia/.local/bin/ruff check \
  scripts/run_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-saturating-fresh-v1-compile \
  .venv/bin/python -m compileall -q \
  scripts/run_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

git diff --check
```

Additionally:

- independently validate the persisted bundle read-only;
- independently rederive the final research decision;
- verify exact request count and provider-call accounting;
- verify protected source inventories before/after;
- reindex codebase-memory and report node/edge counts and `ready` status;
- verify the runner has no production runtime caller.

## Acceptance Criteria

The task passes only when:

1. exactly one Binance request is made;
2. exact 726 confirmed bars pass preflight;
3. the prior approved research chain remains byte-identical;
4. validation candidates are generated causally exactly once per validation bar;
5. baseline and four policies use the same immutable validation stream;
6. fixed threshold 0.50 and horizons 12/24/48/96 remain unchanged;
7. objective/outcome semantics remain frozen;
8. holdout remains sealed unless a finalist is frozen;
9. only baseline and the frozen finalist access one shared holdout stream;
10. final decision is independently rederived and explicitly research-only;
11. no canonical, YAML, runtime, tracker or Regime work occurs;
12. all validation commands pass.

## Explicit Non-Goals

Do not:

- select or tune another threshold;
- tune lookback;
- add another formula family;
- modify candidate geometry;
- implement the saturating formula in canonical fitter/provider code;
- create a YAML patch;
- call the trial result runtime-ready;
- start tracker evaluation;
- use RegimeV2;
- interpret structural reaction metrics as profitability.

## Coder Handoff

Write:

```text
plans/coder-to-review-trendline-family-saturating-quality-fresh-window-trial-v1.md
```

Include:

- exact files created;
- approved source identities and protected inventories;
- request authorization and single-call proof;
- raw/normalized data evidence;
- dataset, config and fold identities;
- validation/holdout provider-call accounting;
- candidate-stream identities;
- baseline and four policy results by fold;
- research effect audits;
- finalist selection or no-finalist reason;
- holdout audit/decision when applicable;
- bundle IDs and hashes;
- all test counts;
- codebase-memory status;
- known gaps;
- explicit confirmation that no canonical/YAML/runtime/tracker/Regime work occurred.

Stop after the handoff. Do not begin canonical implementation or tracker research.
