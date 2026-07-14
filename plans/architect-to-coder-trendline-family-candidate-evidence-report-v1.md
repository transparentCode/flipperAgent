# Architect → Coder: Trendline-Family Candidate Evidence Report v1

## Objective

Generate one deterministic, reviewer-facing evidence report from the already persisted and independently verified candidate/geometry v2 trial.

The report must consume only existing local evidence:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

It must not fetch market data, rerun Phase I, open holdout, rewrite the trial bundle, or begin tracker work.

The report should answer only:

- what dataset, configuration, outcome policy, folds, objective, and search grid were actually evaluated;
- what the verified baseline and six primary validation trials produced;
- why no validation finalist existed;
- what parameter-effect and leakage audits were persisted;
- what provider status, candidate density, balance, touch, survival, reaction, penetration, exclusion, and gate evidence exists;
- what evidence is absent, especially finalist and holdout evidence;
- why the canonical recommendation is `REJECT`;
- what may and may not be inferred from this one bounded structural trial.

## Scope Boundaries

### In scope

- read-only verification of v2 input evidence;
- read-only `load_verified_phase_i_artifacts(...)` over the existing v2 Phase-I bundle;
- deterministic extraction of verified evidence;
- one standalone reporting script;
- focused tests for report integrity and read-only behavior;
- writing report outputs outside the immutable v1/v2 trial roots;
- a coder-to-review handoff.

### Out of scope

- any Binance or other network request;
- calling `run_phase_i_evaluation` or any stage evaluator;
- rebuilding, repairing, rewriting, or re-identifying trial artifacts;
- opening or fabricating holdout evidence;
- changing objective, outcome policy, folds, search grid, or recommendation semantics;
- changing canonical model, provider, tracker, interaction, MTF, or optimization behavior;
- editing `configs/trendline_family.yaml`;
- runtime or feature promotion;
- RegimeV2, signal, selection, strategy, risk, execution, or portfolio work;
- PnL, trade simulation, return attribution, or signal interpretation;
- tracker trial preparation or execution.

## Fixed Source Identity

Use exactly:

```text
trial root:
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2

input manifest:
<input root>/input/input_manifest.json

normalized input:
<input root>/input/normalized_ohlcv.csv

Phase-I bundle:
<input root>/phase_i
```

Expected source identity:

```text
asset:                BTCUSDT
market:               Binance USD-M Futures
timeframe:            4h
start:                2025-08-01T00:00:00Z
end:                  2025-12-01T00:00:00Z
row count:            732
first timestamp:      2025-08-01T00:00:00Z
last timestamp:       2025-11-30T20:00:00Z
execution attempt:    2
authorization ID:     trendline_family_candidate_geometry_retry_v2
dataset hash:         trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53
normalized SHA-256:   b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150
resolved config hash: da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
```

Expected verified recommendation:

```text
winner:            None
decision:          REJECT
rationale:         no_validation_trial_passed_stage_owned_gates
recommendation ID: trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc
```

Any mismatch must stop the reporting task. Do not repair or reinterpret the source bundle.

## Expected Implementation Scope

Create:

```text
scripts/build_trendline_family_candidate_evidence_report.py

tests/scripts/test_trendline_family_candidate_evidence_report.py

artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_inventory.json
    evidence_report.json
    evidence_report.md
    report_manifest.json

plans/coder-to-review-trendline-family-candidate-evidence-report-v1.md
```

Do not modify the existing trial runner merely to generate this report. The reporting script must be independently runnable and read-only with respect to the source roots.

## Required Read Boundaries

Use canonical APIs:

```python
load_verified_phase_i_artifacts(<v2 phase_i root>)
ImmutableHistoricalFrame(...)
```

The report script must not import or call:

```text
BinanceNativeAdapter
get_historical_ohlcv
run_phase_i_evaluation
CandidateGeometryEvaluator.__call__
run_stage_grid
evaluate_holdout_once
```

It may import typed optimization/research contracts for serialization and validation.

## Input Verification Contract

Before report generation:

1. Build sorted relative-path/SHA-256 inventories for both v1 and v2 trial roots.
2. Read the v2 input manifest.
3. Verify every fixed identity above.
4. Verify SHA-256 of `normalized_ohlcv.csv` against the manifest.
5. Load the normalized CSV with a strict timezone-aware UTC index.
6. Verify:
   - 732 rows;
   - exact first/last timestamps;
   - strictly increasing unique timestamps;
   - exact four-hour spacing;
   - required OHLCV and `complete` fields;
   - finite positive OHLC;
   - non-negative volume;
   - valid high/low envelopes;
   - every row complete.
7. Rebuild `ImmutableHistoricalFrame` and require its dataset hash to equal the input manifest and Phase-I fold-plan data hash.
8. Load the Phase-I bundle through `load_verified_phase_i_artifacts(...)`.
9. Require the expected run, stage, dataset, config, recommendation, and no-finalist identities.
10. Recompute v1/v2 inventories after report writing and prove both source roots are byte-identical.

A failure at any step must stop without writing a partial final report. A bounded failure manifest outside the source roots is acceptable only if it clearly states that no report was completed.

## Deterministic Evidence Payload

Build one typed or strictly validated canonical payload with these sections.

### 1. Report identity

- report schema version;
- source trial name and execution attempt;
- source dataset hash;
- Phase-I run ID;
- recommendation ID;
- verified source-artifact hashes;
- deterministic report ID.

The report ID must exclude wall-clock timestamps and be derived from the complete semantic evidence payload.

### 2. Dataset and request provenance

- asset, market, timeframe, start/end;
- request parameters as persisted evidence only;
- raw and normalized row counts;
- input manifest hash;
- normalized-file hash;
- dataset hash;
- first/last timestamps;
- completeness and gap audit summary.

Do not perform or imply a new request.

### 3. Configuration identity

- config/model versions;
- resolved config hash;
- baseline candidate parameter values persisted in the manifest;
- field provenance only when already present in verified evidence;
- explicit statement that no YAML was changed.

### 4. Outcome-policy identity

Report the exact `CandidateOutcomePolicy` semantic inputs from the verified evaluator specification:

- horizon;
- ATR window;
- touch tolerance;
- survival penetration;
- reaction threshold;
- policy version.

### 5. Fold and holdout plan

- fold-plan ID;
- every training, warmup, purge, validation, and holdout boundary;
- label horizon;
- train mode;
- explicit verified holdout status.

Do not infer that holdout was evaluated merely because the plan contains a holdout window. In this bundle, no finalist exists, so report the absence of finalist freeze, holdout-open audits, baseline holdout result, and finalist holdout result.

### 6. Search request set

- exact search space;
- maximum trial count;
- seed;
- expected primary trial IDs;
- actual verified primary trial IDs;
- completion status;
- no missing/extra trial statement.

Sort primary trials canonically by:

```python
(canonical_json(trial.parameter_overrides), trial.trial_id)
```

### 7. Objective identity

- objective version;
- primary metric;
- direction;
- minimum sample count;
- fold coverage gate;
- failure-rate gate;
- allowed degradation;
- comparable-population requirement.

### 8. Baseline validation evidence

Include:

- trial/result IDs;
- status;
- per-fold metrics;
- aggregate metrics;
- worst-window metrics;
- objective gate and rejection reasons;
- provider status counts;
- excluded outcome counts/reasons;
- evaluated rows;
- runtime diagnostics as operational evidence only.

### 9. Primary trial evidence

For each of six primary trials include:

- trial/result IDs;
- exact overrides;
- status/failure evidence;
- per-fold and aggregate metrics;
- worst-window values;
- objective gate and rejection reasons;
- provider statuses;
- candidate count/coverage/density;
- support/resistance balance;
- touch/survival/reaction/penetration evidence;
- excluded outcomes;
- runtime/evaluated-row counts;
- parameter-effect audits;
- counterfactual result identities.

Do not rank trials outside canonical Phase-I winner selection.

### 10. Counterfactual and parameter-effect evidence

Include every verified marginal counterfactual and audit:

- owning stage;
- parameter name;
- baseline/trial values;
- trial and counterfactual identities;
- expected/observed changed outputs;
- forbidden outputs checked;
- effect detected;
- leakage detected;
- audit decision.

### 11. Finalist and holdout evidence

Explicitly report:

```text
validation finalist: None
finalist freeze: absent
holdout-open audits: absent
baseline holdout result: absent
finalist holdout result: absent
```

Do not create a holdout comparison table with synthetic null metrics.

### 12. Recommendation

Include the complete verified recommendation and clearly separate:

- canonical persisted decision;
- canonical rationale;
- objective-gate evidence;
- human interpretation.

The human interpretation must not replace or modify the persisted recommendation.

### 13. Bounded reviewer interpretation

State only evidence-supported conclusions, such as:

- the bundle is internally verified;
- no validation trial passed stage-owned gates;
- therefore no finalist and no holdout evaluation existed;
- this bounded trial provides no basis for config or runtime promotion;
- structural metrics do not establish PnL or live-trading utility;
- next research direction requires a separate planning decision rather than changing this report.

Any more specific model diagnosis must quote the relevant verified metrics/status counts and remain framed as an observation, not a causal conclusion.

## Output Contract

Write outside the immutable trial roots:

```text
artifacts/trendline_family_candidate_reports/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Required files:

### `source_inventory.json`

Contains sorted v1/v2 source inventories and their aggregate inventory hashes.

### `evidence_report.json`

Canonical machine-readable evidence payload.

### `evidence_report.md`

Readable report generated only from the canonical JSON payload.

### `report_manifest.json`

Binds:

- report schema version;
- report ID;
- source trial identity;
- source inventory hashes;
- normalized input SHA-256;
- dataset hash;
- Phase-I run ID;
- verified artifact hashes;
- recommendation ID;
- SHA-256 of JSON and Markdown reports.

Use atomic writes. Refuse to overwrite an existing non-identical report. Identical rerendering may be idempotent but must not alter content.

## Tests

Add focused coverage proving:

1. The report script has no network/adapter/stage-runner imports or calls.
2. Source input and Phase-I bundle are verified before report construction.
3. Tampered normalized CSV rejects.
4. Tampered input-manifest hash or dataset identity rejects.
5. Tampered Phase-I artifact rejects through canonical verification.
6. Missing or changed recommendation identity rejects.
7. Report generation is deterministic under equivalent trial ordering.
8. The six primary trials are complete and canonically ordered.
9. No-finalist/no-holdout state is reported exactly and no synthetic holdout metrics appear.
10. JSON and Markdown hashes are bound by the manifest.
11. Non-identical output overwrite rejects.
12. V1/V2 source inventories are unchanged before and after generation.
13. No YAML, runtime, RegimeV2, signal, selection, tracker, or canonical model files change.

Prefer temporary copied fixtures for destructive tamper tests. Never alter the real v1/v2 roots.

## Implementation Order

1. Read the approved research-lab and ordering-remediation review handoffs.
2. Confirm codebase-memory is ready.
3. Capture v1/v2 source inventories.
4. Add the standalone read-only report script and pure helpers.
5. Add focused fixture/tamper/determinism tests.
6. Run focused tests and static checks.
7. Execute the reporting script once against the existing verified v2 evidence.
8. Independently reload and validate all report files and hashes.
9. Recompute v1/v2 inventories and prove byte identity.
10. Run broader regression and isolation checks.
11. Write the coder-to-review handoff and stop.

## Acceptance Criteria

- no network access;
- no Phase-I or evaluator execution;
- no holdout action;
- v1/v2 source roots unchanged byte-for-byte;
- normalized input and verified Phase-I bundle cross-bound successfully;
- all six primary trials represented exactly once;
- baseline, folds, gates, metrics, audits, no-finalist state, and recommendation fully reported;
- deterministic content-addressed report outputs;
- no config/runtime promotion claim;
- no tracker work;
- focused and broad tests pass.

## Validation Checklist

Run focused report tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_evidence_report.py \
  -q -p no:cacheprovider
```

Run optimization and research support tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider
```

Run full trendline-family tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider
```

Run integration isolation checks:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider
```

Run static checks:

```bash
/Users/aloobhujia/.local/bin/ruff check \
  scripts/build_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_candidate_report_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/build_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py

git diff --check
```

Verify codebase-memory is reindexed and ready. Confirm `run_phase_i_evaluation` still has no production runtime caller.

## Explicit Non-Goals

Do not:

- fetch data;
- rerun the candidate experiment;
- repair or rewrite v1/v2 artifacts;
- open holdout;
- alter recommendation ordering or semantics further;
- modify canonical optimization/model code unless a new blocker is found, in which case stop;
- change YAML or runtime configuration;
- promote parameters;
- run tracker, interaction, MTF, or RegimeV2 research;
- produce PnL or trading conclusions.

## Mandatory Completion Report

Return exactly these sections:

- Scope Executed
- Files Changed
- Source Evidence
- Input Verification
- Phase-I Verification
- Report Identity
- Dataset And Configuration
- Outcome Policy
- Fold And Holdout Evidence
- Search Request Set
- Baseline Evidence
- Primary Trial Evidence
- Counterfactual And Audit Evidence
- Recommendation
- Bounded Interpretation
- Source-Root Integrity
- Runtime And Regime Isolation
- Tests
- Codebase-Memory
- Known Gaps
- Next Handoff

Write:

```text
plans/coder-to-review-trendline-family-candidate-evidence-report-v1.md
```

Stop after report generation. Do not begin tracker work.