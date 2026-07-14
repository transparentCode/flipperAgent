# Trendline Family Model — Phase D Review

## Current Mode

Quant review.

## Decision

**Revision required. Phase E is blocked.**

The Phase-D runtime implementation is directionally correct: interaction ATR is separately owned, zone construction preserves exact geometry, support/resistance classification is mirrored, counter ownership follows the approved handoff, observations are persisted before snapshot identity is generated, and no later-phase event lifecycle leaked into the model.

The remaining blockers are in the typed persistence boundary. The current contracts allow ambiguous or internally contradictory observations that a Phase-E shadow adapter would trust as canonical evidence.

---

## Validation Reproduced

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
146 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,825 nodes
126,726 edges
status: ready
```

---

# Verified Correct Areas

- causal confirmed-bar interaction input;
- independent `interaction.atr_window` ownership;
- `simple_true_range_mean_v1` interaction ATR;
- ATR/tick-floor maximum zone policy;
- exact representative geometry remains unchanged;
- support/resistance mirrored adverse-boundary logic;
- precedence: `CLOSE_BEYOND -> BODY_BREACH -> WICK_BREACH -> IN_ZONE -> APPROACHING -> FAR`;
- deterministic equality behavior at zone boundaries;
- non-negative penetration calculations;
- body/close breach counter increments once per bar;
- wick-only breach does not increment `breach_count`;
- contact states reset `bars_since_touch`;
- `FAR`/`APPROACHING` increment `bars_since_touch`;
- candidate structural touch counts are not inflated;
- active and dormant families receive observations;
- expired families receive no observation;
- interaction failures preserve repository head;
- output features are read from typed observations;
- replay determinism and future-row invariance;
- observations are included in content-addressed snapshot identity;
- no Phase-E-or-later scope was introduced.

---

# Blocking Findings

## P1 — Snapshot permits multiple contradictory observations for one family

Location:

```text
src/libs/models/trendline_family/contracts.py
TrendlineFamilySnapshot.__post_init__
```

The snapshot validates unique `observation_id` values and set coverage of family IDs, but it does not require unique observation `family_id` values.

Reproduced:

```text
one published support family
observation A: WICK_BREACH
observation B: IN_ZONE
both reference the same family
snapshot accepted
```

`build_interaction_features()` then creates a dictionary by `family_id`, silently overwriting one observation with the other. The selected result depends on deterministic ordering rather than a valid one-to-one contract.

Required:

- observation family IDs must be unique;
- when observations are present, there must be exactly one observation for every published active/dormant family;
- `len(observations) == len(active_families) + len(dormant_families)`;
- `build_interaction_features()` should defensively reject duplicate family observations even though the snapshot contract should make them impossible.

Backward-compatible Phase-C snapshots with `observations=()` remain valid.

---

## P1 — Observation is not bound to the published family's role and exact geometry

Location:

```text
src/libs/models/trendline_family/contracts.py
TrendlineFamilySnapshot.__post_init__
```

The snapshot only checks that `observation.family_id` exists. It does not verify that the observation describes that family's actual representative.

Reproduced accepted states:

```text
SUPPORT family + RESISTANCE observation

family representative at timestamp = 100
observation exact line / zone center = 110
```

This violates the core Phase-D guarantee that the observation is derived around the unchanged exact representative line.

Required for every observation:

```text
observation.role == family.current_role
observation.exact_line_price == family.representative.value_at(snapshot.timestamp)
observation.zone.center_price == family.representative.value_at(snapshot.timestamp)
observation.zone.line_id == family.family_id
```

Use a documented deterministic floating-point tolerance suitable for existing `LineGeometry` projection semantics.

---

## P1 — Observation cross-field audit invariants are under-validated

Location:

```text
src/libs/models/trendline_family/contracts.py
FamilyInteractionObservation.__post_init__
```

The runtime generator emits coherent values, but the canonical contract accepts contradictory persisted evidence.

Reproduced accepted examples:

```text
WICK_BREACH with positive body penetration

tick_size = 0.25
minimum_zone_ticks = 1
tick_half_width = 99.0
tick_floor_applied = false

zone absolute half-width = 0.25
zone.width_atr = 99.0
```

Required state-specific penetration invariants:

```text
FAR / APPROACHING / IN_ZONE:
    wick = body = close = 0

WICK_BREACH:
    wick > 0
    body = 0
    close = 0

BODY_BREACH:
    wick >= body > 0
    close = 0

CLOSE_BEYOND:
    wick >= body >= close > 0
```

Required zone/audit relationships:

```text
absolute_half_width = zone.upper_price - zone.center_price
absolute_half_width = zone.center_price - zone.lower_price
zone.width_atr = absolute_half_width / interaction_atr

selected_half_width = max(atr_half_width, tick_half_width or 0)
absolute_half_width = selected_half_width

when tick_size is present:
    tick_half_width = tick_size * minimum_zone_ticks
    tick_floor_applied = tick_half_width >= atr_half_width

when tick_size is absent:
    tick_half_width is None
    tick_floor_applied is false
```

The current close-based distance semantics should also be explicit and validated:

```text
distance_to_zone_atr = max(
    distance_to_line_atr - zone.width_atr,
    0,
)
```

Do not add raw candle OHLC fields in this remediation; that was not part of the approved Phase-D contract.

---

## P1 — Snapshot-level interaction ATR audit can disagree with observations

The tracker computes one interaction ATR for one asset/timeframe/bar, but the snapshot contract does not enforce that all observations share it or that snapshot diagnostics agree with it.

Required when observations are non-empty:

- all observations use the same `interaction_atr`;
- all use the same `interaction_atr_method`;
- all use the same `interaction_atr_sample_count`;
- snapshot diagnostics `interaction_atr`, `interaction_atr_method`, `interaction_atr_sample_count`, and `interaction_observation_count` match the typed observations;
- comparisons use deterministic numeric tolerance where appropriate.

For legacy Phase-C snapshots with no observations, these checks should not be required.

---

# Non-Blocking Notes

- `tracker.py` and `api.py` module docstrings still describe Phase C. They can be updated while touching the files, but this is documentation-only.
- Historical-market replay remains deferred and is an accepted residual risk.
- `calculate_interaction_atr()` is safe in the tracker because it receives the normalized/coherent confirmed frame. Direct-helper OHLC coherence validation is optional for this remediation.

---

# Blast Radius

Expected remediation scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/features.py
```

Bounded changes may be made to:

```text
src/libs/models/trendline_family/interactions.py
src/libs/models/trendline_family/tracker.py
tests/models/trendline_family/
```

No config field or classification-policy change is required.

---

# Codex Remediation Prompt

```text
Apply Phase-D remediation only using:

- plans/trendline-family-phase-d-review.md
- plans/trendline-family-phase-c-approval.md
- plans/trendline-family-model-architecture-plan.md
- plans/trendline-family-codex-phase-execution-plan.md

Do not start Phase E.

Required work:

1. Enforce one typed observation per published family.
   - observation family IDs must be unique
   - when observations are non-empty, exactly one observation must exist
     for every active/dormant family
   - legacy snapshots with observations=() remain decodable
   - defensively reject duplicate family observations in feature building

2. Bind every observation to its published family.
   - observation.role == family.current_role
   - exact_line_price equals family.representative.value_at(snapshot.timestamp)
   - zone.center_price equals the same projected exact line value
   - zone.line_id == family.family_id

3. Harden FamilyInteractionObservation cross-field invariants.
   - enforce state-specific penetration relationships
   - enforce zone absolute half-width / width_atr / interaction_atr relation
   - enforce selected half-width = max(ATR half-width, tick half-width)
   - enforce tick_half_width = tick_size * minimum_zone_ticks
   - enforce tick_floor_applied truthfully
   - enforce current close-based distance relation:
       distance_to_zone_atr = max(distance_to_line_atr - zone.width_atr, 0)

4. Enforce snapshot interaction-ATR audit consistency.
   - all observations share ATR value, method and sample count
   - snapshot interaction diagnostics match typed observations
   - interaction_observation_count equals len(observations)
   - skip these requirements for backward-compatible empty-observation snapshots

5. Add adversarial regression tests proving rejection of:
   - duplicate observations for one family
   - observation role mismatch
   - observation center/geometry mismatch
   - WICK_BREACH with body penetration
   - BODY_BREACH with close penetration
   - inconsistent width_atr
   - inconsistent tick_half_width or tick_floor_applied
   - inconsistent distance_to_zone_atr
   - per-observation ATR mismatch
   - snapshot diagnostic/observation ATR mismatch

6. Preserve already-approved runtime behavior.
   Do not alter:
   - support/resistance classification precedence
   - zone boundary equality semantics
   - ATR/tick maximum policy
   - bars_since_touch ownership
   - breach_count ownership
   - family/member identity
   - lifecycle transition types
   - content-addressed snapshot generation

7. Add a direct regression test that:
   - identical observation evidence produces the same observation ID
   - changed state/zone/tick evidence produces a different observation ID

Do not implement:

- RegimeV2 integration
- multi-bar confirmation
- breakout/retest/failed-break sequencing
- role reversal
- split/merge
- multi-rail/channel families
- MTF
- optimization
- trading policy

Run:

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

ruff check \
  src/libs/models/trendline_family \
  tests/models/trendline_family

PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family

Reindex and run codebase-memory scope validation.
Return the mandatory review package and stop.
```

---

## Next Gate

After this remediation, perform a focused Phase-D re-review. Phase E should begin only when persisted typed observations are unambiguous and internally coherent, because the shadow adapter will consume those artifacts without recomputing their semantics.
