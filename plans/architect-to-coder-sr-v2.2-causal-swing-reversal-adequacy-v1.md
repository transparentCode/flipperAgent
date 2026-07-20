---
goal: Test whether alternating ATR-confirmed causal swing-reversal wick bands outperform matched prior-close naive bands on frozen TAOUSDT 1d development data.
stage: architect-to-coder
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, v2.2, causal-swing, zigzag-style, adequacy, kiss]
approved_by: user
approval_date: 2026-07-19
source_agent: Quant Orchestrator
target_agent: Codex quant-coder
source_base: bd6c73281629c60c087417ab4e77dd7383feb07a
depends_on: plans/coder-to-review-sr-v2.1-pivot-rejection-adequacy-v1.md
---

# SR-V2.2 — Causal Swing-Reversal Adequacy

## Objective

Implement and evaluate one final price-only V2 hypothesis:

> Alternating swing extremes confirmed by a close reversal of at least
> 1.5 ATR produce rejection-wick zones with better first-revisit reaction
> quality than same-width bands centered on the immediately preceding close.

V2.2 changes only swing selection relative to V2.1:

- V2.1 used fixed span-5 pivots and failed the matched naive null.
- V2.2 replaces fixed-span selection with an alternating, non-repainting,
  ATR-confirmed swing state machine.
- Rejection-wick geometry, control design, outcomes, folds, gates, source, and
  ATR(14) remain unchanged.

The hypothesis is locked before evidence:

- Wilder ATR(14), SMA seed, common start index 28;
- reversal threshold: exactly `1.5 × ATR at the tracked extreme`;
- confirmation uses the later bar's close;
- high swing → RESISTANCE; low swing → SUPPORT;
- geometry remains the extreme candle's directional wick;
- no threshold grid, tuning, scoring, features, indicators, or learned model.

This document combines hypothesis lock and implementation handoff. User
approval was recorded on 2026-07-19 and authorizes one coding/evidence pass.

## Scope Boundaries

Create branch `feature/sr-v2.2-causal-swing-reversal-adequacy` from exact
V2.1 approved-negative closeout
`bd6c73281629c60c087417ab4e77dd7383feb07a`.

This is a stacked research branch. It does not merge V2.0/V2.1, promote their
detectors, or authorize production changes.

Remain inside:

- active `src/libs/models/sr`;
- one strict V2.2 trial YAML;
- focused SR tests;
- ignored V2.2 evidence;
- one coder-to-review handoff.

Use only the existing frozen TAOUSDT Binance USD-M 1d development source:

- outer cohort bundle:
  `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`;
- canonical source capsule:
  `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`;
- source ID:
  `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`;
- 629 frozen source rows through 2025-12-31;
- 601 model bars after the frozen ATR common start;
- the same six quarterly development folds.

No provider call, source refresh, extra row, holdout access, fold change, gate
change, or post-result tuning is allowed.

The existing `src/libs/trendlines/pivots/rdp_zigzag.py` is reference-only and
must not be imported or copied. It uses full-path RDP geometry, full-series
mean ATR, and future path endpoints; those semantics are incompatible with
causal V2.2 evidence.

Legacy `src/libs/sr` remains reference-only and forbidden as a dependency.

## Affected Symbols, Modules, and Flows

Expected surfaces:

- new pure detector:
  `src/libs/models/sr/detection/causal_swing_reversal.py`;
- optional public pure-function export in
  `src/libs/models/sr/detection/__init__.py`;
- canonical study:
  `src/libs/models/sr/research/studies/swing_reversal_adequacy/`;
- strict config:
  `configs/sr_trials/sr_v2_2_taousdt_1d_swing_reversal_adequacy.yaml`;
- detector and canonical-study tests;
- architecture/import-boundary assertions;
- `plans/coder-to-review-sr-v2.2-causal-swing-reversal-adequacy-v1.md`.

Keep the CLI in the canonical study package. Do not add a historical
`scripts/<study>` facade.

The detector is unregistered. Do not wire it into `SREngine`, lifecycle,
association, runtime config, replay, checkpoint, viewer, or downstream trading.

Execution flow:

1. Load and validate exact frozen source/config identities.
2. Build point-in-time Wilder ATR(14) model bars.
3. Run the causal alternating swing state machine.
4. Convert confirmed swing extremes to rejection-wick candidates.
5. Build two matched prior-close controls for every in-fold candidate.
6. Evaluate real/control bands independently.
7. Form completed same-side pairs.
8. Apply exact readiness then utility gates.
9. Publish and semantically reconstruct deterministic evidence.

Before modifying an existing symbol, run codebase-memory impact analysis. If
the service is unavailable, record that and explicitly inspect callers,
imports, protected evidence, and the diff. Warn before HIGH/CRITICAL impact.

## Data Contracts and Interfaces

### 1. Detector configuration

Introduce one immutable detector-specific config:

- `reversal_atr: float`.

It has no Python numeric default. Strict V2.2 YAML must supply exactly
`reversal_atr: 1.5`.

Reject booleans, non-numeric values, NaN, infinity, zero, negative values,
unknown keys, missing keys, and call-time overrides.

Fixed source label:

`causal_swing_reversal_v2_2`

### 2. State machine

Use exactly three internal modes:

- `UNSEEDED`;
- `SEEK_HIGH`;
- `SEEK_LOW`.

The detector is a pure batch function over an exact tuple of ordered
`ClosedBar` values. Internal mutable iteration state must not escape.

#### Seeding

Start at the first model bar.

- Maintain the seed start and inspect closes sequentially.
- On the first strictly higher close than the immediately preceding close,
  enter `SEEK_HIGH`.
- On the first strictly lower close, enter `SEEK_LOW`.
- Equal closes leave the state `UNSEEDED`.
- When entering `SEEK_HIGH`, select the strict highest high from all seed
  bars through the direction-establishing bar.
- When entering `SEEK_LOW`, select the strict lowest low over that interval.
- Equal extreme prices keep the earliest bar.
- Emit no candidate during seeding.

This deterministic seed affects only the initial alternating direction and
must be fully prefix-causal.

#### Seeking a high

Track one high extreme bar `e`.

For each later bar `t`:

1. If `high[t] > high[e]`, replace the tracked extreme with `t` and do
   not confirm a swing on that bar.
2. Otherwise, confirm the tracked high when:

   `close[t] <= high[e] - 1.5 × ATR[e]`

3. Equality at the reversal threshold confirms.
4. On confirmation:
   - record swing high `e`;
   - `formed_at = e.closed_at`;
   - `available_at = t.closed_at`;
   - transition to `SEEK_LOW`;
   - initialize the tracked low extreme from bar `t`.
5. Emit at most one confirmed swing per bar.

A bar that establishes a new high cannot confirm that same high. This prevents
same-bar formation/availability and keeps the causal rule unambiguous.

#### Seeking a low

Mirror the high rule:

1. If `low[t] < low[e]`, replace the tracked extreme with `t` and do not
   confirm on that bar.
2. Otherwise, confirm when:

   `close[t] >= low[e] + 1.5 × ATR[e]`

3. Equality confirms.
4. Record the low, transition to `SEEK_HIGH`, and initialize the new high
   extreme from confirmation bar `t`.
5. Emit at most one swing per bar.

Equal highs/lows never replace the earlier tracked extreme.

Confirmed internal swings must alternate HIGH/LOW even when one swing has
zero-width zone geometry and emits no candidate.

### 3. Causality and ATR ownership

The reversal threshold is frozen when the tracked extreme is selected:

- threshold scale: `ATR[e]`;
- later ATR changes must not move the threshold for that extreme;
- a new strict extreme replaces both price and threshold ATR.

Candidate provenance remains confirmation-time:

- `atr_at_creation = ATR[t]`;
- `formed_at = extreme.closed_at`;
- `available_at = confirmation.closed_at`;
- `formed_at < available_at`.

A controlled unequal-ATR test must prove extreme ATR qualifies the reversal
while confirmation ATR owns the candidate identity.

Appending future bars must not change any previously available candidate,
ordering, causal identity, or confirmation time.

### 4. Rejection-wick geometry

Keep V2.1 geometry exactly.

For a confirmed swing high:

- side: RESISTANCE;
- `lower_bound = max(extreme.open, extreme.close)`;
- `upper_bound = extreme.high`.

For a confirmed swing low:

- side: SUPPORT;
- `lower_bound = extreme.low`;
- `upper_bound = min(extreme.open, extreme.close)`.

Use existing `ZoneGeometry` center/half-width representation.

A zero or negative directional wick emits no candidate, with no epsilon, ATR
floor, candle-range substitute, or tick-size fallback. The internal swing
transition still occurs.

### 5. Ordering and identity

Candidates sort by:

1. `available_at`;
2. RESISTANCE before SUPPORT;
3. `candidate_id`.

Each real case binds only confirmation-time facts:

- candidate identity;
- confirmation bar ID/index;
- extreme bar ID/index;
- extreme ATR used by the threshold;
- confirmation predecessor close;
- fold;
- width in confirmation ATR.

Status and outcomes must not enter case/control identity.

Different future paths may alter later swings/outcomes but must not rewrite
already confirmed identities.

### 6. Shared services and modularity

Reuse the existing neutral services:

- `research/metrics/first_revisit.py`;
- frozen source/cohort adapters;
- strict research config primitives;
- repository provenance;
- canonical JSON, manifest, publisher, validator, and path-safety services;
- existing domain candidates, geometry, sides, bars, and first-touch outcome.

Study-specific config, case/control contracts, disposition, metric assembly,
artifact schema, and semantic recomputation remain inside
`swing_reversal_adequacy`.

Do not import a sibling study. Do not mechanically copy an entire previous
study or build a detector registry/generic experiment framework. Extract a new
shared primitive only if it is genuinely detector-neutral, has at least two
real consumers after the change, preserves protected artifact semantics, and
is covered by parity tests.

Do not refactor V2.0/V2.1 merely for aesthetic deduplication.

### 7. Matched naive controls

For every candidate whose `available_at` is inside a fold, construct exactly
two controls in stable order SUPPORT then RESISTANCE:

- center: `close[t-1]`;
- half-width: real candidate half-width;
- formed_at: predecessor bar close;
- available_at: real candidate availability;
- creation ATR: real candidate creation ATR;
- source: `prior_close_naive_v2_2`;
- same state key.

The real case must bind the actual predecessor close. Reject a control whose
declared prior close, center, predecessor bar, width, confirmation, state,
availability, ATR, fold, side topology, or real-case identity does not match.

Build both controls before real outcome discovery. Each control finds its own
touch and outcome.

### 8. Outcome protocol

Keep V2.1/V2.0 semantics unchanged:

- search begins at confirmation index + 1;
- inclusive OHLC/band intersection;
- maximum 50 search bars;
- fold-end search cutoff;
- first touch only;
- 10 subsequent bars for reaction;
- all horizon bars close strictly before fold end;
- incomplete horizon is right-censored;
- explicit completed, no-touch, right-censored, outside-fold accounting;
- each band uses ATR at its own touch.

Quality remains favorable excursion ATR minus adverse excursion ATR, with
side-correct direction.

### 9. Pairing, metrics, and gates

Primary pair requirements remain exact:

- real and same-side control both completed;
- exact real-case/control causal binding;
- matching fold, state, confirmation, availability, creation ATR, side, and
  width;
- distinct real/control geometry identity.

`paired_excess_quality_atr = real_quality_atr - naive_quality_atr`

Opposite-side controls are diagnostic only.

Serialize candidate/control status counts, unpaired reasons, per-fold counts,
per-fold medians, comparable folds, pooled median, positive-fold fraction, and
worst comparable-fold median.

Use the exact ordered seven-gate topology and V2.1 numeric thresholds.

Readiness:

- completed same-side pairs >= 24;
- comparable folds >= 4;
- pairs per comparable fold >= 4;
- completed controls per side per comparable fold >= 4.

Utility after readiness:

- pooled median paired excess >= 0.10 ATR;
- positive comparable-fold fraction >= 0.60;
- worst comparable-fold median >= -0.10 ATR.

Exact dispositions:

- `SWING_REVERSAL_BEATS_NAIVE_NULL`;
- `SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL`;
- `INSUFFICIENT_EVIDENCE`.

Unknown, missing, extra, reordered, wrong-category, wrong-operator, or
wrong-threshold gates fail closed. Disposition and reason must derive exactly
from readiness precedence and utility gates.

### 10. Strict configuration and provenance

The YAML must bind exact:

- trial/study identity;
- TAOUSDT/binance_usdm/1d;
- frozen source paths, IDs, hashes, row/grid/cutoff identity;
- ATR protocol;
- reversal threshold;
- control topology;
- outcome protocol;
- six folds;
- gates/dispositions;
- output root, stage, schema and exact members.

Reject recursive duplicate YAML keys and all missing/unknown/mistyped values.
Do not fall back to production `configs/sr.yaml`.

Keep outer cohort and underlying capsule identities distinct and validated.

### 11. Evidence artifacts

Publish exactly:

- `manifest.json`;
- `study.json`;
- `cases.json`.

The casebook must permit full reconstruction of:

- seed direction;
- alternating state transitions;
- extreme replacement and frozen extreme ATR;
- confirmation rule/time;
- emitted/skipped geometry;
- real/control identities and outcomes;
- pairs, fold accounting, metrics, gates and disposition.

Semantic validation recomputes from frozen source plus YAML and rejects:

- unsafe paths, symlinked parents/members, non-regular files;
- member/schema/hash/length/config/source/commit mismatch;
- rehashed detector/state/geometry/timing/control/outcome/pair/metric/gate or
  disposition tampering.

Generated V2.2 evidence stays ignored. V1.12, V2.0, and V2.1 evidence remain
immutable and semantically valid.

## Implementation Order

1. Create the V2.2 branch from `bd6c732`; confirm only the five known plan
   drafts are untracked.
2. Run impact analysis for detection exports, shared first-revisit metrics,
   frozen inputs, artifact services, architecture tests, and protected studies.
3. Write controlled state-machine tests before detector implementation.
4. Implement the pure unregistered causal swing detector.
5. Add strict V2.2 YAML and canonical study contracts.
6. Implement causal cases, matched controls, outcomes, paired metrics, exact
   decision topology, runner, artifacts, semantic validator, and canonical CLI.
7. Add adversarial causality, threshold, state, identity, boundary, gate,
   determinism, tamper, path-safety, and import tests.
8. Run focused tests plus V2.1/V2.0/protected V1.12 semantic validations.
9. Run Ruff, compile/import, CLI help, architecture, diff and full SR checks.
10. Commit implementation/tests/config before observing evidence.
11. Run the exact frozen study twice from that implementation commit.
12. Require identical bundle ID and member bytes.
13. Validate the bundle semantically with explicit implementation/bundle IDs.
14. Update one coder-to-review handoff with exact identities, counts,
    diagnostics, disposition, commands and worktree state.
15. Commit only the handoff. Do not merge or start another hypothesis.

Once valid evidence is observed, no detector, threshold, geometry, gate, fold,
source, control, or outcome change may respond to the result.

## Acceptance Criteria

### Detector/state machine

- First unequal close seeds exactly one search direction.
- Equal-close prefixes remain unseeded.
- Strict new extremes replace price and frozen ATR.
- Equal extreme prices keep the earlier bar.
- A new extreme cannot confirm on the same bar.
- Exact 1.5 ATR reversal equality confirms.
- Sub-threshold reversal does not confirm.
- Confirmed internal swings alternate.
- Zero-wick swing transitions state without emitting fallback geometry.
- Extreme ATR qualifies reversal; confirmation ATR owns candidate identity.
- Full replay equals every eligible prefix projection.
- Future suffixes cannot rewrite prior candidates.
- Malformed type/state/order/time/duplicate/non-finite inputs fail closed.
- Detector has no numeric defaults, registry, pandas/numpy, provider, network,
  trendline, legacy SR, or runtime dependencies.

### Controls/outcomes/metrics

- Actual `close[t-1]` is bound by the real case and both controls.
- Exactly two ordered controls exist for every in-fold candidate.
- Real and controls can touch on different bars.
- Outcome changes do not affect causal IDs.
- Search bars 50/51 and fold/horizon boundaries are explicit.
- Same-side pairing and arithmetic are exact.
- All three dispositions and readiness precedence are tested.
- Gate topology and thresholds fail closed under mutation.

### Evidence/architecture

- Two runs from one implementation commit are byte-identical.
- Full semantic reconstruction returns the same study/disposition.
- Rehashed state, threshold, prior-close, touch, pair, metric, gate and
  disposition tampering is rejected.
- Bundle/member/parent symlink and non-regular path attacks are rejected.
- V1.12, V2.0, and V2.1 protected evidence validates unchanged.
- No sibling-study, trendline, legacy SR, provider, holdout, runtime, viewer,
  database, or production dependency exists.
- Focused/full SR, Ruff, compile/import, CLI, architecture and diff checks pass.

## Explicit Non-Goals

- No V1/V2.0/V2.1 detector or evidence reinterpretation.
- No RDP or conventional repainting ZigZag.
- No fixed-span pivot combined with the reversal state machine.
- No threshold grid, min-segment parameter, depth/backstep parameter, scoring,
  smoothing or parameter optimization.
- No volume POC, FVG, order block, liquidity sweep, round number, VWAP,
  trendline, regime, feature ensemble, ML or RL.
- No provider, refresh, new asset/timeframe, holdout, production config,
  runtime registration, lifecycle integration, viewer, database, deployment,
  trading or merge.
- No V2.3 or rescue study.

## Stop Rule

This is the final price-only V2 screening hypothesis on the reused TAOUSDT
development cohort.

- If `SWING_REVERSAL_BEATS_NAIVE_NULL`, freeze the result and require a
  separately approved fresh multi-asset/timeframe validation plan before any
  runtime work.
- If negative or insufficient, stop adding price-structure kernels on this
  cohort. Do not cycle through fractals, FVG, order blocks, or parameter
  variations. Route the model to descriptive shadow-context/retirement
  decision instead.

Even a positive result is development screening under repeated hypothesis use;
it is not holdout evidence or production authorization.

## Required Coder Handoff

Return one review-ready package containing:

- branch/base and implementation/docs commits;
- changed-file inventory and blast radius;
- detector state/threshold/geometry contract;
- exact source/config/implementation identities;
- bundle/study/member hashes and byte lengths;
- swing/candidate/control/status/pair/fold/gate/disposition accounting;
- deterministic double-run proof;
- focused/full/static/boundary/semantic validation;
- protected V1.12/V2.0/V2.1 evidence status;
- worktree state;
- explicit confirmation of no provider, holdout, runtime, production, merge,
  tuning, or next-hypothesis work.

A negative or insufficient result completes V2.2; it is not an implementation
failure and must not trigger rescue tuning.
