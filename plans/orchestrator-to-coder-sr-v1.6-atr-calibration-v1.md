---
goal: Implement SR-V1.6 as a leakage-controlled TAOUSDT 1d ATR-period calibration and untouched-holdout evaluation without changing SR behavior or production configuration.
stage: orchestrator-to-coder
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Quant Orchestrator
status: Approved for implementation
tags: [handoff, quant, sr, atr-calibration, taousdt, walk-forward, holdout, evidence]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 1ee8cdea0b1ca9563d55f7ddab6d4a087fc3f2b4
source_branch: feature/sr-v1.5-baseline-trial
target_branch: feature/sr-v1.6-atr-calibration
---

# Orchestrator To Coder: SR-V1.6 ATR Calibration v1

## Objective

SR-V1.5 is closed and review-ready. Its deterministic TAOUSDT/1d evidence,
standalone Lightweight Charts viewer, and macOS Chrome smoke are approved.
Dense event-label overlap and the uncaptured exact Chrome version remain
non-blocking viewer follow-ups.

Implement a bounded calibration trial for the only upstream model input under
consideration: Wilder/RMA ATR period. Compare the predeclared periods
`7, 10, 14, 20, 28` on the frozen V1.5 TAOUSDT/1d source. ATR(14) remains the
global baseline. All eight SR parameters remain frozen.

V1.6 must answer one narrow question:

> Does one non-14 ATR period improve causal, first-touch zone reaction quality
> consistently across development folds and once on an untouched holdout,
> without achieving that result through too few zones, excessive invalidation,
> excessive churn, or censoring?

The phase must:

1. verify and reuse the exact V1.5 source bundle without contacting Binance;
2. create a development-only source capsule and a separately sealed full
   capsule;
3. replay every candidate causally through the development history with state
   carried across all fold boundaries;
4. select at most one challenger using development results only;
5. freeze a content-addressed selection artifact before opening holdout results;
6. evaluate only that selected challenger against ATR(14) on the holdout;
7. publish deterministic, tamper-evident evidence and one recommendation; and
8. stop for review without changing production configuration or merging.

This remains model-research evidence, not trading, PnL, profitability, or
production-readiness evidence.

## Non-Negotiable Decisions

| Decision | Locked value |
|---|---|
| Venue / asset / timeframe | `binance_usdm / TAOUSDT / 1d` |
| Source | approved V1.5 bundle only |
| ATR method / seed | existing `wilder_rma / sma` |
| Periods evaluated in development | `[7, 10, 14, 20, 28]` |
| Global baseline | ATR(14) |
| Common replay start | first bar where ATR(28) and reference ATR(14) are valid |
| Primary outcome | median first-touch reaction quality in reference ATR(14) units |
| Outcome horizon | 10 subsequent closed daily bars |
| Development folds | six fixed UTC calendar quarters |
| Holdout | `[2026-01-01T00:00:00Z, 2026-07-01T00:00:00Z)` |
| State policy | one causal replay per period; never reset at a fold or holdout boundary |
| SR parameters | all eight frozen |
| Holdout candidates | ATR(14) and at most one development-selected challenger |
| Production config | recommendation only; no automatic write |
| Database | none |
| Viewer work | none |
| Merge | forbidden |

The candidate ATR is a model input. It must not also define its own scoring
unit. Every candidate is evaluated with the independently computed frozen
reference ATR(14) at the touch close. This prevents a candidate from improving
its score by changing the denominator.

## Branch And Working-Tree Safety

1. Verify HEAD is exactly:

   `1ee8cdea0b1ca9563d55f7ddab6d4a087fc3f2b4`

2. Create:

   `feature/sr-v1.6-atr-calibration`

   directly from that commit.

3. Do not merge V1.5 or V1.6.
4. The existing modified `.codebase-memory/artifact.json`,
   `.codebase-memory/graph.db.zst`, and unrelated untracked plan drafts are
   outside scope. Do not edit, stage, delete, regenerate, or commit them.
5. If any dirty path overlaps an approved V1.6 path, stop and report the
   blocker.
6. Keep implementation/tests and the coder-to-review handoff in separate
   commits.
7. Generated source capsules, metrics, and evidence remain under the ignored
   research output root and must not be committed.
8. Every evidence manifest binds the implementation commit. If code changes
   after an evidence run, rerun all three stages and replace every evidence ID
   in the coder handoff.
9. Do not modify V1.5 artifacts to make V1.6 pass. A missing or invalid frozen
   source bundle is a blocker, not permission to refetch or substitute data.

## Scope

### Add

```text
configs/sr_trials/taousdt_1d_atr_calibration.yaml

src/libs/models/sr/scripts/atr_calibration/
├── __init__.py
├── artifacts.py
├── candidates.py
├── cli.py
├── config.py
├── contracts.py
├── metrics.py
├── runner.py
├── selection.py
└── source.py

tests/models/sr/scripts/atr_calibration/
├── __init__.py
├── test_artifacts.py
├── test_candidates.py
├── test_cli.py
├── test_config.py
├── test_contracts.py
├── test_metrics.py
├── test_runner.py
├── test_selection.py
└── test_source.py
```

A narrower file split is acceptable only if every named responsibility remains
explicit and independently testable. Do not collapse configuration, replay,
metrics, selection, and artifact publication into one large module.

### Do not modify

```text
configs/sr.yaml
configs/sr_inputs.yaml
configs/sr_trials/taousdt_1d_baseline.yaml

src/libs/models/sr/config/
src/libs/models/sr/domain/
src/libs/models/sr/detection/
src/libs/models/sr/association/
src/libs/models/sr/lifecycle/
src/libs/models/sr/replay/
src/libs/models/sr/serialization/
src/libs/models/sr/evaluation/
src/libs/models/sr/scripts/baseline_trial/
src/libs/models/sr/tools/zone_viewer/
src/libs/models/sr/__init__.py
apps/ingestion_app/adapters/binance_native.py
src/libs/features/indicators/volatility/atr.py
```

Do not add a new top-level script, tool, web app, database, ORM, cache service,
optimizer framework, generic experiment platform, feature store, or second SR
model tree.

## Dependency Direction

```text
V1.5 validated evidence bundle
  -> atr_calibration.source
  -> development-only capsule + sealed full capsule

development capsule + frozen calibration YAML
  -> atr_calibration.candidates
  -> existing ATR + existing SR replay/evaluation
  -> atr_calibration.metrics
  -> atr_calibration.selection
  -> immutable development selection artifact

sealed full capsule + immutable selection artifact
  -> ATR(14) + selected challenger replay only
  -> holdout metrics
  -> recommendation artifact
```

Rules:

- Core SR packages never import `scripts.atr_calibration`.
- `libs.models.sr.__init__` does not export this research integration.
- `atr_calibration.__init__` performs no I/O, config loading, artifact
  discovery, model replay, or market-data access.
- V1.6 may import the existing V1.5 bundle validator, existing ATR
  implementation, SR config resolver, replay, trace, and diagnostics APIs.
- No V1.6 module imports the Binance adapter or any network client.
- No provider call, subprocess fetch, or fallback source is allowed.
- Reuse existing canonical timestamp, float, JSON, hashing, and
  duplicate-key-safe boundaries where suitable. Do not fork an incompatible
  serialization convention.
- The development selector accepts only a development capsule. It must have no
  argument, field, object, callback, or path through which holdout bars or
  holdout metrics can be read.
- Holdout evaluation accepts exactly one immutable selection artifact and the
  sealed full capsule. It must not rerank candidates.
- Do not add optional ML, volume, regime, confidence, return, PnL, or
  optimization dependencies.

## Frozen V1.5 Source Identity

The only approved source is:

```text
bundle path:
research/tmp_sr_v1_5/d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925

bundle ID:
d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925

implementation commit:
2b8306b21a7e69f097218ffa05c34515b607de75

venue / symbol / timeframe:
binance_usdm / TAOUSDT / 1d

source rows:
811

requested window:
[2024-01-01T00:00:00Z, 2026-07-01T00:00:00Z)

actual source:
2024-04-11T00:00:00Z through 2026-07-01T00:00:00Z

source_bars.json SHA-256:
b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535

resolved SR config hash:
cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299

resolved V1.5 input hash:
5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d
```

Before publishing any V1.6 artifact:

1. call the hardened V1.5 Python bundle validator;
2. verify every identity above;
3. verify duplicate-key rejection and all member hashes;
4. verify strict bar order, uniqueness, exact daily cadence, OHLC validity,
   finite values, and the expected bounds; and
5. fail closed if the bundle is missing or differs.

The V1.5 trace and diagnostics are not an expected-output oracle for the V1.6
ATR(14) replay: V1.6 deliberately aligns every period to the later common
ATR(28) start, so its initial model history differs from V1.5. Reconcile the
source bars and overlapping ATR(14) values only. Recompute every V1.6 trace,
diagnostic, and outcome under this protocol, and do not treat V1.5 diagnostic
counts as the V1.6 objective.

## Calibration Configuration

Create
`configs/sr_trials/taousdt_1d_atr_calibration.yaml` with this semantic
content. Formatting can follow repository conventions, but values and ordering
are locked:

```yaml
version: "1"

calibration:
  trial_name: sr-v1.6-taousdt-1d-atr-calibration
  venue: binance_usdm
  symbol: TAOUSDT
  timeframe: 1d
  source_bundle_path: research/tmp_sr_v1_5/d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925
  source_bundle_id: d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925
  source_implementation_commit: 2b8306b21a7e69f097218ffa05c34515b607de75
  source_bars_sha256: b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535
  source_row_count: 811
  sr_config_path: configs/sr.yaml
  input_config_path: configs/sr_inputs.yaml
  expected_sr_config_hash: cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299
  expected_input_hash: 5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d
  output_root: research/tmp_sr_v1_6

atr:
  method: wilder_rma
  seed: sma
  baseline_period: 14
  candidate_periods: [7, 10, 14, 20, 28]
  common_start_period: 28
  evaluation_reference_period: 14

outcome:
  start_offset_bars: 1
  horizon_bars: 10
  primary_metric: median_first_touch_quality_reference_atr
  primary_location: median

development:
  folds:
    - name: 2024_q3
      start: "2024-07-01T00:00:00.000Z"
      end: "2024-10-01T00:00:00.000Z"
    - name: 2024_q4
      start: "2024-10-01T00:00:00.000Z"
      end: "2025-01-01T00:00:00.000Z"
    - name: 2025_q1
      start: "2025-01-01T00:00:00.000Z"
      end: "2025-04-01T00:00:00.000Z"
    - name: 2025_q2
      start: "2025-04-01T00:00:00.000Z"
      end: "2025-07-01T00:00:00.000Z"
    - name: 2025_q3
      start: "2025-07-01T00:00:00.000Z"
      end: "2025-10-01T00:00:00.000Z"
    - name: 2025_q4
      start: "2025-10-01T00:00:00.000Z"
      end: "2026-01-01T00:00:00.000Z"

holdout:
  start: "2026-01-01T00:00:00.000Z"
  end: "2026-07-01T00:00:00.000Z"

selection_gates:
  minimum_completed_first_touches_per_fold: 4
  minimum_eligible_development_folds: 4
  minimum_development_completed_first_touches: 24
  minimum_holdout_completed_first_touches: 8
  minimum_development_fold_win_fraction: 0.75
  minimum_development_pooled_delta_reference_atr: 0.10
  minimum_holdout_delta_reference_atr: 0.05
  maximum_invalidation_rate_delta: 0.05
  minimum_zone_creation_density_ratio: 0.50
  maximum_zone_creation_density_ratio: 2.00
  maximum_churn_rate_delta: 0.10
  maximum_right_censoring_rate_delta: 0.10
```

Configuration validation must reject recursively duplicated keys, unknown keys,
missing keys, empty values, wrong exact types, booleans as integers, non-finite
numbers, unsorted or duplicate candidate periods, absence of baseline 14,
mismatched common/reference periods, non-UTC timestamps, gaps or overlaps
between folds, a development/holdout overlap, holdout outside the source
window, invalid fractions, invalid ratios, unsafe paths, or identity mismatch.

All research semantics above belong to YAML and typed contracts. Protocol
schema names, enum values, canonical field names, and hashing domain
separators may remain software constants.

The CLI may accept only a subcommand and this config path. It must not expose
period, fold, threshold, source, output, SR, or input overrides.

## Frozen SR Parameters

Resolve `configs/sr.yaml` for `TAOUSDT/1d` through the existing resolver and
verify the expected hash. These eight paths and values remain unchanged:

```text
detection.pivot_span_bars        = 5
detection.zone_half_width_atr    = 0.25
association.merge_distance_atr   = 0.50
lifecycle.touch_tolerance_atr    = 0.25
lifecycle.break_buffer_atr       = 0.25
lifecycle.break_confirm_closes   = 2
lifecycle.max_age_bars           = 50
runtime.max_active_zones         = 8
```

The calibration period must not be injected through a call-time
`RuntimeConfig` or production input override. It is a research candidate
specified by the V1.6 calibration contract. Do not change SR config
provenance, config precedence, or hashing behavior.

## Source Preparation And Holdout Seal

Implement an explicit `prepare-source` stage:

1. validate the full frozen V1.5 bundle and identity;
2. decode source bars with the existing strict contracts;
3. publish a development capsule containing only bars whose
   `closed_at < 2026-01-01T00:00:00Z`;
4. publish a separately named sealed full capsule containing the validated
   complete source required for later causal holdout replay;
5. record member hashes, row counts, first/last open and close timestamps,
   split boundary, source bundle ID, source member hash, protocol version, and
   implementation commit; and
6. print both content IDs and paths.

The development capsule must contain the listing-history prefix needed for ATR
warmup and model state, not only bars that fall inside the scored development
folds.

The sealed full capsule must not be read by development candidate replay,
metrics, selection, ranking, or their tests. Opening it is allowed only in the
explicit holdout stage after an immutable development selection artifact
exists.

Do not create a mutable `latest` pointer. Downstream stages derive and verify
the exact expected artifact identity. Reject duplicate keys, missing members,
extra members, traversal, symlinks, hash mismatch, semantic mismatch, or
tampering.

## ATR And Candidate Replay Contract

Use only:

`libs.features.indicators.volatility.atr.ATR`

The method contract stays:

```text
method: wilder_rma
seed: sma
implementation: libs.features.indicators.volatility.atr.ATR
implementation_contract: true_range_sma_seed_then_wilder_recursion_v1
```

For each evaluated period:

1. compute ATR from source OHLC in strict chronological order;
2. verify the existing warmup contract and positive finite values;
3. compute the independent reference ATR(14) from the same prefix;
4. align every candidate to the common first bar where ATR(28), candidate ATR,
   and reference ATR(14) are valid;
5. create candidate `ClosedBar` values with unchanged state key, bar ID,
   `closed_at`, and OHLC; only `atr_at_close` varies by candidate;
6. call `create_initial_state` exactly once for that candidate;
7. call `replay_bars` once over its complete aligned history;
8. build the V1.4 evaluation trace and diagnostics; and
9. compute all fold outcomes from that one causal trace without resetting.

All candidates therefore receive identical bar identities, timestamps, OHLC,
evaluation-reference ATR values, replay start, and scored calendar windows.

Development runs all five periods. Holdout reruns exactly ATR(14) and the one
selected non-14 challenger over the full aligned history. If development
selects no challenger, do not evaluate alternative periods on holdout.

Required causality properties:

- ATR prefixes equal the corresponding full-run prefixes exactly.
- Appending or mutating bars after a development cutoff cannot change any
  earlier candidate bar, snapshot, event, first-touch outcome, fold metric, or
  selection result.
- No candidate starts earlier because it has a shorter warmup.
- No fold boundary or holdout boundary creates a fresh SR state.
- No later trace revises an earlier zone, event, or observation.
- Candidate ordering cannot affect results.

## First-Touch Outcome Contract

### Eligibility and anchor

Each candidate zone contributes at most one outcome across the entire replay.

The anchor is the earliest authoritative `SREventType.TOUCHED` event for that
zone whose event timestamp is at or after the zone's `visible_from`. If a
zone's first touch is before a scoring window, later touches do not make it
eligible in that window.

A fold owns an outcome when:

`fold.start <= first_touch_at < fold.end`

The holdout owns an outcome when:

`holdout.start <= first_touch_at < holdout.end`

Map the touch event to the exact source/model bar by state key, bar ID, and
`closed_at`. The anchor price is that bar's close. The evaluation denominator
is the independently computed reference ATR(14) at that same close. It must be
finite and strictly positive.

### Horizon and censoring

Do not score the touch bar. The outcome begins with the next closed bar and
uses exactly 10 subsequent source bars.

A development outcome is complete only when all 10 subsequent bars have
`closed_at < fold.end`. A holdout outcome is complete only when all 10
subsequent bars have `closed_at < holdout.end`. Otherwise it is
right-censored and excluded from the primary metric while remaining in the
censoring count.

A `BREAK_CONFIRMED` or `EXPIRED` event does not shorten the price horizon.
The market bars still exist and the fixed horizon is required for comparable
outcomes. Lifecycle events are recorded separately as guardrails.

### Excursions and quality

For a support zone:

```text
favorable = max(max(outcome highs) - anchor close, 0)
adverse   = max(anchor close - min(outcome lows), 0)
```

For a resistance zone:

```text
favorable = max(anchor close - min(outcome lows), 0)
adverse   = max(max(outcome highs) - anchor close, 0)
```

Normalize both with reference ATR(14) at the anchor:

```text
favorable_reference_atr = favorable / reference_atr_14_at_touch
adverse_reference_atr   = adverse / reference_atr_14_at_touch
quality_reference_atr   = favorable_reference_atr - adverse_reference_atr
```

The primary metric for a fold or pooled interval is the median
`quality_reference_atr` across completed outcomes. Report medians for
favorable and adverse excursions as descriptive components, but do not create
a second weighted objective.

Do not use the candidate's own ATR as the denominator. Do not infer intrabar
event order, use the touch bar's excursion, fit a return model, or translate
quality into a trade/PnL claim.

## Guardrail Metrics

Compute these deterministically for every candidate and scoring window:

- total first-touch outcomes;
- completed first-touch outcomes;
- right-censored first-touch outcomes;
- right-censoring rate;
- support/resistance completed counts;
- median favorable, adverse, and quality in reference ATR(14) units;
- invalidated completed outcomes;
- invalidation rate;
- created-zone count;
- created zones per 100 eligible aligned model bars;
- cohort terminal count;
- cohort churn rate.

Definitions:

- A completed outcome is invalidated when the same zone has an authoritative
  `BREAK_CONFIRMED` event with
  `first_touch_at < break_at <= tenth_outcome_bar.closed_at`.
- Invalidation-rate denominator is completed first-touch outcomes.
- Created-zone count is the number of unique zones whose first `CREATED`
  event falls inside the scoring window.
- Eligible aligned model bars are bars whose `closed_at` falls inside the
  scoring window.
- Zone-creation density is
  `100 * created_zone_count / eligible_aligned_model_bar_count`.
- The churn cohort contains zones created inside the scoring window.
- A cohort zone is terminal when it reaches `BROKEN` or `EXPIRED` by the
  scoring-window end.
- Churn rate is `cohort_terminal_count / created_zone_count`.
- Zero denominators produce an explicit undefined metric and fail any gate
  requiring that metric. Do not silently substitute zero.

Also record raw V1.4 diagnostics for reconciliation. Zone count, touch count,
break count, fakeout count, expiration count, or churn must never become the
optimization objective.

## Development Selection

Development uses the six fixed folds only. Holdout data and metrics are absent
from the selector's input contract.

For each non-14 candidate:

1. A fold is eligible for comparison only when both candidate and baseline
   have at least four completed first-touch outcomes.
2. The candidate must have at least four eligible folds.
3. Both candidate and baseline must have at least 24 completed development
   outcomes when development folds are pooled.
4. A fold win means candidate median quality is strictly greater than baseline
   median quality.
5. The fold-win fraction is wins divided by eligible folds and must be at
   least 0.75. Ties are not wins.
6. Pooled candidate median quality minus pooled baseline median quality must be
   at least +0.10 reference ATR.
7. Across pooled development, candidate minus baseline invalidation rate must
   be <= +0.05.
8. Candidate/baseline zone-creation density ratio must be within
   [0.50, 2.00].
9. Candidate minus baseline churn rate must be <= +0.10.
10. Candidate minus baseline right-censoring rate must be <= +0.10.

A candidate failing any required or defined metric is ineligible. Preserve a
machine-readable reason for every failed gate.

Rank eligible challengers by this exact stable ordering:

1. descending median of eligible-fold quality deltas;
2. descending pooled development quality delta;
3. ascending median absolute deviation of eligible-fold quality deltas;
4. ascending absolute distance from period 14; and
5. ascending period.

Select at most one challenger. Period 14 is never labeled a challenger.

The immutable development selection artifact must contain the full candidate
table, fold and pooled metrics, gate results/reasons, ranking inputs, selected
period or explicit no-selection result, source/config/protocol hashes,
implementation commit, and its own content ID.

If no challenger passes, use `INSUFFICIENT_EVIDENCE` only when the baseline
fails mandatory pooled coverage or no challenger has enough comparable data to
complete every development gate. Otherwise, when at least one challenger was
fully evaluable but none passed, use `RETAIN_GLOBAL_14`. An individually
under-sampled challenger does not force the whole trial to
`INSUFFICIENT_EVIDENCE` when another challenger was fully evaluable. Do not
inspect challenger holdout performance to rescue or replace the development
disposition.

## Holdout Evaluation And Recommendation

The holdout stage must first validate the immutable development selection
artifact and content ID, implementation commit, config/SR/protocol hashes, and
that no holdout metrics exist inside the development artifact.

If no challenger was selected, propagate the immutable development disposition
(`RETAIN_GLOBAL_14` or `INSUFFICIENT_EVIDENCE`) without opening holdout bars or
evaluating any non-14 period.

If one challenger was selected, then validate the sealed full source capsule,
its V1.5 parent identity, and all source hashes before reading holdout bars.
Evaluate exactly that period and ATR(14). The candidate passes holdout only
when:

1. both candidate and baseline have at least eight completed holdout
   first-touch outcomes;
2. candidate median quality minus baseline median quality is at least +0.05
   reference ATR;
3. candidate minus baseline invalidation rate is <= +0.05;
4. candidate/baseline zone-creation density ratio is within [0.50, 2.00];
5. candidate minus baseline churn rate is <= +0.10; and
6. candidate minus baseline right-censoring rate is <= +0.10.

Allowed final recommendations are exactly:

- `PROMOTE_EXACT_OVERRIDE`
- `RETAIN_GLOBAL_14`
- `INSUFFICIENT_EVIDENCE`
- `HOLDOUT_REJECTED`

Use:

- `PROMOTE_EXACT_OVERRIDE` only when a challenger passes every development
  and holdout gate;
- `INSUFFICIENT_EVIDENCE` when development has no fully evaluable challenger,
  the baseline lacks mandatory development coverage, or the selected
  challenger/baseline lacks mandatory holdout evidence;
- `HOLDOUT_REJECTED` when a development-selected challenger has sufficient
  holdout evidence but fails a holdout quality or guardrail gate; and
- `RETAIN_GLOBAL_14` when development selects no challenger for reasons other
  than insufficient evidence.

A promotion recommendation must specify only the future exact override:

```yaml
assets:
  TAOUSDT:
    timeframes:
      1d:
        atr:
          period: <selected_period>
```

Do not write this override to `configs/sr_inputs.yaml` in V1.6. Promotion
requires reviewer and user approval followed by a separate, auditable config
change. Do not change the global ATR(14) default.

The holdout is opened once for this protocol. If it rejects the challenger, do
not tune thresholds, periods, horizon, folds, metrics, or SR parameters against
the result. A revised protocol requires a new version and a new future holdout.

## Evidence And Determinism

Use canonical JSON with duplicate-key-safe readers, explicit schema versions,
sorted keys, stable list ordering, strict finite-number handling, canonical UTC
timestamps, domain-separated hashes, and atomic publication.

Required uncommitted output groups under `research/tmp_sr_v1_6`:

```text
source/development/<development_source_id>/
├── manifest.json
└── source_bars.json

source/sealed_holdout/<sealed_source_id>/
├── manifest.json
└── source_bars.json

development/<selection_bundle_id>/
├── manifest.json
├── protocol.json
├── development_metrics.json
└── selection.json

holdout/<holdout_bundle_id>/
├── manifest.json
├── selection_reference.json
├── holdout_metrics.json
└── recommendation.json
```

Exact member names may change only for a clear contract reason recorded in the
coder handoff. Do not add CSV, pickle, parquet, SQLite, Turso, a service, or a
mutable result registry.

Every manifest must bind:

- schema/protocol version;
- artifact stage and content ID;
- implementation commit;
- V1.5 source bundle ID, source hash, and row identity;
- development-source, sealed-source, and selection parent IDs as applicable;
- calibration config hash;
- resolved SR config and input hashes;
- ATR implementation contract;
- candidate list and baseline;
- development/holdout boundaries;
- outcome and gate protocol;
- member hashes and byte lengths; and
- a semantic payload from which the content ID is recomputed.

Validators must reject unknown/extra members, duplicate keys at any depth,
identity or parent mismatch, semantic/top-level mismatch, member hash/length
mismatch, recomputed-ID mismatch, unsafe paths, symlinks, non-finite values,
wrong ordering, and stage contamination.

Two clean runs from the same implementation commit and frozen source must
produce identical IDs and byte-identical files for all three stages.

## CLI

Provide exactly three explicit subcommands; no `run-all` shortcut:

```bash
PYTHONPATH=src .venv/bin/python -m \
  libs.models.sr.scripts.atr_calibration.cli \
  prepare-source \
  --config configs/sr_trials/taousdt_1d_atr_calibration.yaml

PYTHONPATH=src .venv/bin/python -m \
  libs.models.sr.scripts.atr_calibration.cli \
  select-development \
  --config configs/sr_trials/taousdt_1d_atr_calibration.yaml

PYTHONPATH=src .venv/bin/python -m \
  libs.models.sr.scripts.atr_calibration.cli \
  evaluate-holdout \
  --config configs/sr_trials/taousdt_1d_atr_calibration.yaml
```

Each command derives the exact expected parent artifact from the frozen config
and verified content identities. It must not choose the newest directory.

Print concise JSON only:

- `prepare-source`: separate development-source and sealed-source IDs, paths,
  and row counts;
- `select-development`: selection ID, path, selected period or null,
  development disposition;
- `evaluate-holdout`: holdout ID, path, selected period or null, final
  recommendation.

Importing the CLI or any package module must not execute a stage.

## Required Tests

### Configuration and contracts

- recursive duplicate-key rejection at every YAML and JSON depth;
- unknown/missing/wrong-type/boolean-as-number/non-finite rejection;
- exact candidate ordering and baseline membership;
- exact fold contiguity, development/holdout separation, UTC bounds, and
  source-window containment;
- threshold and safe-path validation;
- immutable typed contracts and enum validation.

### Frozen source and seal

- accept the exact approved V1.5 identity;
- reject missing source bundle, bundle/member/hash/row/config mismatch,
  tampering, extra files, symlinks, and traversal;
- prove no Binance/network import or call;
- development capsule ends before holdout start;
- development stage cannot open or receive sealed full bars;
- preparation is byte-deterministic.

### ATR and replay causality

- existing ATR prefix invariance for every candidate and reference ATR(14);
- common-start alignment at the max-period boundary;
- identical candidate bar IDs, timestamps, OHLC, and counts;
- only `atr_at_close` differs;
- one initial state and one replay per period;
- state persists across every development fold;
- holdout replay starts from source history, not a reset at 2026-01-01;
- candidate iteration order invariance;
- overlapping ATR(14) values reconcile with the frozen source and existing ATR
  implementation; V1.6 trace equality with the earlier-starting V1.5 replay is
  not required.

### Outcome metrics

- one earliest touch per zone;
- pre-window first touch prevents later re-entry;
- event/bar identity matching;
- next-bar start excludes touch-bar excursion;
- exact 10-bar horizon;
- support and resistance favorable/adverse direction;
- fixed reference ATR(14) denominator for every candidate;
- fold-end and holdout-end right censoring;
- break/expiry does not truncate price horizon;
- exact invalidation interval;
- created cohort, density, churn, and zero-denominator behavior;
- median and MAD determinism.

### Leakage and selection

- selector API has no holdout field or input;
- changing or appending holdout OHLC leaves every development metric,
  candidate eligibility, rank, and selection byte-identical;
- omitting holdout entirely leaves development results byte-identical;
- candidate fails closed on insufficient fold or pooled samples;
- fold ties are not wins;
- every guardrail can independently reject a candidate;
- density guardrail prevents a sparse-zone candidate from winning only through
  selectivity;
- stable tie-breaking in the exact approved order;
- no challenger means no non-14 holdout replay;
- holdout evaluates only selected challenger and baseline;
- holdout cannot change development selection;
- all four recommendation outcomes are covered.

### Artifacts and boundaries

- deterministic content IDs and byte-identical repeated publications;
- parent/reference binding;
- duplicate-key, identity, member, semantic, and recomputed-hash tampering
  rejection;
- atomic write/failure behavior;
- CLI concise JSON and no import-time work;
- SR core import boundary remains clean;
- `configs/sr.yaml`, `configs/sr_inputs.yaml`, V1.5 code/viewer, ATR, and
  Binance adapter remain unchanged.

## Validation Commands

Run from repository root with the project virtual environment:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/scripts/atr_calibration
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/scripts/baseline_trial
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/test_import_boundaries.py tests/models/sr/adapters/test_import_boundaries.py
.venv/bin/ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr tests/models/sr
git diff --check
```

Also run targeted independent probes for:

1. common-start and ATR prefix causality;
2. state carry across a fold and the holdout boundary;
3. holdout mutation/omission invariance of development selection;
4. candidate-independent reference ATR denominator;
5. sparse-zone and insufficient-sample rejection;
6. exact holdout candidate restriction;
7. artifact identity and duplicate-key tamper rejection; and
8. byte-identical repeated three-stage evidence.

Verify protected paths against the exact base commit, not only the working-tree
index. All pre-existing SR tests must stay green; V1.5 closed with 354 SR tests.

## Execution And Commit Order

1. Verify base commit and protected dirty paths.
2. Create `feature/sr-v1.6-atr-calibration`.
3. Add config, package, and mirrored tests.
4. Run unit, integration, boundary, Ruff, compile, and diff checks.
5. Commit implementation/tests only.
6. Run `prepare-source` twice and verify identical IDs/bytes.
7. Run `select-development` twice and verify identical IDs/bytes.
8. Freeze and record the selection artifact ID before running holdout.
9. Run `evaluate-holdout` twice and verify identical IDs/bytes.
10. Run both positive and adversarial independent probes.
11. Create
    `plans/coder-to-review-sr-v1.6-atr-calibration-v1.md`.
12. Commit the handoff separately.
13. Stop. Do not change config, merge, or begin V1.7.

## Coder-To-Reviewer Handoff

The handoff must include:

- branch, exact base, implementation commit, and handoff commit;
- file inventory and protected-path diff evidence;
- exact frozen source identity and validator result;
- development-source, sealed-source, development-selection, and holdout bundle
  IDs/paths;
- development fold table for all five periods;
- pooled development metrics and every gate result/reason;
- exact ranking inputs and selected challenger or no-selection disposition;
- explicit statement that selection was frozen before holdout evaluation;
- holdout comparison for only baseline and selected challenger;
- final recommendation and every recommendation gate;
- proposed exact config override text only if recommendation is
  `PROMOTE_EXACT_OVERRIDE`;
- deterministic rerun IDs and byte-comparison result;
- all test/quality command counts;
- independent probe results;
- confirmation that no provider/network call occurred;
- confirmation that no generated evidence was committed;
- confirmation that production config and protected modules are unchanged;
- confirmation that pre-existing artifacts/drafts remain untouched;
- limitations: one asset, one timeframe, short history, finite first-touch
  sample, fixed 10-bar horizon, no costs/PnL, and holdout opened once; and
- no merge.

Use status `Review Ready` only if implementation, development selection,
holdout evaluation, deterministic reruns, and all validation pass. Use
`Blocked` for missing/invalid frozen source or unavailable required evidence.
Use `Needs Revision` for implementation/test defects.

## Acceptance Gate

V1.6 is reviewable only when:

- the exact V1.5 source is validated and no market fetch occurs;
- all five periods share one common causal bar history and frozen SR config;
- ATR(14) is the common scoring denominator;
- development selection is demonstrably independent of holdout;
- state is never reset at fold or holdout boundaries;
- primary and guardrail metrics match the locked definitions;
- sample, quality, stability, and guardrail gates are fail-closed;
- holdout evaluates at most one challenger against baseline;
- all artifacts are deterministic and tamper-evident;
- production config is unchanged;
- all existing and new tests pass; and
- the branch remains unmerged.

A `PROMOTE_EXACT_OVERRIDE` result is a research recommendation, not permission
to edit configuration or deploy. Any other result is a valid V1.6 outcome and
must not be converted into a tuning loop against this holdout.
