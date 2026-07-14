# Trendline Family Model — Phase B Approval

## Current Mode

Approval.

## Decision

**Phase B is approved. Phase C may begin.**

The native candidate stage now satisfies the approved causal, deterministic, self-owned exact-line boundary.

## Approved production surface

```text
src/libs/models/trendline_family/pivots.py
src/libs/models/trendline_family/fitting.py
src/libs/models/trendline_family/provider.py
src/libs/models/trendline_family/registry.py
```

Together with the approved Phase-A contracts/config/repository surface.

## Approval evidence

Reproduced:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
73 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
status: ready
nodes: 39,557
edges: 124,678
```

Independent adversarial checks confirmed:

- long high plateaus preserve the first confirmed pivot ID, timestamp, price, and confirmation time;
- long low plateaus preserve the first confirmed pivot identity;
- numeric-string OHLCV and equivalent float OHLCV produce identical provider status, metadata, candidates, ordering, IDs, geometry, and diagnostics;
- malformed numeric input remains an explicit provider-input error;
- timestamp-space path validation, config/request identity binding, exact-anchor diagnostics, deterministic IDs, and future-row invariance remain intact.

## Locked Phase-B semantics

- Plateau policy: `leftmost_strict_left_nonstrict_right_v1`.
- Every returned pivot is causal and non-repainting after confirmation.
- Shared confirmed OHLCV windows are normalized to finite floats before pivot/fitting use.
- Pathfinding validates and emits the same timestamp-space line geometry.
- `min_pivots_per_side` gates source evidence, not declared anchor count.
- An emitted candidate has exactly two exact anchors.
- Full dynamic-programming paths are provenance only, not unverified touches.
- Initial quality method is `anchor_span_coverage_v1`.
- Candidate generation is self-owned and imports no legacy trendline runtime.
- Candidate provider accepts only a matching `ResolvedTrendlineFamilyConfig`.

## Residual boundaries

- The runtime/feed layer remains responsible for identifying completed bars.
- The provider defensively filters to `observed_at`; it does not infer exchange close schedules.
- One candidate per role is intentional for the first provider.
- Candidate quality is structural admission evidence, not trade probability.
- No family tracking, interaction, MTF, RegimeV2, or optimization behavior is approved yet.

## Phase C architecture constraints

Phase C must consume Phase-B outputs without weakening their contracts.

For the MVP:

1. Treat each current candidate as a singleton observation. Do not introduce speculative clustering while the provider emits at most one candidate per role.
2. Keep each family single-member initially. Preserve a stable `member_id` and update that member with newly matched candidate evidence; do not append unbounded candidate history. Multi-rail members belong to Phase G.
3. Use previous active and eligible dormant family snapshots as priors.
4. Match only with exact role compatibility in this phase.
5. Normalize level and slope distance with a causal positive current ATR computed from confirmed bars. Give the matching stage its own typed ATR-window config rather than borrowing interaction-zone config.
6. Use deterministic greedy one-to-one assignment and stable tie-breakers.
7. Normal candidate abstentions advance lifecycle with an empty candidate set. Provider/config errors fail closed and must not persist a new snapshot.
8. Enforce `birth_quality_threshold`, active/dormant/expiry horizons, confidence decay, reactivation threshold, and maximum active families per role through resolved config.
9. Publish only immutable Phase-A contracts with deterministic family/member/transition/snapshot IDs.
10. Do not implement interaction zones, breakouts, role reversal, split/merge, MTF, RegimeV2 integration, or optimization.

## Next gate

Phase C requires a separate architecture/correctness review before Phase D. Review must focus on identity stability, ATR normalization, matching gates, lifecycle off-by-one behavior, replay parity, repository lineage, bounded member state, and churn diagnostics.
