---
goal: Remediate D7A SR adapter artifact boundedness without changing SR core semantics or starting D7B/D8
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d7a, sr, adapter, boundedness, remediation]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — D7A SR adapter artifact boundedness remediation

## Objective

D7A is functionally close and the real SR adapter parity/state/rewarm surfaces are green. Independent review found one D7A contract violation: `ModelArtifact.value["zones"]` currently projects every `SRSnapshot.zones` record, but SR intentionally retains terminal zones indefinitely. The artifact therefore grows monotonically over long-running lanes even though `runtime.max_active_zones` bounds only non-terminal zones.

Continue only in the existing cumulative decision worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not commit, merge, push, switch branches, reset, restore, start D7B, or start D8.

Do not modify SR lifecycle/state retention semantics to solve an adapter projection problem.

## Independent evidence

The approved D7A handoff explicitly requires:

```text
zones: tuple of bounded semantic mappings
Keep the projection useful but bounded.
```

Current adapter:

```python
"zones": tuple(_zone_evidence(record) for record in snapshot.zones)
```

Current SR core:

- `runtime.max_active_zones` bounds non-terminal zones only;
- `advance_existing_zones()` retains terminal `BROKEN`/`EXPIRED` records;
- later candidate creation continues while active count is below the configured limit;
- therefore total `SRState.zones` / `SRSnapshot.zones` may grow over model lifetime.

Direct adversarial execution with the D7 fixture config:

```text
runtime.max_active_zones = 8

bar 120:
  snapshot zone_count     = 12
  artifact zones payload  = 12

bar 1000:
  snapshot zone_count     = 96
  artifact zones payload  = 96

max current-step event payload observed = 3
```

This is an adapter/resource-boundary issue, not an SR quantitative parity failure.

## Required fix

Keep canonical SR aggregate state unchanged and keep `snapshot_id` tied to the complete authoritative `SRSnapshot`.

Change only the adapter's projected zone evidence so the `ModelArtifact` is deterministically bounded.

Preferred semantic projection:

```text
artifact.value:
  snapshot_id
  config_hash
  as_of
  zone_count              # total canonical snapshot zone count, scalar only
  active_zone_count       # total non-terminal zones
  terminal_zone_count     # total terminal zones
  projected_zone_count    # len(zones)
  event_count
  zones                    # bounded non-terminal/current analytical zones only
  events                   # current-step events; already naturally bounded by the SR step
```

For `zones`, project the canonical non-terminal zones from `snapshot.zones` in their existing deterministic order.

The projected tuple must satisfy:

```text
len(zones) <= resolved_config.runtime.max_active_zones
```

Do not include all historical terminal zones merely to preserve exact aggregate state in the artifact. Exact aggregate state already exists in:

```text
proposed_next_state = encode_state(next_state)
```

and canonical snapshot identity remains available through `snapshot_id`.

If a bounded terminal-zone sample is judged necessary, it must have an explicit fixed deterministic limit and a documented semantic reason. Prefer the simpler non-terminal-only projection unless existing consumers/tests demonstrate a need for terminal history.

Do not introduce pagination, artifact stores, cache frameworks, truncation services, or generic model-output projection abstractions.

## Counts and semantics

Do not redefine `snapshot_id`.
Do not alter `SRSnapshot`.
Do not alter `SRState` retention.
Do not alter lifecycle event semantics.
Do not alter `SREngine.step()`.
Do not alter the SR state codec.

`zone_count` should continue to describe the authoritative snapshot total so parity/debugging remains possible even when the artifact projects only active zones.

Add explicit counts so consumers cannot confuse projected count with total count.

## Tests

Extend `tests/decision/test_real_sr_plugin.py` with focused adversarial coverage.

At minimum prove:

1. normal direct `SREngine.step()` vs plugin state/snapshot parity remains unchanged;
2. artifact `snapshot_id` still equals the authoritative direct snapshot ID;
3. artifact total `zone_count` equals `len(snapshot.zones)`;
4. `active_zone_count + terminal_zone_count == zone_count`;
5. `projected_zone_count == len(artifact.value["zones"])`;
6. every projected zone is non-terminal/current analytical context;
7. `projected_zone_count <= runtime.max_active_zones` for every step;
8. long-horizon sequence (large enough to accumulate terminal zones) proves total `zone_count` can exceed max-active while projected zones remain bounded;
9. event evidence remains current-step only and deterministic;
10. encoded proposed state remains byte-identical to direct SR core state for the parity fixture.

The long-horizon regression should be deterministic and lightweight. Do not add research artifacts or live data.

## Existing verified surfaces to preserve

Independent review before this remediation verified:

```text
focused D6/D7 adapter surface      35 passed
tests/decision                     180 passed
SR core/config/lifecycle/codec/
replay/adapter/import-boundary     289 passed
```

The broad `tests/models/sr` tree is not a clean D7 gate in this checkout because approved research fixtures are missing. Independent reproduction confirmed representative failures such as:

```text
approved V1.5 bundle is missing or is a symlink
approved TAOUSDT development capsule is missing
```

Do not modify research tests/core to bypass those gates.
Record them as pre-existing fixture blockers only.

## Static validation

Run after remediation:

```text
focused D7/D6 real-SR tests
all tests/decision
relevant SR core/config/domain/lifecycle/serialization/replay/adapters/import-boundary tests
D1-D6 compatibility tests
Ruff check
Ruff format --check
compileall
git diff --check
adapter/SR import-boundary scan
cache cleanup
```

No infrastructure/network/database/broker/Docker validation is required or allowed for D7A.

## Review pass 1

Verify:

```text
SR core parity unchanged
snapshot identity unchanged
encoded state unchanged
artifact zone projection bounded
counts self-consistent
active-zone selection deterministic
no terminal-history leakage into artifact growth
D6 rewarm/prepare/abort/commit still correct
```

## Review pass 2

Verify:

```text
adapter remains thin
no SR-core redesign
no generic projection framework
no legacy FeatureVector bridge
no D7B work
no D8/publication/runtime infrastructure
```

## Handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d7-representative-real-model-adapters-v1.md
```

Record:

```text
artifact projection rule
long-horizon boundedness evidence
total/active/terminal/projected count semantics
snapshot/state parity evidence
focused/cumulative test counts
broad SR fixture-blocked status
Ruff/format/compile/diff/import results
Pass 1 findings
Pass 2 findings
```

D7B remains deferred.
D8 remains unstarted.

Final line exactly:

```text
DECISION_APP_D7A_SR_REAL_ADAPTER_READY_FOR_REVIEW
```
