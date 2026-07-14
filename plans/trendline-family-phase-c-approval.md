# Trendline Family Model — Phase C Approval

## Current Mode

Quant approval.

## Approval Scope

Phase C deterministic single-timeframe family tracking:

- ATR-normalized family/candidate matching;
- deterministic one-to-one assignment;
- stable family and member identity;
- birth, continuation, strengthening, weakening, dormancy, reactivation and expiry;
- active-family caps and ranking;
- immutable snapshots and transitions;
- content-addressed audit identities;
- replay determinism and future-row invariance;
- fail-closed provider, API and repository-lineage behavior.

## Approval Decision

**Approved. Phase D may begin.**

No unresolved Phase-C blocking issue remains.

## Verified Remediation

The final repository-lineage guard now executes after confirmed-frame validation and before provider execution or persistence.

Repository head identity must exactly match the current tracker config on:

```text
asset
timeframe
model_version
config_version
resolved_config_hash
```

A mismatch raises `TrendlineFamilyUpdateError`; implicit reset or migration is not performed.

Independent Config-A to Config-B reproduction:

```text
repository head: Config A
tracker update: Config B
result: repository head identity mismatch
provider calls: 0
repository head changed: false
```

A subsequent same-Config-A continuation still:

```text
calls provider once
matches the existing family
preserves family identity
publishes valid lineage
```

## Validation Sufficiency

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
110 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,728 nodes
126,079 edges
status: ready
```

Boundary inspection confirms:

- no runtime import from old trendline packages;
- YAML remains confined to `config_loader.py`;
- no Phase-D interaction implementation exists yet.

## Blast Radius Confirmation

Phase C remains self-contained under:

```text
src/libs/models/trendline_family/
tests/models/trendline_family/
configs/trendline_family.yaml
plans/trendline-family-*.md
.codebase-memory/
```

No existing RegimeV2, signal, strategy, risk, execution or legacy trendline runtime path was changed.

## Residual Risk

Acceptable deferred risks:

- validation remains synthetic-fixture based rather than historical-market replay;
- repository implementation remains in-memory;
- explicit config reset/migration is not implemented;
- the native provider currently emits at most one candidate per role;
- interaction zones and per-bar price evidence are not yet present;
- no downstream RegimeV2 consumer is connected.

These are later-phase scope items and do not block Phase D.

## Required Next Handoff

Implement Phase D only. Stop for review before any RegimeV2 integration or multi-bar event lifecycle.

### Phase D objective

Derive volatility-aware interaction zones around exact family representative lines and classify one confirmed candle per family without changing line geometry or family identity.

### Expected production scope

```text
src/libs/models/trendline_family/interactions.py
src/libs/models/trendline_family/features.py
```

Necessary bounded modifications are allowed in:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/api.py
src/libs/models/trendline_family/__init__.py
configs/trendline_family.yaml
```

### Required contracts

Add strict frozen contracts for:

```text
InteractionObservationState
FamilyInteractionObservation
```

Required states:

```text
FAR
APPROACHING
IN_ZONE
WICK_BREACH
BODY_BREACH
CLOSE_BEYOND
```

Each observation must preserve:

- deterministic observation ID;
- family ID and role;
- confirmed timestamp;
- exact line price;
- typed `InteractionZone`;
- interaction ATR value/method/sample count;
- distance to line in ATR units;
- distance to zone in ATR units;
- wick penetration ATR;
- body penetration ATR;
- close penetration ATR;
- candle direction;
- close location inside candle;
- tick-size floor audit metadata.

Persist typed observations in the immutable snapshot rather than hiding the primary evidence only inside a free-form diagnostics mapping. Add backward-compatible default/decoding behavior for snapshots without observations.

Observation and snapshot IDs must remain content-addressed.

### Interaction ATR

Use a separately owned causal interaction ATR:

```text
interaction.atr_window
method: simple_true_range_mean_v1
```

It may use the same mathematical true-range definition as matching, but matching ATR and interaction ATR must remain separately named, configured and audited.

Use only confirmed normalized OHLCV rows at `observed_at`.

If families require classification and no finite positive interaction ATR can be produced, fail closed before persistence and preserve the repository head.

### Zone policy

For family representative line at confirmed timestamp `t`:

```text
center = representative.value_at(t)
atr_half_width = interaction_atr * interaction.tolerance_atr
tick_half_width = tick_size * interaction.minimum_zone_ticks
half_width = max(atr_half_width, tick_half_width when tick_size is supplied)
lower = center - half_width
upper = center + half_width
```

Add typed config only for:

```text
interaction.minimum_zone_ticks: int = 1
```

`tick_size` is runtime market metadata, not an asset YAML hyperparameter. Extend the public API/tracker update with an optional finite positive `tick_size` input. When absent, record that the tick floor was unavailable and use the ATR width only.

Document `InteractionZone.width_atr` as the zone half-width normalized by ATR. Enforce symmetric bounds around the exact center.

Never alter slope, intercept, anchors, representative geometry, family ID or member ID to fit the current candle.

### Role-symmetric classification

Use this precedence:

```text
CLOSE_BEYOND
BODY_BREACH
WICK_BREACH
IN_ZONE
APPROACHING
FAR
```

For SUPPORT, the adverse outer boundary is `zone.lower_price`:

```text
close beyond: close < lower
body breach:  min(open, close) < lower
wick breach:  low < lower
```

For RESISTANCE, the adverse outer boundary is `zone.upper_price`:

```text
close beyond: close > upper
body breach:  max(open, close) > upper
wick breach:  high > upper
```

`IN_ZONE` means candle range intersects the zone after higher-precedence adverse breach checks.

`APPROACHING` means there is no range/zone intersection and the nearest candle extreme is within:

```text
interaction.approaching_distance_atr * interaction_atr
```

of the nearest zone edge.

Otherwise classify `FAR`.

All penetration metrics must be non-negative, measured beyond the adverse outer zone boundary and normalized by interaction ATR. Support and resistance mirror fixtures must produce numerically symmetric metrics.

### State integration

Classify each non-expired active and dormant family on the current confirmed bar before final transition/snapshot IDs are generated.

Interaction evidence belongs to the same single family version produced by the bar update. Do not increment family version twice.

Phase-D ownership of existing counters:

```text
bars_since_touch = 0
```

for `IN_ZONE`, `WICK_BREACH`, `BODY_BREACH` or `CLOSE_BEYOND`; otherwise increment the prior value by one.

Increment `breach_count` only for `BODY_BREACH` and `CLOSE_BEYOND`. A wick-only probe is not yet a confirmed structural breach.

Do not increment candidate-derived `touch_count` or `effective_touch_count`; those remain structural candidate diagnostics.

Do not change lifecycle transition type solely because of an interaction observation in Phase D.

### Feature output

Expose compact output features for nearest active support and resistance:

```text
distance_to_support_line_atr
distance_to_resistance_line_atr
distance_to_support_zone_atr
distance_to_resistance_zone_atr
support_interaction_state
resistance_interaction_state
support_wick_penetration_atr
resistance_wick_penetration_atr
support_body_penetration_atr
resistance_body_penetration_atr
support_close_penetration_atr
resistance_close_penetration_atr
```

Features must be derived from typed observations, not recomputed with different semantics.

Do not connect these features to RegimeV2 in Phase D.

### Reserved config

`interaction.close_confirmation_bars` remains reserved for Phase F multi-bar confirmation. Do not use it to manufacture a multi-bar event in Phase D.

### Required tests

Add under `tests/models/trendline_family/`:

```text
test_interaction_contracts.py
test_interaction_zones.py
test_interaction_evidence.py
test_interaction_symmetry.py
test_interaction_parameter_effects.py
test_interaction_tracker_integration.py
test_interaction_replay.py
```

Acceptance cases:

- exact center line is unchanged by zone construction;
- ATR width and tick-size floor select the correct maximum;
- absent tick size uses ATR only and remains auditable;
- all six states have controlled support and resistance fixtures;
- classification precedence is explicit at boundary cases;
- equality at zone boundaries is deterministic and documented;
- support/resistance mirror cases produce symmetric penetration values;
- tolerance, approaching distance, ATR window and minimum ticks each have parameter-effect tests;
- body and close breaches update `breach_count` once;
- wick-only breach does not increment `breach_count`;
- contact states reset `bars_since_touch`; FAR/APPROACHING increment it;
- touch/effective-touch structural counts are not inflated;
- family/member IDs and exact geometry remain unchanged by interaction width;
- dormant families can be observed without automatic reactivation;
- expired families receive no observation;
- interaction failure does not persist a partial snapshot;
- repeated replay produces byte-identical observations/snapshots;
- future rows do not alter observations at `observed_at=T`;
- content-addressed snapshot IDs change when observation evidence changes;
- all 110 Phase-A/B/C tests continue to pass.

### Forbidden work

Do not implement:

- multi-bar break confirmation;
- breakout/retest/failed-break sequencing;
- role reversal;
- split or merge;
- multi-rail/channel families;
- tick-driven persistent state;
- RegimeV2 integration;
- MTF composition;
- optimization;
- trading policy or compatibility signal labels.

### Validation commands

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q

ruff check src/libs/models/trendline_family tests/models/trendline_family

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
```

Reindex codebase-memory, verify scope, return the mandatory review package and stop after Phase D.
