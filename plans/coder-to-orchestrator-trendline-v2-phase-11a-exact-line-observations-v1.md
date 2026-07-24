# Coder to Orchestrator: Trendline V2 Phase 11A

Status: `READY_FOR_ORCHESTRATOR_REVIEW`

## 1. Execution identity

- Branch: `feature/trendline-v2-phase-11a-exact-line-observations-v1`
- Base commit: `aacbae339d6ae4a17aaea7680ec78bdd87c9fb4b`
- Commit created: no
- Phase 11A interaction provider/network calls: `0 / 0`

## 2. Exact changed-file scope

Only these nine files changed:

```text
src/libs/models/trendline_v2/__init__.py
src/libs/models/trendline_v2/api.py
src/libs/models/trendline_v2/interaction/__init__.py
src/libs/models/trendline_v2/interaction/contracts.py
src/libs/models/trendline_v2/interaction/observations.py
tests/models/trendline_v2/test_api.py
tests/models/trendline_v2/test_interaction_contracts.py
tests/models/trendline_v2/test_interactions.py
plans/coder-to-orchestrator-trendline-v2-phase-11a-exact-line-observations-v1.md
```

No provider, selection, tracking, configuration, YAML, runtime, viewer,
storage, Regime, MTF or legacy trendline file changed.

## 3. Policy and identities

Policy namespace:

```text
trendline_v2_interaction_observation_policy
```

Canonical policy payload is the approved Phase 11A payload with:

```text
policy_name=exact_line_bar_observation
policy_version=v1
source_family_scope=active_families_only
family_coverage=exactly_one_observation_per_active_family
line_projection_time=bar_timestamp
distance_definition=price_minus_exact_line_price
wick_intersection_rule=low <= exact_line_price <= high
body_intersection_rule=min(open, close) <= exact_line_price <= max(open, close)
same_step_visibility_rule=bar_timestamp >= tracking_observed_at and bar_available_at > tracking_observed_at
source_input_advancement_rule=bar_source_input_identity != tracking_input_identity
ordering_rule=family_id_ascending
threshold_policy=none
```

Derived policy identity:

```text
17a4f5e27483722091881349d775fe17adc018829efc6645d26a223c474bcdb4
```

Other identity namespaces:

```text
trendline_v2_confirmed_interaction_bar
trendline_v2_exact_line_bar_observation
trendline_v2_interaction_snapshot
```

All IDs are lowercase SHA-256 content identities. Serialization is strict and
round-trippable.

## 4. Contracts

`ConfirmedInteractionBar` stores one exact confirmed OHLCV row, its explicit
availability timestamp and source input identity. It validates UTC ordering,
finite numeric OHLCV, candle bounds, non-negative volume and canonical `bar_id`.

`ExactLineBarObservation` stores raw timestamp-space line projection, four
price differences, absolute close distance, wick/body containment, close
relation and candle direction. Its constructor recomputes all persisted
formula fields and canonical `observation_id`.

`InteractionObservationDiagnostics` enforces non-negative integer counts,
`observation_count == source_active_family_count`, exact support/resistance
population, and intersection count bounds.

`TrendlineInteractionSnapshot` is immutable. It enforces one observation per
active family, sorted unique family IDs, bar/tracking ownership, causal timing,
advanced source identity, exact diagnostic derivation and canonical
`snapshot_id`. `create()` accepts typed `source_tracking` and derives all
tracking-owned fields before calling `validate_source_tracking()`. Structural
`from_dict()` decoding is deliberately separate; decoded payloads require
explicit source validation before use. Empty active-family snapshots are valid.

## 5. Causal timing

Observation order is:

```text
tracking snapshot fixed at t
        -> later confirmed bar
        -> frozen active-family projection
```

Required checks:

```text
bar.timestamp >= tracking.observed_at
bar.available_at > tracking.observed_at
bar.source_input_identity != tracking.input_identity
```

Frame extraction requires an exact, unique row with
`timestamp < frame.observed_at`; it does not use nearest lookup, rounding or
future rows. `available_at` is exactly `frame.observed_at` and source identity is
exactly `frame.input_identity`. Future-prefix bar identity invariance is tested.

## 6. Exact formulas

For each active family:

```python
line = family.current_candidate.geometry.value_at(bar.timestamp)
open_minus_line = bar.open - line
high_minus_line = bar.high - line
low_minus_line = bar.low - line
close_minus_line = bar.close - line
absolute_close_distance = abs(close_minus_line)
wick_intersects_line = bar.low <= line <= bar.high
body_intersects_line = min(bar.open, bar.close) <= line <= max(bar.open, bar.close)
```

Close relation uses exact sign (`below`, `on`, `above`). Candle direction uses
exact `close` versus `open` (`down`, `flat`, `up`). No ATR, tick size,
threshold, tolerance, zone or breach state exists in Phase 11A.

## 7. Public API and exports

Added thin wrappers:

```text
build_trendline_interaction_bar(frame, timestamp=...)
observe_trendline_family_interactions(tracking, bar, policy=...)
```

Root exports add the approved interaction contracts and wrappers while
retaining all existing Trendline V2 exports.

## 8. Dependency audit

Dependency direction is:

```text
domain / input / tracking -> interaction -> public API
```

Interaction code has no imports from discovery, selection, provider,
configuration, YAML, scripts, viewer, storage, Regime, network, legacy
trendline packages or `trendline_family`. Observer tests also prove provider
discovery is not executed.

## 9. Validation

```text
Focused interaction/tracking/API suite: 139 passed
Protected V2 + viewer suite:             281 passed
Protected Trendline Family suite:        400 passed
Provider benchmark harness:                4 passed
Frontend Node/TypeScript suite:            13 passed
npm audit:                                  0 vulnerabilities
Ruff:                                       passed
compileall:                                 passed
git diff --check:                           passed
```

The focused count includes the final diagnostics-cardinality regression. No
network request, Binance call or external evidence generation occurred. The
four-test provider benchmark is an existing offline regression harness run;
the Phase 11A interaction observer itself has no provider execution path.

## 10. Codebase-memory status

Post-remediation full-repository reindex was attempted. The indexing worker
crashed on a file and returned a contained non-zero outcome; no workaround or
source broadening was used. Existing split source index remains non-zero but
does not include this uncommitted Phase 11A work. This is tooling evidence, not
an implementation failure.

## 11. Limitations and next boundary

Phase 11A intentionally does not classify proximity or interaction meaning.
It adds no ATR normalization, interaction envelope, tick-size floor, distance
threshold, FAR/APPROACHING/CONTACT label, wick/body/close breach state,
multi-bar event, pressure, breakout, retest, role reversal, approximate
matching, MTF, viewer, storage, YAML, provider or network behavior.

Phase 11A observations are contract-foundation work only.

`latest_valid_predecessor_v1` is not approved as the source family set for
normalized interactions, lifecycle events, viewer integration or trading
interpretation.

BTCUSDT 4h checkpoint evidence:

```text
raw candidates:                 2,697
selected families:                321
median selected anchor span:        4 bars
selected span at most 4 bars:     200 / 321
selected span at most 8 bars:     300 / 321
selected span at least 24 bars:     2 / 321
```

Visual output forms local upper/lower envelopes rather than sparse structural
trendlines. Next model phase must redesign and empirically validate structural
candidate selection before Phase 11B.

Next boundary: `Structural Trendline Selection V2`.

```text
READY_FOR_ORCHESTRATOR_REVIEW
```
