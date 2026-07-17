---
goal: Implement causal pivot detection and deterministic zone association for SR-V1.2 on the approved stateful foundation.
stage: orchestrator-to-coder
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, detection, pivots, association, causality]
source_agent: Quant Orchestrator
target_agent: Coder Agent
source_branch: feature/sr-v1.1-lifecycle
source_commit: 5f3a0c7
target_branch: feature/sr-v1.2-detection-association
---

# Orchestrator To Coder: SR-V1.2 Detection And Association v1

## Decision And Phase Gate

SR-V1.0 foundation/configuration and SR-V1.1 lifecycle are approved. Implement
**SR-V1.2 causal pivot detection and deterministic association only**, then
stop for Quant Review.

Start from the exact approved V1.1 handoff commit:

```text
5f3a0c7  docs(sr): add lifecycle hardening handoff
9b4f6cf  fix(sr): harden lifecycle fail-closed checks
```

Create `feature/sr-v1.2-detection-association` from `5f3a0c7`. Do not merge
V1.1 or V1.2.

No production caller currently imports the new SR package, so the approved
contract extensions below may update all isolated SR construction sites
explicitly. Do not add compatibility defaults that conceal missing causal
inputs.

## Approved V1.2 Policy

These decisions are fixed:

- Pivot detection is causal and uses a symmetric closed-bar window.
- `pivot_span_bars` is both the left and right span.
- A pivot becomes available only after all right-hand confirmation bars close.
- Tied or plateau extrema do not form pivots; the center must be a unique
  strict extremum.
- ATR is supplied causally by the upstream bar source as
  `ClosedBar.atr_at_close`.
- The SR model does not choose or hardcode an ATR period or calculation method
  in V1.2.
- Lifecycle thresholds continue using each zone's frozen
  `atr_at_creation`; current-bar ATR must not alter an existing zone.
- New-zone width uses the confirmation bar's `atr_at_close`.
- Existing-zone lifecycle is processed before candidate insertion.
- A candidate is compared with the nearest same-side eligible zone.
- Association suppresses a duplicate candidate; it never moves, widens,
  averages, strengthens, or otherwise mutates an existing zone.
- Unmatched candidates create new `ACTIVE` zones with frozen geometry.
- Newly created zones cannot interact on their availability bar.
- No eviction or ranking occurs when `max_active_zones` is reached.
- Candidate/cap tie-breaking is deterministic identity ordering, not a market
  quality score.
- The exact eight-parameter YAML surface remains unchanged.

## Public Engine Contract

Preserve the approved public call and return shape:

```python
new_state, snapshot, events = SREngine().step(
    previous_state,
    closed_bar,
    resolved_config,
)
```

```python
tuple[SRState, SRSnapshot, tuple[SREvent, ...]]
```

Do not add candidate, ATR, history, runtime-override, detector, or association
arguments to `SREngine.step`.

The engine obtains the causal ATR from `closed_bar.atr_at_close` and the
minimal pivot window from `previous_state.recent_bars`.

## Required File Structure

```text
src/libs/models/sr/
  domain/
    contracts.py
  detection/
    __init__.py
    pivots.py
  association/
    __init__.py
    matcher.py
  lifecycle/
    engine.py
  __init__.py

tests/models/sr/
  domain/
    test_contracts.py
  detection/
    __init__.py
    test_pivots.py
  association/
    __init__.py
    test_matcher.py
  lifecycle/
    test_engine.py
```

Keep `SREngine` in its existing module for V1.2 to preserve the approved
import surface and avoid a cosmetic orchestration refactor. Detection and
association logic must live in their descriptive packages, not inline in the
engine.

Do not copy legacy files or import `app.sr` / `libs.sr`. The legacy pivot
kernel is reference-only.

## ClosedBar Contract Extension

Add one mandatory field:

```text
atr_at_close: float
```

It must be finite and strictly positive.

The complete V1.2 `ClosedBar` data contract is:

```text
state_key
bar_id
closed_at
open
high
low
close
atr_at_close
```

Update every SR construction site explicitly. Do not give
`atr_at_close` a numeric default or make it optional.

Semantics:

- it is a point-in-time value available at `closed_at`;
- upstream owns its causal calculation and lineage;
- V1.2 hashes derived candidate/zone identity with the supplied ATR value;
- lifecycle code must continue ignoring current `atr_at_close` for existing
  zones.

Do not add ATR period, method, smoothing, warmup, fallback, clipping, or
imputation parameters.

## SRState Rolling Detection Buffer

Add a mandatory immutable field:

```text
recent_bars: tuple[ClosedBar, ...]
```

This buffer is model state, not a feature artifact.

Domain validation must require:

- every item is exactly `ClosedBar`;
- every bar has the same `state_key` as `SRState.state_key`;
- `closed_at` values are strictly increasing;
- `bar_id` values are unique;
- if non-empty, the final bar ID equals `last_processed_bar`.

The domain contract cannot validate the maximum length because that depends on
resolved configuration. `SREngine.step` must fail closed if:

```text
len(previous_state.recent_bars) > 2 * pivot_span_bars
```

Initial empty states must set `recent_bars=()` explicitly.

For each successful step:

1. append the new closed bar;
2. use the resulting sequence for current pivot confirmation;
3. retain only the most recent `2 * pivot_span_bars` bars in
   `new_state.recent_bars`.

Do not store an unbounded OHLC history. Do not add bar history to
`SRSnapshot` in V1.2.

## Sequential Bar Preconditions

In addition to all V1.1 preconditions:

- reject the current `bar_id` if it exists anywhere in `recent_bars`;
- when `recent_bars` is non-empty, require
  `closed_bar.closed_at > recent_bars[-1].closed_at`;
- reject a state whose non-empty buffer does not end at
  `last_processed_bar`;
- retain V1.1 runtime chronology and config/state ownership validation.

These checks close same-timestamp/different-ID double processing for the
incremental V1.2 path. General restart, replay, gap, and out-of-order policy
remains a V1.3 responsibility.

## Pivot Detector API

Implement one pure public function:

```python
detect_confirmed_pivots(
    bars: tuple[ClosedBar, ...],
    config: DetectionConfig,
) -> tuple[CandidateLevel, ...]
```

Export it from `libs.models.sr.detection`, not from the package root.

The detector:

- has no internal state;
- accepts only closed bars;
- reads no YAML or filesystem state;
- uses no pandas, NumPy, Polars, TA library, smoothing, scoring, or volume;
- returns candidates confirmed by the final bar only.

Let:

```text
span = config.pivot_span_bars
window_size = 2 * span + 1
window = bars[-window_size:]
center = window[span]
confirmation = window[-1]
```

If fewer than `window_size` bars exist, return `()`.

Validate that the selected window:

- contains exact `ClosedBar` instances;
- has one common `state_key`;
- has strictly increasing timestamps;
- has unique bar IDs.

If more than `window_size` bars are supplied, use only the final window.
The engine itself must never retain more than `2 * span` bars after a step.

## Exact Pivot Rules

### Resistance pivot

The center bar is a resistance pivot only when:

```text
center.high > every other bar.high in the window
```

Equality with any other high rejects the pivot.

### Support pivot

The center bar is a support pivot only when:

```text
center.low < every other bar.low in the window
```

Equality with any other low rejects the pivot.

A single center bar may satisfy both rules and emit two candidates.

Do not use close prices, candle direction, volume, prominence, minimum
movement, scoring, or smoothing to qualify pivots.

## Candidate Construction

For every confirmed candidate:

```text
atr_at_creation = confirmation.atr_at_close
half_width = config.zone_half_width_atr * atr_at_creation
formed_at = center.closed_at
available_at = confirmation.closed_at
source = "pivot_v1"
```

Resistance:

```text
side = RESISTANCE
center = center.high
```

Support:

```text
side = SUPPORT
center = center.low
```

Validate all ATR-scaled products and final geometry bounds for finiteness
before constructing the candidate. Continue relying on `ZoneGeometry` for
positive-price/lower-bound validation.

Candidate ordering is:

```text
(formed_at, available_at, candidate_id)
```

This ordering is mechanical and deterministic. It is not a quality ranking.
When support and resistance are confirmed by the same center bar, identity
ordering decides which is considered first if capacity has only one slot.

## Association API

Implement one pure function:

```python
match_candidate(
    candidate: CandidateLevel,
    zones: tuple[ZoneRecord, ...],
    config: AssociationConfig,
) -> ZoneRecord | None
```

Export it from `libs.models.sr.association`, not from the package root.

Validate exact input types, ownership, finite geometry, and ATR-derived
distance.

A zone is eligible only when the caller includes it in `zones`. For each
eligible zone:

- `definition.state_key` must match `candidate.state_key`;
- `definition.side` must match `candidate.side`.

Distance and threshold are:

```text
distance = abs(candidate.geometry.center - zone.definition.geometry.center)
threshold = config.merge_distance_atr * candidate.atr_at_creation
```

A zone matches when:

```text
distance <= threshold
```

Threshold equality is a match.

Select the match using:

```text
(distance, zone_id)
```

The nearest zone wins; `zone_id` is the exact deterministic tie-break.

The matcher must not mutate the candidate, record, definition, geometry, or
runtime state. It returns the existing `ZoneRecord` or `None`; do not add
a generic association framework or score.

## Engine Processing Order

`SREngine.step` must use this exact order:

1. Validate all state/bar/config/buffer/lifecycle preconditions for the full
   aggregate before producing any event.
2. Capture the IDs of zones that were `ACTIVE` or `BREACH_PENDING` at the
   start of the step.
3. Process lifecycle transitions for every existing zone using the V1.1
   rules.
4. Form the detection window from `recent_bars + (closed_bar,)`.
5. Detect candidates confirmed by the current bar.
6. Sort candidates by the approved canonical candidate order.
7. Associate each candidate against:
   - zones that were non-terminal at the start of this step, even if they
     became terminal during lifecycle processing;
   - any zone already created earlier in this candidate batch.
8. Suppress matched candidates without changing the matched zone.
9. For an unmatched candidate, create a zone only if capacity remains.
10. Append created zones/events after lifecycle processing.
11. Construct the new state, bounded recent-bar buffer, snapshot, and
    canonical returned events.

Using the start-of-step non-terminal association pool gives an existing zone
one-bar precedence when it breaks or expires on the same bar. On later bars,
previously terminal zones do not participate. This avoids both immediate
same-bar recreation and permanent blocking by retained terminal zones.

## Zone Creation

For an unmatched candidate with capacity:

`ZoneDefinition`:

```text
state_key = candidate.state_key
side = candidate.side
geometry = candidate.geometry
source = candidate.source
created_at = candidate.formed_at
available_at = candidate.available_at
atr_at_creation = candidate.atr_at_creation
config_hash = resolved_config.resolved_config_hash
```

`ZoneRuntimeState`:

```text
status = ACTIVE
touch_count = 0
fakeout_count = 0
pending_breach_count = 0
age_bars = 0
last_interaction_at = None
updated_at = candidate.available_at
```

Emit one `CREATED` event:

```text
zone_id = new zone ID
event_type = CREATED
timestamp = candidate.available_at
price = candidate.geometry.center
bar_id = confirmation/current closed bar ID
```

The new definition and geometry are frozen immediately. The new zone is
inserted after lifecycle processing and therefore cannot touch, breach, age,
expire, or fake out on its creation/availability bar.

## Association Suppression

When a candidate matches:

- do not create a zone;
- do not emit `CREATED` or another event;
- do not update touch/fakeout/pending/age counters;
- do not update timestamps;
- do not change geometry;
- do not average ATR or center;
- do not preserve an association score.

The pure detector and matcher APIs provide deterministic test/audit surfaces.
V1.2 does not add candidate/association history to `SRState` or
`SRSnapshot`.

## Active-Zone Capacity

For V1.2, capacity counts only:

```text
ACTIVE + BREACH_PENDING
```

`BROKEN` and `EXPIRED` are retained but do not consume active capacity.

Before lifecycle processing, fail closed if the previous state already
contains more non-terminal zones than
`resolved_config.runtime.max_active_zones`.

After lifecycle processing:

- recalculate remaining capacity;
- create unmatched candidates in canonical candidate order until capacity is
  full;
- suppress further unmatched candidates;
- never evict or rank an existing zone;
- never use price proximity, side, strength, score, age, or recency to decide
  capacity order beyond the approved candidate identity ordering.

A candidate suppressed only because capacity is full emits no event.

## Fail-Closed Numeric Requirements

All operands are individually finite by domain/config contracts, but derived
operations must also be checked.

Reject non-finite:

- `zone_half_width_atr * confirmation.atr_at_close`;
- derived candidate lower/upper bounds;
- `merge_distance_atr * candidate.atr_at_creation`;
- candidate-to-zone center distance.

Raise `ContractValidationError`; never silently turn overflow into a match,
non-match, zero-width zone, or universal-width zone.

Do not clip or substitute fallback values.

## Required Tests

At minimum:

### ClosedBar and SRState

- `atr_at_close` accepts positive finite values and rejects zero, negative,
  NaN, and infinity;
- mandatory ATR has no default;
- recent bars are immutable and canonical;
- recent-bar ownership mismatch rejection;
- duplicate bar ID rejection;
- equal/decreasing timestamp rejection;
- non-empty buffer must end at `last_processed_bar`;
- engine rejects a buffer longer than `2 * span`;
- current bar ID duplicate anywhere in buffer is rejected;
- current timestamp must be strictly later than the buffered final timestamp.

### Pivot detector

- no candidate before `2 * span + 1` bars;
- support and resistance strict pivots;
- unique-extremum requirement;
- tied high and tied low rejection;
- one center bar can emit both sides;
- formed time is the center bar;
- availability time is the final confirmation bar;
- candidate uses confirmation-bar ATR;
- exact zone half-width;
- line geometry when width multiplier is zero;
- chronological shift confirms a pivot once;
- deterministic candidate IDs/order;
- mixed state keys, duplicate IDs, or unordered timestamps fail closed;
- product and final-bound overflow fail closed;
- inputs remain unchanged.

### Association

- same-side match;
- opposite-side non-match;
- ownership mismatch rejection;
- exact threshold equality match;
- outside-threshold non-match;
- nearest-zone selection;
- exact-distance tie by `zone_id`;
- terminal inclusion is controlled only by caller-provided pool;
- product/distance overflow rejection;
- no mutation.

### Integrated engine

- lifecycle events occur before candidate insertion logic;
- warmup bars only advance lifecycle and buffer;
- first confirmed unmatched pivot creates exactly one zone/event;
- new zone has age zero and no same-bar touch;
- created event owns the new snapshot zone;
- matched candidate creates no zone/event and does not mutate the match;
- zone terminalized during the current step still suppresses a same-bar
  candidate;
- the same terminal zone does not suppress a later-bar candidate;
- start-of-step association pool and newly-created batch pool are
  deterministic;
- support and resistance candidates can both be created;
- capacity counts active/pending but not terminal;
- invalid over-cap previous state fails before any event;
- cap never evicts an existing zone;
- one-slot/two-candidate behavior follows candidate identity order;
- recent buffer remains exactly bounded to `2 * span`;
- repeated identical inputs produce identical state/snapshot/events;
- frozen geometry and V1.1 lifecycle behavior remain unchanged;
- exact eight configuration paths remain unchanged.

## Import And Dependency Boundaries

Production V1.2 code may import only:

- Python standard library;
- `libs.models.sr.domain`;
- `libs.models.sr.config`;
- sibling detection/association/lifecycle modules.

It must not import:

- pandas, NumPy, Polars, TA libraries, scipy, sklearn, or ML frameworks;
- YAML outside the approved adapter;
- `app.sr` or legacy `libs.sr`;
- persistence/database/filesystem/network modules;
- trendline, regime, strategy, execution, risk, portfolio, or optimizer code.

Extend the AST boundary tests to cover both `Import` and `ImportFrom` for
any new forbidden dependency names.

## Exact Configuration Surface

Do not add, remove, rename, or reinterpret fields:

```text
detection.pivot_span_bars
detection.zone_half_width_atr
association.merge_distance_atr
lifecycle.touch_tolerance_atr
lifecycle.break_buffer_atr
lifecycle.break_confirm_closes
lifecycle.max_age_bars
runtime.max_active_zones
```

V1.2 owns only the two detection fields, one association field, and active-zone
capacity. ATR input is market data, not configuration.

No asset/timeframe tuning values may be added to `configs/sr.yaml`.

## Explicit Non-Goals

Do not implement:

- alternate pivot methods, zigzag, fractals beyond the approved strict window,
  smoothing, prominence, volume confirmation, candle-pattern rules, or scores;
- geometry averaging, strength, quality, confidence, decay, touch weighting,
  merge weighting, or candidate ranking;
- active-zone eviction;
- persistent candidate or association history;
- terminal retention/pruning policy;
- automatic support/resistance flips or role reversal;
- breakout/retest setup logic;
- persistence adapters, state stores, checkpoints, replay, restart parity, or
  full out-of-order recovery;
- MTF composition;
- regime/trendline integration;
- ML, optimization, feature production, or trading policy;
- migration or runtime integration with legacy S/R;
- ATR calculation, ATR-period configuration, or ATR fallback logic.

## Acceptance Commands

Run and report:

```bash
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/detection tests/models/sr/association tests/models/sr/lifecycle -q
.venv/bin/python -m pytest tests/models/sr/config tests/models/sr/adapters -q
.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q
ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr
.venv/bin/python -c "from libs.models.sr import ClosedBar, SREngine; from libs.models.sr.detection import detect_confirmed_pivots; from libs.models.sr.association import match_candidate; print('ok')"
rg -n "app\.sr|libs\.sr|pandas|numpy|polars|scipy|sklearn" src/libs/models/sr tests/models/sr
git diff --check
```

Run independent probes for:

1. the earliest causal pivot confirmation;
2. tied extrema producing no candidate;
3. confirmation-bar ATR ownership;
4. a current-bar-broken zone suppressing same-bar recreation;
5. the retained terminal zone allowing a later new episode;
6. nearest same-side association with exact tie-breaking;
7. one-slot/two-candidate deterministic capacity behavior;
8. ATR width/merge/final-bound overflow;
9. duplicate/equal-time bar rejection;
10. aggregate preflight producing no partial events.

## Mandatory Coder Handoff

Return a coder-to-review handoff containing:

- target branch and implementation commit;
- exact approved base commit;
- exact files added/changed;
- ClosedBar/SRState compatibility impact;
- pivot timing and tie semantics;
- ATR ownership and geometry calculation;
- association pool, threshold, nearest/tie logic, and suppression behavior;
- capacity behavior;
- engine ordering map;
- call/callee and blast-radius analysis;
- all test/check/probe outputs;
- confirmation that the exact eight-parameter surface is unchanged;
- confirmation that no tuning values, detector variants, persistence,
  features, optimization, or legacy imports were added;
- known risks and deliberately deferred V1.3 items.

Stop after the V1.2 implementation and handoff. Do not begin persistence,
replay, research evaluation, feature work, tuning, or V1.3 without explicit
Quant Review approval.
