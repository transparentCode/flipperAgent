---
goal: Implement and evaluate an asset/timeframe-relative, causal swing-salience probability model against a causal base-rate null without tuning a universal ATR reversal threshold.
stage: architect-to-coder
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, v2-3, adaptive, probabilistic, calibration, multi-asset, multi-timeframe, kiss]
approved_by: user
approval_date: 2026-07-19
source_agent: Quant Orchestrator
target_agent: Codex quant-coder
source_base: 60331170abbbb5e538a4a67fa3a970a137160758
depends_on: plans/approval-decision-sr-v2.2-causal-swing-reversal-adequacy-v1.md
---

# SR-V2.3 — Adaptive Causal Swing-Salience Calibration

## Architecture goal

Implement one consolidated V2.3 research pass answering:

> Can a parameter-free causal swing stream, normalized relative to each
> asset/timeframe's own past behavior, produce better calibrated probabilities
> and positive paired zone utility than a causal constant base-rate model?

V2.3 is not another fixed reversal-threshold search. It must preserve
continuous swing evidence, estimate uncertainty, and separate model
probabilities from strategy decisions.

Successful evidence may authorize a later shadow-runtime plan. It cannot
authorize trading, production configuration, holdout access, or merge.

## Prior decision

V2.2 is closed as approved negative research at exact base
`60331170abbbb5e538a4a67fa3a970a137160758`.

Its fixed `1.5 ATR` TAOUSDT/1d result remains:

- bundle `e50c0a2237c5e909d148eab39a19e75f76037d29c6f92d4a316c348190b47660`;
- study `34e44ea7c16384bd98bbc99aef162d4f9a516ae0b6ca2e4cc52d75a894e4c846`;
- disposition `SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL`.

Do not modify or reinterpret V2.2. Its fixed detector is a diagnostic reference,
not the V2.3 candidate generator or a production default.

## Options considered

### A. Periodically optimize an ATR reversal multiplier

Reject.

Weekly/monthly grid selection on 12h/1d data has too few new completed outcomes,
encourages configuration churn, and reuses development outcomes for repeated
selection.

### B. Use a trailing asset/timeframe quantile as a hard detector gate

Reject for V2.3.

This is adaptive in scale but still discards sub-threshold information and
moves the hard cutoff into a quantile parameter.

### C. Enumerate causal direction reversals and calibrate continuous salience

Selected.

Emit every valid alternating causal swing transition, retain continuous
reversal salience, normalize it against past-only observations from the same
asset/timeframe, and let probability plus uncertainty determine usefulness.

The fixed object is the causal adaptation contract, not an asset-level market
parameter.

## Branch and commit discipline

Create:

`feature/sr-v2.3-adaptive-context-calibration`

from exact base:

`60331170abbbb5e538a4a67fa3a970a137160758`

Use one implementation/evidence pass. A second pass is allowed only for
confirmed review defects.

Recommended commits:

1. implementation, tests, strict configurations and source protocol;
2. immutable evidence handoff documentation.

Do not merge.

## Scope boundaries

### In scope

- one unregistered pure causal swing-salience detector;
- asset/timeframe-relative salience normalization;
- causal hierarchical Beta calibration;
- TAOUSDT, ETHUSDT and SOLUSDT;
- 1d and 12h development cohorts;
- matched prior-close controls and first-revisit outcomes;
- causal walk-forward predictions;
- deterministic uncertainty estimation;
- strict source/evaluation artifacts and semantic validators;
- CLI entry points inside the SR model package;
- tests and coder-to-review handoff.

### Explicit non-goals

- no ML classifier, optimizer, parameter grid or feature search;
- no FVG, order block, fractal, volume profile, POC, trendline or indicator
  feature;
- no expert screenshot used as ground truth;
- no parsing TradingView images;
- no V1/V2.0/V2.1/V2.2 modification;
- no production `configs/sr.yaml` change;
- no viewer/UI change;
- no database;
- no runtime, strategy, risk, execution or order wiring;
- no holdout;
- no automatic weekly/monthly optimizer;
- no source repair, sorting, interpolation or silent row filtering;
- no merge or V2.4.

## Module layout

Add:

- `src/libs/models/sr/detection/causal_swing_salience.py`;
- `src/libs/models/sr/research/studies/adaptive_context_calibration/__init__.py`;
- `.../config.py`;
- `.../contracts.py`;
- `.../source.py`;
- `.../normalization.py`;
- `.../calibration.py`;
- `.../outcomes.py`;
- `.../metrics.py`;
- `.../artifacts.py`;
- `.../runner.py`;
- `.../cli.py`;
- `configs/sr_trials/sr_v2_3_adaptive_context_calibration.yaml`;
- mirrored tests under
  `tests/models/sr/research/studies/adaptive_context_calibration/`;
- detector tests under
  `tests/models/sr/detection/test_causal_swing_salience.py`.

Do not add a parallel top-level script tree. All scripts/tools remain inside
`src/libs/models/sr`.

## Source contract

### Assets and timeframes

Canonical order:

1. TAOUSDT/1d
2. ETHUSDT/1d
3. SOLUSDT/1d
4. TAOUSDT/12h
5. ETHUSDT/12h
6. SOLUSDT/12h

Venue remains `binance_usdm`.

### Frozen 1d sources

Reuse only the verified TAOUSDT/ETHUSDT/SOLUSDT members from the existing
V1.7 outer source bundle:

`research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`

Outer bundle ID:

`6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`

Source implementation:

`be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2`

Validate every selected member's existing source ID, source-bundle ID, bar
hash, grid hash, row count, venue, timeframe, timestamps and zero provider-call
identity. Do not republish or contact the provider for 1d.

### New 12h development sources

Use the existing leaf adapter only:

`apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter`

Exact half-open grid:

- start: `2024-08-19T00:00:00Z`;
- end: `2026-01-01T00:00:00Z`;
- timeframe: `12h`;
- expected rows per asset: `1000`;
- expected open-time spacing: exactly 12 hours;
- request `since` inclusive and `until - 1 ms`;
- adapter limit: `1000`;
- one bounded provider call per asset.

The approval authorizes at most three provider requests total: one each for
TAOUSDT, ETHUSDT and SOLUSDT. A failed or rejected request still consumes its
asset's allowance. Build and pass all synthetic/provider-boundary tests before
executing them.

If any response has missing, duplicate, unordered, additional, out-of-window,
non-finite or invalid OHLC rows, stop as `BLOCKED_SOURCE`. Do not retry,
repair, truncate, sort or spend another request without explicit user approval.

Provider imports must remain lazy and leaf-only in `source.py`. Evaluation
must consume only the published frozen source bundle and must be network-free.

### Source publication

Publish one immutable V2.3 source bundle under
`research/tmp_sr_v2_3/source/<source_bundle_id>/`.

Bind:

- exact request identities;
- adapter identity;
- asset/timeframe order;
- source and grid hashes;
- row counts and cutoff;
- implementation commit;
- member hashes and lengths;
- provider-call counts.

Capture each live response once, canonicalize it in memory, compute the complete
source bundle bytes twice before one publication, and prove byte identity. Do
not call the provider twice merely to prove determinism.

## ATR and common history

Use only:

- Wilder RMA;
- period 14;
- SMA seed;
- common start index 28.

ATR remains a scale/reference measure. It is not the detector gate.

## Parameter-free causal swing stream

Implement states:

- `UNSEEDED`;
- `SEEK_HIGH`;
- `SEEK_LOW`.

### Seeding

- Equal-close prefixes remain unseeded.
- First strictly higher close enters `SEEK_HIGH`.
- First strictly lower close enters `SEEK_LOW`.
- Select the strict highest/lowest extreme over the seed interval.
- Equal extremes keep the earliest bar.
- Emit nothing during seeding.

### SEEK_HIGH

At bar `t` with tracked extreme `e`:

1. If `high[t] > high[e]`, replace `e` and do not confirm on `t`.
2. Equal high retains the earlier extreme.
3. Otherwise confirm the resistance swing only when
   `close[t] < close[t-1]`.
4. Initialize `SEEK_LOW` from confirmation bar `t`.

### SEEK_LOW

Mirror exactly:

1. If `low[t] < low[e]`, replace `e` and do not confirm on `t`.
2. Equal low retains the earlier extreme.
3. Otherwise confirm the support swing only when
   `close[t] > close[t-1]`.
4. Initialize `SEEK_HIGH` from confirmation bar `t`.

Equal consecutive closes do not confirm. A newly selected extreme can never
confirm on the same bar.

### Raw salience

Resistance:

`raw_salience_atr = (high[e] - close[t]) / ATR[e]`

Support:

`raw_salience_atr = (close[t] - low[e]) / ATR[e]`

Require finite, non-negative salience. Preserve the value even when directional
wick geometry is zero and no candidate is emitted.

### Candidate geometry and time

Use the existing V2.1/V2.2 rejection-wick geometry:

- resistance: `max(open[e], close[e]) .. high[e]`;
- support: `low[e] .. min(open[e], close[e])`.

For non-zero geometry:

- `formed_at = extreme.closed_at`;
- `available_at = confirmation.closed_at`;
- `atr_at_creation = ATR[confirmation]`;
- source: `causal_swing_salience_v2_3`.

The extreme ATR belongs to raw salience. Confirmation ATR belongs to candidate
identity and width normalization.

## Asset/timeframe-relative normalization

For each confirmation, calculate its percentile against only prior
confirmations from the same asset/timeframe satisfying:

- confirmation time strictly earlier than the current availability;
- confirmation time within the preceding 365 UTC calendar days;
- finite raw salience;
- current observation excluded.

Use deterministic midrank:

`percentile = (count(x < current) + 0.5 * count(x == current)) / n`

If `n == 0`, record `NORMALIZATION_WARMUP` and do not emit a calibrated
prediction. Do not substitute another asset's percentile.

Map available percentiles to fixed semantic buckets:

- Q1: `[0.00, 0.25)`;
- Q2: `[0.25, 0.50)`;
- Q3: `[0.50, 0.75)`;
- Q4: `[0.75, 1.00]`.

These are probability-conditioning buckets, not detector gates. All candidates
remain serialized.

## Outcomes and labels

Reuse the V2.2 protocol unchanged:

- exactly two prior-close controls per in-fold real candidate, SUPPORT then
  RESISTANCE;
- same width, availability, creation ATR, state and fold;
- search starts at confirmation + 1;
- inclusive first intersection;
- 50-bar search;
- 10 subsequent outcome bars;
- fold-end censoring;
- ATR at each band's own touch;
- quality = favorable ATR - adverse ATR.

Primary pair requires real and same-side control both completed.

`paired_excess_quality_atr = real_quality - same_side_control_quality`

Binary calibration label:

- `1` only when paired excess is strictly greater than zero;
- `0` for zero or negative paired excess.

Bind `label_available_at` to the last closed outcome bar needed for both the
real and control pair. A prediction at time `t` may use a historical label
only when:

`label_available_at < t`

Candidate time alone is insufficient. This invariant requires adversarial
leakage tests.

## Causal probability calibration

Use only historical labels in the same salience bucket and trailing 365-day
calendar window.

Base prior is Jeffreys `Beta(0.5, 0.5)`.

For a target asset/timeframe at prediction time:

1. Collect bucket successes/failures from other assets across either timeframe.
2. Form the other-asset posterior mean
   `mu_g = (0.5 + S_g) / (1 + S_g + F_g)`.
3. If `S_g + F_g > 0`, compress its external prior precision to
   `kappa_g = sqrt(S_g + F_g)` and set
   `alpha_0 = mu_g * kappa_g`,
   `beta_0 = (1 - mu_g) * kappa_g`.
4. With no other-asset evidence, use `alpha_0 = beta_0 = 0.5`.
5. Add historical same-asset/other-timeframe bucket counts.
6. Add historical same-asset/same-timeframe bucket counts.
7. Output global, asset and final asset/timeframe posterior states separately.
8. Final probability is `alpha / (alpha + beta)`.
9. Report the central 90% Beta credible interval.

This is the sole V2.3 shrinkage rule. Do not tune prior, precision, bucket or
history length. Do not add side, lifecycle or geometry features to the
calibrator in V2.3.

### Causal null

For every scored prediction, compute a causal constant base-rate probability
from Jeffreys `Beta(0.5, 0.5)` plus all eligible prior labels, ignoring asset,
timeframe and salience.

The adaptive and null probabilities must be scored on exactly the same cases.

## Walk-forward window

Use common evaluation folds:

- 2025_q1: `[2025-01-01, 2025-04-01)`;
- 2025_q2: `[2025-04-01, 2025-07-01)`;
- 2025_q3: `[2025-07-01, 2025-10-01)`;
- 2025_q4: `[2025-10-01, 2026-01-01)`.

All earlier source bars are warmup/history only. Within folds, prediction is
strictly online: normalization and calibration update only from observations
and completed labels available before each candidate.

Full replay must equal every eligible prefix projection.

## Metrics

For identical scored predictions report globally and by asset/timeframe/fold:

- prediction count;
- outcomes and censoring;
- mean Brier loss;
- mean log loss;
- base-rate Brier and log loss;
- Brier improvement = null loss - adaptive loss;
- log-loss improvement = null loss - adaptive loss;
- predicted versus observed rate by salience bucket;
- calibration error diagnostics;
- mean and median paired excess quality ATR;
- posterior means and interval widths;
- source/candidate density diagnostics;
- fixed V2.2 detector candidate counts as diagnostic only.

Do not compare Brier scores across different candidate sets. V2.2 diagnostic
counts cannot affect disposition.

## Statistical uncertainty and disposition

Use a deterministic hierarchical Bayesian bootstrap over scored cases, nested
by asset/timeframe and fold:

- 10,000 draws;
- NumPy PCG64 seed `2303`;
- resample cohort-fold cells, then cases within selected cells;
- serialize draw protocol, not all draws;
- report central 90% intervals.

Positive loss improvement means adaptive is better.

Exact dispositions:

### `ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW`

Only when all are true:

- lower 90% bound of pooled Brier improvement is strictly greater than zero;
- lower 90% bound of pooled log-loss improvement is at least zero;
- lower 90% bound of pooled mean paired excess quality ATR is strictly greater
  than zero;
- lower 90% bound of median cohort Brier improvement is strictly greater than
  zero.

### `ADAPTIVE_CONTEXT_NOT_SUPPORTED`

When either is true:

- upper 90% bound of pooled Brier improvement is at most zero;
- upper 90% bound of pooled mean paired excess quality ATR is at most zero.

### `INSUFFICIENT_CALIBRATION_EVIDENCE`

All other valid cases, including empty/unscored predictions or intervals
spanning the support boundary.

These are research-governance decisions based on uncertainty. They are not
zone detector hyperparameters or trade-entry gates.

Unknown, missing, reordered or semantically inconsistent metrics/dispositions
must fail closed.

## Configuration

Create one recursive-duplicate-safe strict YAML binding exact:

- source identities and source-acquisition protocol;
- canonical asset/timeframe order;
- ATR;
- 365-day normalization/calibration history;
- salience buckets;
- Jeffreys prior and square-root external precision;
- outcome/control semantics;
- folds;
- bootstrap protocol;
- dispositions;
- artifact paths/members.

No call-time override, environment fallback or production-config fallback.

The existing global/asset/timeframe configuration resolver must not be changed.
V2.3 research configuration may model future override dimensions but must
contain one immutable study payload.

## Artifacts

Publish exact immutable source and evaluation bundles with safe paths,
non-regular/symlink rejection, canonical JSON, hashes and byte lengths.

Evaluation bundle must contain exactly:

- `manifest.json`;
- `study.json`;
- `cases.json`;
- `predictions.json`.

The casebook must allow complete reconstruction of:

- causal state transitions;
- raw salience and percentiles;
- history membership and bucket;
- candidate/control outcomes;
- label availability;
- global/asset/local posterior counts;
- adaptive and null probabilities;
- loss values;
- fold/cohort metrics;
- bootstrap summaries;
- disposition.

Semantic validation must recompute from frozen sources plus YAML and reject
rehashed tampering of any causal, statistical or decision field.

Generate evaluation twice from the implementation commit and require identical
bundle IDs and member bytes.

## Import boundaries

- detector imports domain only;
- normalization/calibration import domain/research primitives only;
- study may import shared SR research primitives already used by V2.2;
- no imports from the V2.0, V2.1 or V2.2 study packages;
- no legacy `libs.sr`;
- no provider/network import outside source leaf;
- evaluation runner is network-free;
- no runtime/model registration;
- no dataframe dependency outside source validation;
- SciPy may be used only for Beta interval calculation;
- NumPy may be used only for deterministic bootstrap.

## Implementation order

1. Create branch from exact base.
2. Add strict config/contracts and synthetic source protocol tests.
3. Implement parameter-free detector and full prefix tests.
4. Implement normalization with causal 365-day membership tests.
5. Implement outcomes, controls and label-availability tests.
6. Implement hierarchical Beta calibration and null.
7. Implement walk-forward metrics/bootstrap/disposition.
8. Implement source/evaluation artifacts and adversarial validators.
9. Run all offline tests before any provider request.
10. Fetch each 12h asset once and publish the source bundle.
11. Evaluate twice from exact implementation commit.
12. Validate both V2.3 evidence and protected V2.2/V2.1/V2.0/V1.12 evidence.
13. Commit code/tests/config, then coder-to-review handoff.

## Acceptance criteria

- No universal ATR magnitude gate exists in the V2.3 detector.
- Causal swing state alternates and is prefix-stable.
- Raw salience is retained for every confirmation.
- Percentile is asset/timeframe-local, past-only and current-excluding.
- History expires by UTC calendar time exactly.
- Prediction never uses a label before both paired outcomes are observable.
- Other assets/timeframes influence probability only through declared
  historical posterior counts.
- Sparse local evidence widens uncertainty instead of selecting a tuned value.
- Null and adaptive models score identical cases.
- No detector candidate is suppressed by its probability.
- Source fetch count is at most one per 12h asset.
- Evaluation after source publication performs zero provider calls.
- Artifact reruns are byte-identical.
- Protected evidence validates unchanged.
- No production/runtime/viewer/holdout/merge change.

## Required tests

At minimum:

- equal-prefix seeding;
- new/equal extremes;
- same-bar non-confirmation;
- zero-wick state transition;
- support/resistance salience mirrors;
- complete frozen-source prefix replay;
- 365-day exact inclusion/exclusion;
- percentile ties and current exclusion;
- asset/timeframe isolation;
- label-availability leakage;
- fold boundary and censoring;
- two-control topology and causal identity;
- Beta prior/precision arithmetic;
- sparse/global/asset/local backoff;
- adaptive/null identical-case scoring;
- log-loss finiteness without clipping;
- deterministic bootstrap;
- each disposition;
- recursive duplicate YAML keys;
- source schema/grid/cutoff/tamper;
- symlink/non-regular/parent path rejection;
- semantic rehash tampering;
- import boundaries;
- protected-evidence invariance.

## Validation checklist

From final docs HEAD record:

- focused detector/study tests;
- full SR suite;
- Ruff;
- compile/import all SR modules;
- architecture/import boundaries;
- `git diff --check`;
- source-bundle semantic validation;
- two byte-identical evaluation runs;
- evaluation semantic validation;
- protected V2.2, V2.1, V2.0 and V1.12 validation;
- exact config/protected hashes;
- final branch lineage and clean core diff.

## Stop rules

Stop and return `Blocked` without evidence if:

- source identity/grid cannot be frozen exactly;
- a provider request is consumed unsuccessfully;
- causal prefix parity fails;
- evaluation requires network access;
- adaptive/null prediction sets differ;
- evidence cannot be deterministically reconstructed;
- protected evidence changes.

After valid evidence:

- supported: hand off for review only; do not start shadow work;
- not supported: close adaptive price-only predictive SR;
- insufficient: do not tune this cohort; request an architect/user decision on
  broader prospective data.

## Coder handoff requirements

Report:

- branch, exact base and commits;
- source bundle/member IDs and provider-call counts;
- evaluation bundle/study IDs;
- disposition and uncertainty intervals;
- prediction/case counts by cohort/fold;
- causal replay and determinism evidence;
- all validation counts/commands;
- protected-evidence identities;
- explicit confirmation of no holdout, runtime, production, viewer, database,
  merge, tuning or V2.4 work;
- untouched pre-existing worktree artifacts/drafts.
