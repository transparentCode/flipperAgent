# Trendline Family Model — Phase D Re-review

## Current Mode

Quant review.

## Decision

**Revision required. Phase E remains blocked.**

The requested Phase-D remediation is substantially correct. One narrow persistence inconsistency remains in the no-observation/backward-compatibility branch.

---

## Validation Reproduced

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
158 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,852 nodes
126,635 edges
status: ready
```

---

## Verified Remediation

The following prior findings are resolved:

- exactly one observation per published family when observations are present;
- observation family ID uniqueness;
- observation role matches family role;
- observation exact line and zone center match the published representative;
- state-specific penetration invariants;
- symmetric zone and width/ATR consistency;
- tick-size/minimum-ticks/tick-half-width consistency;
- selected ATR/tick half-width consistency;
- close-based distance-to-zone relation;
- one interaction ATR value/method/sample count across observations;
- observation count and interaction ATR diagnostics agree with non-empty observations;
- duplicate-safe feature extraction;
- approved Phase-D runtime classification, counters and replay behavior remain unchanged.

---

# Remaining Finding

## P1 — Empty observation snapshots can claim non-existent interaction evidence

Location:

```text
src/libs/models/trendline_family/contracts.py
TrendlineFamilySnapshot.__post_init__
```

Interaction diagnostic consistency is enforced only inside:

```python
if observations:
    ...
```

When `observations == ()`, the contract accepts arbitrary Phase-D interaction diagnostics.

Reproduced:

```text
observations = ()
interaction_observation_count = 7
interaction_atr = 123.0
interaction_atr_method = "fake"
interaction_atr_sample_count = 99

result: accepted
```

This creates a persisted snapshot where diagnostics claim seven interaction observations and an ATR calculation, while no typed observations exist.

This matters before Phase E because consumers may use:

- `interaction_observation_count` as a coverage/health field;
- interaction ATR diagnostics as normalization metadata;
- typed observations as the primary evidence source.

Those surfaces would disagree.

### Existing compatibility test is not a true Phase-C payload

Current test:

```text
test_snapshot_decoding_defaults_to_empty_observations_for_phase_c_payloads
```

starts from a Phase-D snapshot, removes only the `observations` key, and leaves the positive Phase-D interaction diagnostics intact.

That is not a real Phase-C payload. A real Phase-C payload has no interaction diagnostic fields, or an explicitly empty Phase-D diagnostic set.

---

## Required Semantics

Preserve backward compatibility while enforcing consistency.

### Legacy Phase-C snapshot

When observations are absent and none of these keys exist:

```text
interaction_atr
interaction_atr_method
interaction_atr_sample_count
interaction_observation_count
```

accept the snapshot unchanged.

### Explicit empty Phase-D snapshot

When any interaction diagnostic key is present and observations are empty, require:

```text
interaction_observation_count == 0
interaction_atr is None
interaction_atr_method is None
interaction_atr_sample_count is None
```

Reject:

- positive observation count;
- non-zero or positive ATR;
- non-null method;
- non-null sample count;
- partial contradictory combinations.

The normal tracker-generated empty-family snapshot already uses the explicit empty values above and should remain valid.

---

## Required Tests

Add or correct tests under:

```text
tests/models/trendline_family/test_interaction_contracts.py
```

Required cases:

1. Real Phase-C payload:
   - remove `observations`;
   - remove all four interaction diagnostic keys;
   - decode successfully with `observations == ()`.

2. Explicit empty Phase-D payload:
   - `observations == ()`;
   - count `0`;
   - ATR/method/sample count `None`;
   - accepted.

3. Empty observations with positive count are rejected.

4. Empty observations with non-null interaction ATR are rejected.

5. Empty observations with non-null method are rejected.

6. Empty observations with non-null sample count are rejected.

7. Partial contradictory interaction diagnostics are rejected.

All existing 158 tests must continue to pass after correcting the inaccurate compatibility fixture.

---

## Blast Radius

Expected production change:

```text
src/libs/models/trendline_family/contracts.py
```

Expected test change:

```text
tests/models/trendline_family/test_interaction_contracts.py
```

No runtime classification, tracker, feature, config or API change is required.

---

## Codex Remediation Prompt

```text
Apply the final Phase-D remediation only using:

- plans/trendline-family-phase-d-rereview.md
- plans/trendline-family-phase-d-review.md
- plans/trendline-family-phase-c-approval.md
- plans/trendline-family-model-architecture-plan.md

Do not start Phase E.

Fix TrendlineFamilySnapshot no-observation interaction diagnostics:

1. Preserve real Phase-C compatibility when observations are absent and
   all interaction diagnostic keys are absent.

2. When any interaction diagnostic key is present and observations are
   empty, require exactly:
   - interaction_observation_count == 0
   - interaction_atr is None
   - interaction_atr_method is None
   - interaction_atr_sample_count is None

3. Reject positive counts, non-null ATR metadata and partial
   contradictory combinations without observations.

4. Correct the current Phase-C compatibility test. Do not create a fake
   Phase-C payload by deleting only observations from a Phase-D snapshot
   while retaining positive Phase-D interaction diagnostics.

5. Add all regression cases listed in the re-review.

Preserve all approved classification, zone, penetration, counter,
identity, replay and feature behavior.

Run:

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

ruff check \
  src/libs/models/trendline_family \
  tests/models/trendline_family

PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family

Reindex codebase-memory and stop for final Phase-D approval review.
```

---

## Next Handoff

Apply this narrow contract/test correction, then perform final Phase-D approval review before Phase E shadow integration.
