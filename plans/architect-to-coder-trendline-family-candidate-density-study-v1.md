# Architect → Coder: Trendline-Family Candidate Density Study v1

## Objective

Build one bounded, read-only exploratory study that converts the already approved BTCUSDT 4h rejection diagnosis into a deterministic candidate-density and quality-support map.

The study must answer, without running the provider again:

- how candidate support changes across the existing lookbacks `120`, `180`, and `240`;
- how many candidates and producing bars would survive thresholds from `0.00` through `0.40`;
- whether the current minimum-sample failure is primarily threshold support, lookback support, fold concentration, or role imbalance;
- how `anchor_span_coverage_v1` is distributed by fold, role, path length, and anchor span;
- whether repeated anchor-pair evidence exists strongly enough to justify a separately approved fresh-data candidate trial.

This is exploratory research over already observed validation evidence. It is not a new optimization trial, a parameter recommendation, a promotion decision, or evidence for runtime use.

## Fixed Source Identity

The study may consume only the approved four-file diagnosis bundle:

```text
artifacts/trendline_family_candidate_diagnostics/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Require all identities before analysis:

```text
asset:                 BTCUSDT
timeframe:             4h
confirmed rows:        732
dataset hash:          trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53
resolved config hash:  da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
Phase-I run ID:        trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7
report ID:             trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41
recommendation ID:     trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc
diagnosis ID:          trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf
source-binding ID:     trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a
actual provider calls: 2016
shadow provider calls: 1969
validation windows:    252-347, 360-455, 468-563
planned holdout start: 636
```

Any mismatch must stop the study. Do not repair or regenerate the diagnosis bundle.

## Research Status and Bias Boundary

The three validation windows have already been observed and diagnosed. Therefore:

- all outputs are exploratory and post-diagnostic;
- no threshold or lookback from this study may be promoted on this dataset;
- any later candidate trial informed by this study must use a separately approved fresh unseen window;
- the planned holdout at positions `636-731` remains sealed and must not be read, inferred, replayed, or summarized.

Persist this limitation prominently in JSON and Markdown outputs.

## Scope Boundaries

### In scope

- strict read-only validation of the approved diagnosis bundle;
- analysis of persisted `diagnostic_records` only;
- exact reconstruction of threshold-zero candidate exposure for lookbacks `120`, `180`, and `240`;
- deterministic threshold-support curves;
- fold, role, path-length, anchor-span, and anchor-pair persistence summaries;
- descriptive support frontiers tied to the existing minimum-sample count of `100`;
- deterministic external research artifacts and focused tests.

### Out of scope

- importing or calling `NativeDeterministicLineProvider`;
- any provider `generate(...)` call or shadow replay;
- `CandidateGeometryEvaluator` or any future-outcome calculation;
- `run_phase_i_evaluation`, `run_stage_grid`, `run_validation_trial`, or optimization APIs;
- network access, Binance adapters, or new market data;
- any new lookback or candidate parameter value;
- any new quality formula or canonical candidate-score implementation;
- holdout access or holdout-derived conclusions;
- tracker, interaction/event, MTF, RegimeV2, signals, selection, runtime, or YAML work;
- PnL, strategy, directional, or trading claims;
- parameter recommendation, finalist selection, config patch, or promotion.

## Expected Implementation Scope

Create only:

```text
scripts/analyze_trendline_family_candidate_density.py

tests/scripts/test_trendline_family_candidate_density.py

artifacts/trendline_family_candidate_density_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_binding.json
    candidate_density_study.json
    candidate_density_study.md
    study_manifest.json

plans/coder-to-review-trendline-family-candidate-density-study-v1.md
```

Generated `.codebase-memory/` index files may change. Do not modify any existing production, diagnosis, report, trial, config, notebook, or research-lab file.

## Mandatory Read Boundary

Use:

```python
validate_diagnosis_bundle(output_root=<approved diagnosis root>)
```

The study script must not import or contain any of these boundaries:

```text
BinanceNativeAdapter
get_historical_ohlcv
NativeDeterministicLineProvider
provider.generate
run_phase_i_evaluation
run_stage_grid
run_validation_trial
CandidateGeometryEvaluator
evaluate_holdout_once
TrendlineFamilyTracker
advance_interaction_events
RegimeV2
```

Static tests must enforce the forbidden-boundary list.

## Canonical Exposure Reconstruction

The diagnosis contains seven configurations: baseline plus the six persisted primary configurations.

Use only the six primary configurations for the study curves:

```text
lookback 120, threshold 0.30
lookback 120, threshold 0.40
lookback 180, threshold 0.30
lookback 180, threshold 0.40
lookback 240, threshold 0.30
lookback 240, threshold 0.40
```

The baseline `180 / 0.35` is a reconciliation control only.

### Canonical full-exposure source

For each lookback, use its `0.40` configuration as the canonical threshold-zero exposure source.

Require for each `0.40` configuration:

- exactly 288 validation records;
- every actual status is `rejected_low_quality_candidates`;
- every record contains one diagnostic shadow payload;
- every shadow payload uses only `candidate.min_candidate_quality = 0.0`;
- exactly two exposed candidates per bar;
- one support and one resistance candidate per bar;
- quality method equals `anchor_span_coverage_v1`;
- exposed quality is strictly below `0.40`;
- all record positions are in the three approved validation windows and below 636.

Expected canonical exposure per lookback:

```text
bars:       288
candidates: 576
support:    288
resistance: 288
```

### Pairwise threshold reconciliation

For every lookback:

- require the `0.30` and `0.40` records to share the exact fold/position/timestamp universe;
- apply threshold `0.30` to the canonical `0.40` exposed candidates;
- require the derived producing-bar count, accepted-candidate count, role counts, and per-fold counts to equal the actual `0.30` diagnosis records;
- require every actual accepted `0.30` candidate to exist in the canonical exposure with identical role, anchors, quality, coverage, path length, and anchor span;
- require the canonical `180` exposure to reconcile with baseline `180 / 0.35` in the same way.

Expected actual reconciliation:

```text
120 / 0.30: 47 accepted candidates on 47 producing bars
120 / 0.40: 0 accepted candidates
180 / 0.30: 0 accepted candidates
180 / 0.35: 0 accepted candidates
180 / 0.40: 0 accepted candidates
240 / 0.30: 0 accepted candidates
240 / 0.40: 0 accepted candidates
```

Any mismatch must stop artifact generation.

## Threshold Grid

Build one deterministic descriptive grid:

```text
threshold_bps: 0, 100, 200, ..., 4000
threshold:     0.00, 0.01, 0.02, ..., 0.40
```

Here `10,000` basis points equals quality `1.00`.

Use `Decimal(str(quality))` and an exact decimal threshold derived from `threshold_bps`. Do not rely on accumulated binary-float stepping.

A candidate survives when:

```text
normalized_quality >= threshold
```

This grid is analytic only. It must never be converted to `TrialConfig`, runtime config, YAML, or a promotion recommendation.

## Required Study Outputs

### 1. Source and bias identity

Persist:

- all fixed identities;
- diagnosis file inventory and aggregate inventory hash;
- exact validation windows;
- holdout boundary and an explicit `holdout_accessed: false` claim;
- post-diagnostic/exploratory status;
- statement that later confirmation requires a fresh unseen data window.

### 2. Threshold-support curves

For each lookback, threshold, and fold, persist:

- exposed candidate count;
- accepted candidate count;
- producing-bar count;
- no-candidate bar count;
- support and resistance counts;
- support-only, resistance-only, both-role, and no-role bar counts;
- candidates per validation bar;
- producing-bar ratio;
- candidate count in the final 12 positions of each fold;
- horizon-eligible candidate count outside those final 12 positions;
- smallest-fold accepted count;
- largest-fold accepted count;
- largest-fold share of total candidates;
- role-balance ratio.

Aggregate across all three folds as well as retain each fold separately.

### 3. Existing-threshold reconciliation table

Highlight exact observed points:

```text
0.30, 0.35, 0.40
```

Require exact agreement with the approved diagnosis for all current configurations.

### 4. Minimum-sample support frontier

For each lookback, derive descriptively:

- all thresholds whose aggregate accepted-candidate count is at least `100`;
- the highest threshold on the fixed grid with aggregate count at least `100`, or `null`;
- whether every fold has at least one accepted candidate;
- accepted count per fold at that threshold;
- total and per-fold deficits relative to 100 and to a non-empty fold;
- thresholds where aggregate support crosses below 100;
- current-threshold deficits at `0.30`, `0.35`, and `0.40`.

Label this a support frontier, not a recommended threshold.

Do not create a finalist, ranking, objective gate, or promotion decision.

### 5. Quality and structure distributions

For every lookback, fold, and role, summarize:

- normalized quality / coverage;
- path length;
- anchor span in seconds;
- anchor span in exact 4h bars;
- threshold gap for `0.30`, `0.35`, and `0.40`;
- count, min, max, mean, median, and fixed quantiles `0.10`, `0.25`, `0.50`, `0.75`, `0.90`.

Require quality and coverage equality under `anchor_span_coverage_v1` within the existing contract tolerance.

### 6. Anchor-pair persistence

Define a deterministic structural key:

```text
(role, ordered anchor_ids)
```

For each lookback and role, report:

- distinct structural-key count;
- bars covered by repeated keys;
- fraction of bars whose key appeared on more than one bar;
- maximum consecutive run length;
- median consecutive run length;
- key lifetime from first to last observed position;
- top bounded repeated keys, capped at 20 and sorted deterministically.

This is descriptive structural continuity only. Do not interpret it as tracker performance.

### 7. Lookback contrasts

For each pair `120 vs 180`, `120 vs 240`, and `180 vs 240`, retain by fold and aggregate:

- quality distribution deltas;
- accepted candidate-count delta across every threshold;
- producing-bar-count delta across every threshold;
- role-balance delta;
- anchor-span and path-length deltas;
- support-frontier difference.

### 8. Observations and hypotheses

Keep separate arrays:

```text
observations
research_hypotheses
```

Observations must be direct deterministic statements from persisted evidence.

Hypotheses may include only follow-up questions such as:

- whether the current quality grid is above the observed support frontier;
- whether shorter lookbacks increase support by changing anchor-span coverage;
- whether candidate support is concentrated in one fold;
- whether a different quality definition deserves a separate architecture study.

Do not include a chosen threshold, chosen lookback, config patch, trading claim, or promotion language.

## External Artifact Contract

Output root:

```text
artifacts/trendline_family_candidate_density_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Required files:

```text
source_binding.json
candidate_density_study.json
candidate_density_study.md
study_manifest.json
```

### Source binding

`source_binding.json` must include:

- exact four-file diagnosis inventory;
- canonical sorted unique safe relative paths;
- non-negative integer sizes;
- lowercase 64-character SHA-256 values;
- aggregate inventory hash derived from canonical semantic content;
- diagnosis ID;
- diagnosis source-binding ID;
- content-addressed study-source-binding ID.

### Study identity

The study ID must be content-addressed from the complete semantic JSON payload excluding only its own ID field.

### Independent validation

Implement a strict pure validator that independently rederives:

- diagnosis inventory aggregate hash;
- study source-binding ID;
- study ID;
- JSON and Markdown hashes;
- all identity claims in the manifest;
- canonical equality between external source binding and the binding embedded in the study JSON.

The validator must reject jointly rebound nested inventory/manifest attacks. Include adversarial tests from the first implementation rather than deferring provenance hardening.

### Writes

- atomic writes;
- deterministic canonical JSON;
- identical reruns are idempotent;
- non-identical overwrite rejects;
- no source file may be rewritten.

## Source Immutability

Before and after the study, capture exact inventories for:

- v1 trial root: 1 file;
- v2 trial root: 30 files;
- approved report bundle: 4 files;
- approved diagnosis bundle: 4 files;
- `configs/trendline_family.yaml`.

Require canonical equality before returning success.

The study output must remain outside every protected source root.

## Test Requirements

Focused tests must cover at minimum:

1. forbidden imports/call boundaries are absent;
2. approved diagnosis bundle validates before analysis;
3. all fixed source identities reject drift;
4. canonical exposure has exactly 288 bars and 576 candidates per lookback;
5. exact support/resistance balance and quality-method identity;
6. `0.30`, `0.35`, and `0.40` reconciliation with approved diagnosis;
7. threshold curves are monotonic non-increasing in accepted candidates and producing bars;
8. threshold grid is exact and deterministic;
9. minimum-sample support frontier is derived without recommendation semantics;
10. fold/position universe excludes holdout and non-validation positions;
11. quality/coverage equality and deterministic quantiles;
12. anchor-pair persistence ordering and run-length correctness;
13. deterministic rerender and non-identical overwrite rejection;
14. source bytes remain unchanged;
15. forged nested diagnosis inventory with rebound aggregate/manifest claims rejects;
16. forged study source-binding ID rejects;
17. external-versus-embedded source-binding mismatch rejects;
18. missing/extra fields, duplicate/unsorted/unsafe paths, invalid sizes, and malformed hashes reject.

Copied-bundle tests must not run provider replay or rebuild the approved diagnosis.

## Validation Checklist

Run:

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/scripts/test_trendline_family_candidate_density.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family \
  tests/regime_v2/test_trendline_family_adapter.py \
  tests/regime_v2/test_trendline_family_projected_runtime.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/regime_v2 \
  tests/selection \
  tests/signals

/Users/aloobhujia/.local/bin/ruff check \
  scripts/analyze_trendline_family_candidate_density.py \
  tests/scripts/test_trendline_family_candidate_density.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache \
  .venv/bin/python -m compileall -q \
  scripts/analyze_trendline_family_candidate_density.py \
  tests/scripts/test_trendline_family_candidate_density.py

git diff --check
```

Also:

- independently call the study-bundle validator read-only;
- rerun artifact generation once and require byte-identical idempotence;
- verify protected source inventories before/after;
- reindex codebase-memory and report node/edge counts and `ready` status;
- verify the new script has no production runtime caller.

## Acceptance Criteria

The task passes only when:

1. no provider, evaluator, network, holdout, tracker, or Regime path executes;
2. canonical threshold-zero exposure is reconstructed solely from approved diagnosis records;
3. existing thresholds reconcile exactly;
4. threshold-support and structure distributions are deterministic and complete;
5. the study clearly remains exploratory and non-promotional;
6. the external artifact provenance chain rejects rebound forgeries;
7. all protected source bytes remain unchanged;
8. all validation commands pass.

## Explicit Non-Goals

Do not:

- change `anchor_span_coverage_v1`;
- add a new quality method;
- select a threshold or lookback;
- open holdout;
- create or rerun Phase I;
- fetch data;
- change YAML;
- modify canonical provider, fitter, optimizer, tracker, events, MTF, runtime, RegimeV2, signals, or selection;
- begin a fresh-data candidate trial;
- begin tracker research.

## Coder Handoff

Return:

```text
plans/coder-to-review-trendline-family-candidate-density-study-v1.md
```

The handoff must include:

- exact files created;
- fixed source identities;
- source immutability evidence;
- canonical exposure reconciliation;
- threshold-support summary without parameter recommendation;
- study and source-binding IDs;
- artifact hashes;
- tests and exact counts;
- codebase-memory status;
- known gaps;
- explicit confirmation that no provider replay, holdout, network, Phase-I, tracker, or Regime work occurred.

Stop after the study. Do not begin a fresh-data trial or tracker evaluation.
