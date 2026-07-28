---
goal: Causal trendline adequacy evaluation foundation
stage: architect-to-coder
date_created: 2026-07-26
last_updated: 2026-07-26
owner: quant-coder
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, trendlines, adequacy, l2d1]
---

# L2-D1 — Causal Trendline Adequacy Evaluation Foundation

## 1. Objective and evidence

Build package-local, deterministic measurement contracts on top of the committed
`workflows.research` replay/evidence APIs. L2-D1 freezes evaluation scope,
eligibility, observation units, availability rules, cohort identity, metric
definitions, decision-rule contracts, and naive/null baseline definitions.

Live checkpoint:

```text
branch: research/trendlines-adequacy-v1
HEAD:   080277cf33dc357aefd231438a5bbc31369d5307
```

Existing causal inputs:

```text
PreparedTrendlineResearchRun
PreparedTrendlineResearchReplay
TrendlineReplayWindow
TrendlineResearchReplaySpec
TrendlineReplayPoint
SnapshotSummaryRow
LineEvidenceRow
RayEvidenceRow
TrendlineResearchEvidenceBundle
```

## 2. Scope

Add a source-agnostic package under:

```text
src/libs/models/trendlines/workflows/research/adequacy/
```

Suggested files:

```text
__init__.py
contracts.py
metrics.py
baselines.py
```

Add focused offline tests under:

```text
src/libs/models/trendlines/tests/research_adequacy/
```

Update research/workflow documentation and add a coder-to-orchestrator handoff.

## 3. Non-goals and protected scope

Do not modify:

```text
Fractal or RDP algorithms
fitters
boundary geometry
signals
snapshot/history semantics
source, availability, dataset or replay identity seams
Binance bridge or provider adapters
RegimeV2
Trendline V2
YAML
research notebook or viewer
L2-C artifacts
```

Do not:

```text
make provider calls
run optimisation or sensitivity search
generate model-quality conclusions
implement D2 structural stability metrics
implement D3 interaction outcomes
implement D4 baseline execution
implement D5 robustness studies
add promotion/trading-activation status
```

L2-D1 may compute descriptive eligibility/coverage counts only. It must not
label a model adequate or inadequate.

## 4. Frozen contracts

Define immutable, typed contracts with strict bool/integer/finite validation.
Do not accept model parameter dictionaries.

### 4.1 Study scope

Add a frozen `TrendlineAdequacyWindow` containing:

```text
timeframe
start_position
end_position
minimum_warmup_bars
minimum_history_points
```

Positions and counts are non-negative non-boolean integers. The window must be
ordered and must fit the corresponding replay window. Minimum warm-up must not
exceed actual replay warm-up. Eligible coordinates come only from recorded
replay points inside this range; unrecorded positions are never synthesized.

Add enums for:

```text
TrendlineAdequacyAvailabilityPolicy
    CAUSAL_PREFIX_ONLY

TrendlineInvalidPointTreatment
    RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS

TrendlineObservationUnit
    FITTED_LINE
    BOUNDARY_RAY

TrendlineAdequacyOutcome
    ADEQUATE_FOR_FURTHER_RESEARCH
    STRUCTURALLY_STABLE_BUT_NO_UTILITY
    UTILITY_NOT_BETTER_THAN_NAIVE_NULL
    INSUFFICIENT_COVERAGE
    EXCESSIVE_GEOMETRY_CHURN
    INCONCLUSIVE_INSUFFICIENT_EVIDENCE
```

The outcome enum is vocabulary only. L2-D1 never selects an outcome.

### 4.2 Frozen metric definitions

Add frozen `TrendlineAdequacyMetricDefinition` with:

```text
name
phase
unit
direction
requires_future_rows
description
```

Provide a deterministic catalogue covering foundation, structural-stability,
interaction-utility, baseline-comparison and robustness phases. Definitions
must state whether future rows are required; no metric implementation beyond
descriptive eligibility/coverage summary is authorized in L2-D1.

Add frozen `TrendlineAdequacyDecisionRule` with:

```text
metric_name
operator
threshold
minimum_observation_count
```

Thresholds must be explicit finite values supplied by the study configuration;
no numeric default or hidden fallback is allowed. Rules are identity inputs,
not an evaluation result.

### 4.3 Frozen study configuration

Add `TrendlineAdequacyStudyConfig` containing:

```text
study_name
ordered adequacy windows
metric names selected from the frozen catalogue
ordered decision rules
ordered baseline definitions
line observation unit
ray observation unit
invalid-point treatment
availability policy
semantics version
```

Expose deterministic `study_config_id` built with the existing canonical SHA-256
identity seam. The serialised config must contain no wall-clock time, DataFrame,
provider state or model parameter mapping.

### 4.4 Baseline/null definitions

Add frozen `TrendlineAdequacyBaselineSpec` and a kind enum for:

```text
RANDOM_VALID_PIVOT_PAIR
RECENT_EXTREMA
HORIZONTAL_SUPPORT_RESISTANCE
TIME_SHIFTED_GEOMETRY
ROLE_SHUFFLED_GEOMETRY
DENSITY_MATCHED_NULL
```

Each definition must bind:

```text
name
kind
seed when randomized
repetition count
preserved attributes
causal-prefix-only policy
```

Randomized definitions require an explicit non-boolean seed. Repetition count
must be a positive non-boolean integer. Definitions must reject future-data
permission. Baseline IDs must be deterministic. L2-D1 defines them only; it
does not generate or execute null geometry.

## 5. Cohort and observation identity

Add frozen `TrendlineAdequacyCohort` binding:

```text
study_config_id
asset
ordered timeframes
preparation_id
dataset_id
research_configuration_id
replay_id
replay specification
per-timeframe source IDs
per-timeframe availability IDs
timestamp semantics
per-timeframe availability provenance
cohort semantics version
```

Expose deterministic `cohort_id`. Build it only after verifying replay belongs
to prepared run and study windows match prepared/replay timeframe order.

Add frozen `TrendlineAdequacyObservation` containing only compact causal
identity/timing and descriptive counts:

```text
cohort_id
timeframe
position
event_at
available_at
replay_point_id
content_id
source_id
checkpoint_id
fit_valid
eligibility state/reason
history depth
support/resistance line counts
support/resistance ray counts
```

Never embed full frames. Never reorder or synthesize replay points.

## 6. Causal validation and eligibility

Provide pure builders similar to:

```python
build_adequacy_cohort(prepared, replay, study_config)
collect_adequacy_observations(cohort, prepared, replay, study_config)
summarize_adequacy_eligibility(observations)
```

Validate each replay point before observation:

```text
event_at is timezone-aware UTC
available_at is timezone-aware UTC
available_at >= event_at
boundary snapshot timestamp == event_at
boundary checkpoint source as_of == event_at
boundary known_at <= available_at
signal query/available metadata, when present, <= available_at
point identity fields are non-empty and internally consistent
```

Any availability or identity violation raises a typed contract error. Do not
mark it eligible or silently repair it.

Eligibility rules:

```text
only recorded replay positions qualify
position must lie within configured adequacy window
minimum warm-up/history requirements must hold
invalid model outputs remain retained observations
invalid outputs are excluded from geometry eligibility and reported separately
```

Summary may report scoped, eligible, invalid and excluded counts plus
per-timeframe counts. It must not produce a decision state.

## 7. Tests

Add non-parametrised offline tests covering at minimum:

```text
strict window validation and bool rejection
ordered timeframe/window coverage
study config deterministic identity
unknown metric rejection
explicit threshold validation
baseline deterministic identity
random baseline seed/repetition validation
future-data baseline rejection
cohort identity binds replay/preparation/dataset/config IDs
prepared/replay mismatch rejection
valid causal point eligibility
availability-before-event rejection
future-known boundary rejection
unrecorded/out-of-window point exclusion
minimum warm-up/history exclusion
invalid output retained and excluded
line/ray counts remain descriptive
eligibility summary deterministic
study/cohort identity changes when frozen inputs change
preparation/eligibility performs no model execution or provider call
```

Use synthetic/offline fixtures. Do not call Binance. Keep tests independent of
mutable notebook/viewer sessions. Do not add test fixtures that mutate replay
objects after identity creation.

## 8. Validation

Run focused adequacy tests, canonical trendline tests, targeted Ruff,
compileall, and `git diff --check`. Confirm no provider calls. Confirm changed
paths remain inside L2-D1 scope. Remove repository-local Python caches after
validation.

Expected result is a green contract foundation, not a model-quality conclusion.

## 9. Required coder handoff

Return exact files/symbols changed, tests and commands, provider-call evidence,
identity evidence, scope proof, residual risks, and explicit statement:

```text
No adequacy outcome was selected.
No D2/D3/D4/D5 study was run.
No model, YAML or provider path changed.
```
