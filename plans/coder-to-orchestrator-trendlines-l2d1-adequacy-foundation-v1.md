---
goal: Causal trendline adequacy evaluation foundation
stage: coder-to-orchestrator
date_created: 2026-07-26
last_updated: 2026-07-27
owner: quant-coder
status: Ready for review
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendlines, adequacy, l2d1]
---

# Mature Trendlines L2-D1
## Causal Adequacy Evaluation Foundation

### 1. Disposition

Implementation complete and uncommitted after R1 remediation. L2-D1 supplies
frozen causal measurement contracts and descriptive eligibility accounting. No
adequacy outcome was selected. No D2/D3/D4/D5 study was run.

### 2. Starting branch and commit

```text
branch: research/trendlines-adequacy-v1
starting feature checkpoint: 080277cf33dc357aefd231438a5bbc31369d5307
starting feature subject: feat: add mature trendlines research lab
integrated main checkpoint: 29a068a9032b826f88a859623b52faaeedeaee93
integrated main subject: merge: integrate mature trendlines research lab
```

### 3. Worktree and environment proof

Work remained in:

```text
/Users/aloobhujia/flipperAgent-wt-legacy-trendlines
```

Python:

```text
/Users/aloobhujia/flipperAgent/.venv/bin/python
```

No provider call was made. Existing committed model, replay, evidence, viewer,
YAML, Binance, RegimeV2, and L2-C artifact paths were not changed.

Before L2-D1 implementation, required main integration had been skipped. It was
completed in a temporary clean worktree from `origin/main` using `--no-ff
--no-commit`, validated, committed, pushed to `origin/main`, and fast-forwarded
back into this adequacy worktree. Primary Trendline V2 checkout was untouched.
Merge introduced no Trendline V2 path changes beyond files already on main.
The uncommitted L2-D1 file hashes were equal before and after this integration.

### 4. Research scope contracts

Added `TrendlineAdequacyWindow` with non-boolean integer positions, study-level
minimum warm-up and prior-executed-prefix requirements, ordered bounds, and
exact prepared/replay timeframe coverage. Windows must begin at or after replay
recording scope and intersect at least one recorded position under `record_every`.
Only recorded replay positions inside configured windows can be eligible;
unrecorded positions are never synthesized.

Added typed availability policy:

```text
causal_prefix_only
```

Replay points require timezone-aware event and availability times, availability
not before event time, boundary timestamp and checkpoint source horizon equal to
event time, boundary knowledge no later than availability, and signal knowledge
metadata no later than availability.

### 5. Frozen study configuration

`TrendlineAdequacyStudyConfig` binds:

```text
ordered tuple windows
selected metric names
an ordered unique subset of explicit finite decision rules
ordered baseline specs
fitted-line observation unit
boundary-ray observation unit
invalid-point treatment
causal availability policy
semantics version
```

`study_config_id` uses existing canonical SHA-256 identity seam. No model
parameter dictionary, frame, provider state, wall-clock value, or hidden numeric
fallback enters identity.

Decision rules remain protocol metadata. L2-D1 does not evaluate thresholds or
select an outcome.

### 6. Metrics and outcome vocabulary

Frozen metric catalogue covers:

```text
foundation
structural_stability
interaction_utility
baseline_comparison
robustness
```

Definitions declare unit, direction, description, and whether future rows are
required. Unambiguous utility metrics carry higher/lower direction metadata;
ambiguous raw geometry/event counts remain descriptive. L2-D1 computes only
descriptive coverage, invalid-point rate, fitted line count, and boundary-ray
count.

Permitted future outcome vocabulary is typed but unused:

```text
ADEQUATE_FOR_FURTHER_RESEARCH
STRUCTURALLY_STABLE_BUT_NO_UTILITY
UTILITY_NOT_BETTER_THAN_NAIVE_NULL
INSUFFICIENT_COVERAGE
EXCESSIVE_GEOMETRY_CHURN
INCONCLUSIVE_INSUFFICIENT_EVIDENCE
```

### 7. Baseline/null definitions

Added frozen definitions for:

```text
random_valid_pivot_pair
recent_extrema
horizontal_support_resistance
time_shifted_geometry
role_shuffled_geometry
density_matched_null
```

Randomized kinds require explicit non-boolean seeds. Repetition counts are
positive non-boolean integers. Baseline data policy is only
`causal_prefix_only`; future-data permission is rejected. Baseline IDs are
deterministic. No baseline geometry is generated or executed.

### 8. Cohort identity and observations

`TrendlineAdequacyCohort` binds:

```text
study_config_id
asset and ordered timeframes
preparation_id
dataset_id
research_configuration_id
replay_id and replay specification
per-timeframe source IDs
per-timeframe availability IDs
timestamp semantics
per-timeframe availability provenance
cohort semantics version
```

`cohort_id` is canonical SHA-256 content identity. Replay scope is stored as
ordered immutable tuples, and public cohort construction recomputes the ID from
those contents. Mutable dictionaries are not retained inside the frozen cohort.

`TrendlineAdequacyObservation` retains compact point identity/timing, fit
validity, eligibility state/reason, `prior_executed_prefix_count`, and
support/resistance line/ray counts. This count means executed causal prefixes
before the current point from replay warm-up; it is not retained snapshot or
signal-history depth. Invalid outputs remain reportable and are excluded from
geometry eligibility counts. No complete frame is embedded.

`collect_adequacy_observations()` first calls canonical
`validate_replay_point_integrity()`. Canonical failures are wrapped in
`TrendlineAdequacyContractError` with original cause retained. Adequacy windows
must begin inside replay recording scope and intersect at least one recorded
position under `record_every`; no synthetic positions are created.

### 9. Descriptive measurement API

Added:

```python
build_adequacy_cohort(prepared, replay, study_config)
collect_adequacy_observations(cohort, prepared, replay, study_config)
summarize_adequacy_eligibility(observations)
```

Collection performs no model execution, provider access, sorting, frame copy, or
replay mutation. Summary returns deterministic scoped/eligible/invalid/excluded
counts, per-timeframe counts, and foundation metric values. `decision` remains
`None` in serialized summaries.

### 10. Tests

Added offline synthetic tests under:

```text
src/libs/models/trendlines/tests/research_adequacy/test_foundation.py
```

Result before R1 remediation:

```text
21 passed
```

Coverage includes bool/bound checks, exact timeframe scope, deterministic
configuration and baseline identities, explicit threshold validation, causal
point checks, replay-integrity tamper rejection, recorded-stride scope,
future-known boundary rejection, prior-prefix handling, invalid-output
retention, descriptive counts, immutable cohort identity, public-summary
validation, exact metric catalogue/directions, and no-model-execution
eligibility.

### 11. Documentation

Updated:

```text
src/libs/models/trendlines/docs/research.md
src/libs/models/trendlines/docs/workflows.md
```

Docs state L2-D1 boundaries, causal availability rules, identity bindings,
invalid treatment, frozen null definitions, and explicit deferral of all
adequacy conclusions and later D2-D5 studies.

### 12. Validation evidence

```text
Research adequacy tests: 27 passed
Canonical trendlines:    520 passed
Viewer Python:            30 passed
Viewer Node/TypeScript:   23 passed
Consumer/ingestion:       79 passed
Offline workflows:        20 passed
Trendline V2 Python:      294 passed (isolated validation worktree)
Trendline V2 Node:         20 passed
Ruff:                     passed
compileall:               passed
git diff --check:         passed
Provider calls:            0
```

Canonical count is 493 committed trendline tests plus 27 R1 adequacy tests.
Research viewer and Trendline V2 web suites ran `npm test`; package builds and
all 23/20 tests passed. Consumer matrix used mocked RegimeV2/ingestion/research-
adapter suites. Offline group used the three canonical trendline optimizer/workflow
test modules. Trendline V2 Python ran in a fresh detached validation worktree to
avoid an unrelated stale viewer pytest process creating ignored app-level
node_modules in the active checkout.

One exploratory command included unrelated
`src/libs/regression/tests/test_optimization_integration.py`; collection hit
its existing `app.regression` import boundary. It was outside L2-D1 scope and
was not part of required offline group; exact required group passed.

Post-R1 current file hashes:

```text
f1cac4d81196088a889bb3104a1e5ab76b13ff18582d64a45cfa779a4b1eed78  src/libs/models/trendlines/docs/research.md
703cb28cb5bd031824e717c683a1ac422c9bcb6b2694bbe5cc178b7c157d4c20  src/libs/models/trendlines/docs/workflows.md
e2efd265a0db10baa88942d7a3b8dcd7a69ec539865b42e862e25c0b459f6653  plans/architect-to-coder-trendlines-l2d1-adequacy-foundation-v1.md
ad735d7cec0e7eac551d54842f037c90c1a8232775c9f05344fe73b810df25b3  src/libs/models/trendlines/tests/research_adequacy/__init__.py
d66a6e5797d65b016002a90cd86930f9b901941da3b424b7a93965e182532d33  src/libs/models/trendlines/tests/research_adequacy/test_foundation.py
85b85d3c9e2248e654875b7b2aea31fd28d48b86ed297ec9d375dd1cf560d4c7  src/libs/models/trendlines/workflows/research/adequacy/__init__.py
9409d4ba19f71b8452e3edc4a4b3eace3facee16f506cf174daa2c61b07adcff  src/libs/models/trendlines/workflows/research/adequacy/baselines.py
b9ad12dca01e3547db84eb5f15be55a74452799b932a3ae72e013c77b06ff337  src/libs/models/trendlines/workflows/research/adequacy/contracts.py
7ed1150a2c1e94d4c70863c164260f93cfd43b9e1366e5719f65c57d213faaca  src/libs/models/trendlines/workflows/research/adequacy/metrics.py
```

Handoff-file hash is reported separately because embedding a file's own hash
would be self-referential.

### 13. R1 findings and deliberate simplifications

Resolved:

- canonical replay-point integrity now gates every adequacy observation;
- windows require recorded replay scope and non-empty stride intersection;
- unreachable warm-up state was not added; warm-up remains study-level;
- `minimum_prior_executed_prefixes` and `prior_executed_prefix_count` replace
  ambiguous history vocabulary;
- decision rules cover an ordered subset of metrics, avoiding fake count rules;
- metric directions are explicit only for unambiguous utility directions;
- cohort replay scope is immutable and cohort ID self-validates its contents;
- public metric/timeframe/measurement summaries reject non-finite values,
  invalid counts, inconsistent aggregates, and unsupported semantics;
- tuple-or-mapping window complexity and unused scope semantics were removed.

Deliberately not added:

- generic recursive-freezing or validation frameworks;
- metric registries, study managers, model loops, D2 metrics, or adequacy
  conclusions.

### 14. Files changed

```text
A  plans/architect-to-coder-trendlines-l2d1-adequacy-foundation-v1.md
A  plans/coder-to-orchestrator-trendlines-l2d1-adequacy-foundation-v1.md
A  src/libs/models/trendlines/workflows/research/adequacy/__init__.py
A  src/libs/models/trendlines/workflows/research/adequacy/baselines.py
A  src/libs/models/trendlines/workflows/research/adequacy/contracts.py
A  src/libs/models/trendlines/workflows/research/adequacy/metrics.py
A  src/libs/models/trendlines/tests/research_adequacy/__init__.py
A  src/libs/models/trendlines/tests/research_adequacy/test_foundation.py
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
```

### 15. Commands executed

```text
git fetch origin
git worktree add --detach <temporary-integration-worktree> origin/main
git merge --no-ff --no-commit research/trendlines-adequacy-v1
git commit -m "merge: integrate mature trendlines research lab"
git push origin main
git merge --ff-only origin/main
pytest -q src/libs/models/trendlines/tests/research_adequacy
pytest --collect-only -q src/libs/models/trendlines/tests
pytest -q src/libs/models/trendlines/tests
pytest -q src/libs/models/trendlines/tests/research_viewer
pytest -q tests/test_regime_v2_trendline_feature_producer.py tests/test_regime_v2_shadow_binance_collector.py tests/test_regime_v2.py tests/ingestion/test_adapters.py tests/ingestion/test_trendlines_research_adapter.py
npm test (research_viewer/web)
pytest -q src/libs/models/trendlines/tests/test_optimizer.py src/libs/models/trendlines/tests/test_optimization_integration.py src/libs/models/trendlines/tests/test_trendlines_pipeline_workflow.py
pytest -q tests/models/trendline_v2 (fresh detached validation worktree)
npm test (src/libs/models/trendline_v2/tools/viewer/web)
compileall adequacy package and tests
ruff check adequacy package and tests
git diff --check
find . -type f -name '*.pyc' -delete
find . -depth -type d -name __pycache__ -empty -delete
```

### 16. Residual risks

L2-D1 does not implement structural-stability, interaction-utility,
baseline-execution, or robustness metrics. No real-market adequacy conclusion
exists. Future metrics must preserve replay-point selection, availability-time
cutoffs, frozen cohort identities, and explicit null definitions.

The committed optimization workflow remains separate and is not used by this
foundation. Provider and real-market execution remain outside L2-D1 validation.

### 17. Recommended next phase

```text
L2-D2 — Structural stability measurements
```

L2-D2 should be separately scoped and approved before measuring line birth,
disappearance, revision/churn, anchor persistence, geometry stability, coverage,
or survival across future prefixes.

### 18. Commit policy

No L2-D1 implementation commit made. Integrated main checkpoint remains
`29a068a`; worktree contains only listed L2-D1 files and generated caches are
removed after validation.
