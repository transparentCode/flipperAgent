# Trendline Family Model — Phase C Re-review

## Current Mode

Quant review.

## Decision

**Revision required. Phase D remains blocked.**

All five findings from `plans/trendline-family-phase-c-review.md` are correctly remediated. One additional configuration-lineage blocker was found during adversarial re-review.

---

## Validation Reproduced

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
105 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
39,700 nodes
126,145 edges
status: ready
```

---

## Verified Remediation

The following are approved:

1. Public API validates requested asset/timeframe against injected resolved config and rejects runtime overrides with resolved config.
2. Transition IDs include complete transition content plus resulting family state.
3. Snapshot IDs include complete snapshot content except `snapshot_id`.
4. Lifecycle horizons are strictly ordered.
5. Dormant families already at the expiry horizon cannot reactivate.
6. Projection horizon increments on unmatched updates and resets on candidate evidence.
7. `bars_since_touch` remains neutral throughout Phase C.
8. Churn rate is bounded by the documented denominator.
9. Existing matching, lifecycle, replay, future-row invariance and import-boundary behavior remain intact.

---

# Blocking Finding

## P0 — Config-hash changes contaminate family lineage after one update

Locations:

```text
src/libs/models/trendline_family/tracker.py
- previous snapshot loading
- `_previous_config_compatible`
- matching and snapshot publication
```

The tracker currently handles a previous snapshot with a different model/config/hash as follows:

1. `_previous_config_compatible` returns false.
2. Old families are prevented from matching during that update.
3. Those old families are still advanced and republished inside a snapshot carrying the new config identity.
4. On the next update, the repository head now matches the new config identity.
5. The old family becomes match-eligible and may consume a new-config candidate while preserving its old family ID.

### Reproduced

```text
Config A births family F_A.

First Config-B update:
- F_A remains active/unmatched
- Config-B candidate births F_B
- snapshot metadata is Config B

Second Config-B update:
- Config-B candidate matched F_A
- F_A preserved its old family ID
- F_B weakened
```

Observed output:

```text
after config switch:
F_A bars_since_match=1, member candidate=a0
F_B bars_since_match=0, member candidate=b1
matched_count=0, birth_count=1

next Config-B update:
F_A -> CONTINUE with candidate b2
F_B -> WEAKEN
```

This means the incompatibility gate lasts only one bar. It mixes families generated under different hyperparameter regimes and makes config-hash provenance misleading.

### Why this blocks Phase D

Interaction state must attach to a structurally coherent family lineage. A family ID whose candidate-generation and tracking regime silently changed cannot support reliable touch/breach history, replay analysis, or later optimization attribution.

---

## Required Phase-C Semantics

For the Phase-C MVP, use the safest behavior:

```text
repository head config identity != tracker config identity
    -> fail closed before provider execution
    -> do not save a snapshot
    -> do not alter repository head
    -> require explicit reset/new repository namespace/migration outside this update
```

Identity comparison must include:

```text
model_version
config_version
resolved_config_hash
asset
timeframe
```

Do not silently:

- carry old families into a new-config snapshot,
- expire them under new-config metadata,
- birth new-config families beside old-config families,
- relabel prior state with the new config hash.

An explicit migration/reset API can be designed later if needed. It is outside Phase C.

---

## Required Tests

Add regression tests proving:

1. A repository head created with Config A rejects an update attempted with Config B.
2. The provider is not called on this failure.
3. The repository head remains byte-identical and unchanged.
4. Model-version mismatch fails identically.
5. Config-version mismatch fails identically.
6. Asset/timeframe mismatch from a repository implementation fails closed.
7. Same-config updates continue to work unchanged.

The existing candidate-level config identity failure test must remain.

---

## Codex Remediation Prompt

```text
Apply final Phase-C remediation only using:

- plans/trendline-family-phase-c-rereview.md
- plans/trendline-family-phase-c-review.md
- plans/trendline-family-model-architecture-plan.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-phase-a-approval.md
- plans/trendline-family-phase-b-approval.md

Do not start Phase D.

Required work:

1. Add a repository-head compatibility preflight in
   TrendlineFamilyTracker.update immediately after loading the previous
   snapshot and before calling the candidate provider.

2. When a previous snapshot exists, require exact equality for:
   - asset
   - timeframe
   - model_version
   - config_version
   - resolved_config_hash

3. On mismatch:
   - raise TrendlineFamilyUpdateError with a clear config/repository
     identity message
   - do not call provider.generate
   - do not save a snapshot
   - preserve repository head exactly

4. Do not carry, expire, relabel or migrate prior families under the
   new config. Explicit reset/migration is deferred.

5. Remove or simplify the one-update-only
   `_previous_config_compatible` behavior so incompatible repository
   state can never enter normal matching/lifecycle publication.

6. Add regression tests for hash, config-version, model-version and
   repository asset/timeframe mismatches, provider non-invocation and
   unchanged repository head.

Preserve all approved behavior:

- API request/config identity validation
- content-addressed transition and snapshot IDs
- strict lifecycle horizons
- stale dormant expiry behavior
- projection_horizon_bars semantics
- neutral bars_since_touch
- bounded churn rate
- deterministic matching/replay
- future-row invariance
- no legacy imports
- no Phase-D functionality

Do not implement:

- reset or migration APIs
- interaction zones
- touch/breach events
- role reversal
- split/merge
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

Reindex and run codebase-memory scope validation.
Return the mandatory review package and stop.
```

---

## Next Gate

After this small correction, perform one final Phase-C approval review. Phase D must not begin until configuration lineage is fail-closed and immutable across repository heads.
