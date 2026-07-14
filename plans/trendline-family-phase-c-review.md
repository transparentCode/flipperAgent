# Trendline Family Model — Phase C Review

## Current Mode

Quant review.

## Decision

**Revision required. Phase D is blocked.**

Phase C is directionally strong: candidate matching is causal and ATR-normalized, family/member identity is preserved on continuation, lifecycle transitions are immutable and repository-backed, provider errors fail before persistence, replay is deterministic for identical inputs, and no later-phase interaction policy leaked into the tracker.

Five issues remain before interaction-zone work can safely consume this state.

---

## Validation Reproduced

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
94 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,668 nodes
125,932 edges
status: ready
```

---

# Findings

## P0 — Public API ignores requested asset/timeframe when a resolved config is injected

Location:

```text
src/libs/models/trendline_family/api.py:20-44
```

The API uses:

```python
resolved = config or resolver.resolve(asset=asset, timeframe=timeframe)
```

When `config` is supplied, the explicit `asset` and `timeframe` arguments are not checked against it. The tracker then uses `config.asset` and `config.timeframe`, not the API request identity.

Reproduced:

```text
API request: ETHUSDT / 4h
Injected config: BTCUSDT / 1h
Published snapshot: BTCUSDT / 1h
Repository head written under BTCUSDT / 1h
No ETHUSDT / 4h head created
```

This can silently persist state for a different market than the caller requested.

Required:

- validate non-empty API `asset` and `timeframe`;
- when `config` is provided, require exact equality with `config.asset` and `config.timeframe`;
- fail before provider execution and repository persistence;
- reject `runtime_override` when an already-resolved config is supplied, rather than silently ignoring it.

---

## P0 — Snapshot and transition IDs are not content-identifying

Locations:

```text
src/libs/models/trendline_family/tracker.py:616-684
```

Transition IDs currently omit resulting state, geometry, confidence metrics and association metrics. Snapshot IDs include only family IDs/versions and transition IDs, not full family state or diagnostics.

This allows different serialized artifacts to share the same ID.

### Default-provider reproduction

Two monotonic OHLCV frames at the same timestamp/config both produced `no_confirmed_pivots`, but had different ATR diagnostics:

```text
snapshot A normalization_atr = 2.0
snapshot B normalization_atr = 10.0

snapshot A ID == snapshot B ID
serialized snapshot A != serialized snapshot B
```

### Continuation reproduction

Two continuation updates with the same candidate ID but different exact geometry produced:

```text
same transition ID
same snapshot ID
different representative prices
different serialized snapshots
```

The public provider protocol makes this more than a theoretical UUID concern.

Required:

- derive each transition ID from its complete canonical transition payload, plus a deterministic fingerprint of the resulting family state when present;
- derive snapshot ID from the complete canonical snapshot payload excluding only `snapshot_id` itself;
- include full active/dormant family state, transitions, diagnostics, previous snapshot ID, model/config metadata, asset/timeframe and timestamp;
- preserve byte-identical IDs for byte-identical replay;
- add explicit non-collision tests for different geometry, confidence/association metrics and empty-snapshot diagnostics.

A snapshot ID must never identify two different serialized snapshots.

---

## P1 — Lifecycle config permits ambiguous equal horizons

Locations:

```text
src/libs/models/trendline_family/config.py:109-125
src/libs/models/trendline_family/tracker.py:408-469
```

Configuration currently permits:

```text
active_grace_bars == dormant_after_bars
dormant_after_bars == expire_after_bars
```

The exact Phase-C rules require distinct boundaries.

Reproduced with `active_grace_bars=3`, `dormant_after_bars=3`:

```text
bars_since_match=3 remained ACTIVE
family became DORMANT at 4
```

This violates the required `bars_since_match == dormant_after_bars -> DORMANT` boundary.

Required:

```text
active_grace_bars < dormant_after_bars < expire_after_bars
```

Also reject dormant-family reactivation when the stored family is already at or beyond the current config's expiry horizon. This matters after config changes, imported snapshots or boundary corruption.

Add equality and expiry-eligibility regression tests.

---

## P1 — Projection horizon never advances

Locations:

```text
src/libs/models/trendline_family/tracker.py:383-458
```

`LineUncertainty.projection_horizon_bars` remains zero through unmatched projection:

```text
bars_since_match:                0 -> 1 -> 2
projection_horizon_bars:         0 -> 0 -> 0
```

The locked mental model requires projected old families to carry an increasing horizon so downstream consumers can distinguish fresh geometry from stale extrapolation.

Required Phase-C semantics:

```text
birth:        projection_horizon_bars = 0
matched:      projection_horizon_bars = 0
reactivated:  projection_horizon_bars = 0
unmatched:    previous projection_horizon_bars + 1
cap demotion: preserve the draft's resulting horizon
```

Do not estimate an uncertainty width yet. Only maintain truthful projection age using the existing contract.

---

## P1 — `bars_since_touch` invents interaction recency before Phase D

Locations:

```text
src/libs/models/trendline_family/tracker.py:330-342
src/libs/models/trendline_family/tracker.py:383-396
src/libs/models/trendline_family/tracker.py:446-458
```

Phase C sets birth `bars_since_touch=0`, then increments the field on both matched and unmatched updates:

```text
BIRTH     bars_since_touch=0
CONTINUE  bars_since_touch=1
WEAKEN    bars_since_touch=2
```

No Phase-C code observed a line-price interaction or current-bar touch. This creates synthetic interaction evidence before the Phase-D event layer exists.

Required:

- keep candidate `touch_count` and `effective_touch_count` as structural candidate diagnostics;
- do not infer touch recency from family persistence or candidate matching;
- preserve `bars_since_touch` unchanged through Phase C;
- Phase-C-born families should keep the agreed neutral sentinel (`0`) until Phase D owns and updates this field;
- add tests proving continuation, abstention, dormancy and reactivation do not modify it.

---

## P2 — Churn rate is not normalized as a rate

Location:

```text
src/libs/models/trendline_family/tracker.py:700-724
```

Current formula:

```python
churn_count / max(previous_family_count, 1)
```

can exceed `1.0` on first publication or when births exceed the previous family count. Either rename it as a ratio-to-previous-count or define a bounded denominator such as:

```text
max(previous_family_count + birth_count, 1)
```

This is not independently blocking, but should be corrected while diagnostics are being touched.

---

## Verified Correct Areas

- causal confirmed-frame filtering;
- true-range mean normalization and owned config field;
- projected level and slope normalization in ATR units;
- role hard gate;
- anchor-overlap contribution;
- minimum match and dormant reactivation score gates;
- deterministic greedy one-to-one assignment;
- family/member identity retention;
- singleton family state;
- exact representative line replacement rather than averaging;
- birth-quality threshold and audit rejection;
- exact grace/decay/dormancy/expiry behavior for strictly ordered default horizons;
- normal abstentions advance lifecycle;
- provider/config errors preserve repository head;
- active-family cap produces one final transition per family;
- structural importance and current relevance remain separate;
- future-row invariance;
- repository version lineage;
- no Phase-D or later functionality.

---

# Required Codex Remediation

```text
Apply Phase-C remediation only using:

- plans/trendline-family-phase-c-review.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md
- plans/trendline-family-phase-a-approval.md
- plans/trendline-family-phase-b-approval.md

Do not start Phase D.

1. Bind public API identity.
   - Validate non-empty asset/timeframe.
   - If resolved config is injected, require exact config.asset and
     config.timeframe equality with the API request.
   - Reject runtime_override when resolved config is injected.
   - Fail before provider invocation or repository persistence.

2. Make transition and snapshot IDs content-identifying.
   - Transition ID must include the complete canonical transition
     payload and resulting family-state fingerprint when present.
   - Snapshot ID must hash the complete canonical snapshot payload
     excluding only snapshot_id.
   - Include families, transitions, diagnostics, previous ID,
     timestamp, asset/timeframe and model/config metadata.
   - Add collision regression tests.

3. Enforce strict lifecycle horizons:
     active_grace_bars < dormant_after_bars < expire_after_bars
   - Add equality rejection tests.
   - Dormant families already at/after expiry under the current config
     are not eligible for reactivation and must expire on update.

4. Maintain projection_horizon_bars truthfully.
   - birth/match/reactivation -> 0
   - unmatched -> previous + 1
   - cap demotion preserves resulting value
   - do not add calibrated uncertainty width.

5. Stop inventing touch recency.
   - Preserve bars_since_touch unchanged throughout Phase C.
   - Phase-C births use neutral 0.
   - Matching/persistence/abstention do not count as touches.

6. Normalize or rename family_churn_rate so its semantics are
   explicit and tested. Prefer a bounded [0,1] churn rate.

Preserve all already-correct Phase-A/B/C behavior.

Do not implement:
- interaction zones
- touch/breach classification
- breakout/retest/role reversal
- split/merge
- multi-rail families
- MTF
- RegimeV2 integration
- optimization

Run:

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

ruff check \
  src/libs/models/trendline_family \
  tests/models/trendline_family

PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family

Reindex codebase-memory, return the mandatory review package, and stop.
```

## Next Gate

Re-review Phase C after remediation. Phase D begins only after API identity, content-addressed audit IDs, strict lifecycle boundaries, projection age and touch-recency ownership are correct.
