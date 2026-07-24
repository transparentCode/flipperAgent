---
goal: implement exact structural tracking over canonical Phase 9D selections
stage: coder-to-orchestrator
date_created: 2026-07-23
last_updated: 2026-07-23
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendline-v2, phase-10a]
---

# Trendline V2 Phase 10A

## 1. Status

`READY_FOR_ORCHESTRATOR_REVIEW`

Implemented on branch:

```text
feature/trendline-v2-phase-10a-tracking-foundation-v1
```

Base and current HEAD are unchanged:

```text
722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f
```

No commit was created. No merge, push, provider execution, network request,
YAML change, viewer change, storage, Regime, interaction, event, MTF or
lifecycle implementation was added.

## 2. Changed files

Exactly eleven files are in scope:

```text
src/libs/models/trendline_v2/tracking/__init__.py
src/libs/models/trendline_v2/tracking/contracts.py
src/libs/models/trendline_v2/tracking/exact_lineage.py
src/libs/models/trendline_v2/api.py
src/libs/models/trendline_v2/__init__.py
tests/models/trendline_v2/test_tracking_contracts.py
tests/models/trendline_v2/test_tracking.py
tests/models/trendline_v2/test_api.py
scripts/validate_trendline_v2_tracking_foundation.py
tests/scripts/test_trendline_v2_tracking_foundation.py
plans/coder-to-orchestrator-trendline-v2-phase-10a-tracking-foundation-v1.md
```

No generated `/tmp` evidence entered Git.

## 3. Tracking policy

Policy identity namespace:

```text
trendline_v2_tracking_policy
```

Exact policy payload:

```json
{
  "policy_name": "exact_selected_structure_lineage",
  "policy_version": "v1",
  "supported_selection_policy_identity": "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc",
  "family_identity_fields": [
    "asset", "timeframe", "role", "geometry", "anchors", "evidence",
    "provider_identity", "discovery_config_identity",
    "selection_policy_identity", "tracking_policy_identity"
  ],
  "continuation_rule": "exact_family_id_match",
  "valid_source_absence_rule": "source_removed",
  "source_unavailable_rule": "carry_forward_without_observation",
  "removed_reappearance_rule": "reject",
  "observation_time_rule": "strictly_increasing"
}
```

Required identity:

```text
82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce
```

`ExactSelectedStructureTrackingPolicy` is frozen, slotted, strict and has no
alternate policy values.

## 4. Family identity

Namespace:

```text
trendline_v2_tracked_family
```

`tracked_family_id()` hashes exactly:

```python
{
    "asset": candidate.asset,
    "timeframe": candidate.timeframe,
    "role": candidate.role.value,
    "geometry": candidate.geometry.to_dict(),
    "anchors": [anchor.to_dict() for anchor in candidate.anchors],
    "evidence": candidate.evidence.to_dict(),
    "provider_identity": provider_identity,
    "discovery_config_identity": discovery_config_identity,
    "selection_policy_identity": selection_policy_identity,
    "tracking_policy_identity": tracking_policy_identity,
}
```

The hash excludes `candidate_id`, `candidate.observed_at`, the source
selection snapshot ID, Phase 9B `candidate_structure_id`, future outcomes and
all interaction state. Exact anchor IDs are required to be canonical hashes.
Provider/config/policy inputs are canonical hashes; `TrackedTrendlineFamily`
also verifies that its candidate provider identity matches the stored provider
identity.

## 5. Runtime contracts

`TrackingStatus` has only `updated` and `source_unavailable`.

`FamilyTrackingTransitionType` has only `birth`, `continue` and
`source_removed`. `source_removed` means absence from a newer valid selected
source only; it does not claim invalidation, breakout, expiry, weakness,
dormancy or role reversal.

`TrackedTrendlineFamily` is frozen and binds:

```text
family_id, version, first_seen_at, last_seen_at, observation_count,
current_candidate, current_selection_snapshot_id,
provider_identity, discovery_config_identity, selection_policy_identity,
tracking_policy_identity
```

It enforces canonical family ID, exactly two anchors, version equals
observation count, and `last_seen_at == current_candidate.observed_at`.

`FamilyTrackingTransition` is content-addressed under
`trendline_v2_family_tracking_transition` and enforces exact birth,
continuation and source-removed field combinations. Its timestamp and policy
are bound by the enclosing tracking snapshot.

`TrackingDiagnostics` contains only nonnegative integer accounting fields:

```text
previous_active_count
source_selected_candidate_count
current_active_count
birth_count
continuation_count
source_removed_count
carried_forward_count
cumulative_removed_count
```

`TrendlineTrackingSnapshot` is frozen, content-addressed under
`trendline_v2_tracking_snapshot`, canonically orders active families,
removed IDs and transitions, rejects duplicates/overlap, validates all
transition/current-family links and enforces status-specific arithmetic.

## 6. Update semantics and API

`track_selected_trendlines(selection, previous=..., policy=...)` is pure:

- validates exact selection, previous snapshot and policy types;
- rejects asset, timeframe, input, provider, discovery-config, selection-policy,
  tracking-policy and observation-time drift;
- uses `selection.snapshot_id` as the source selection snapshot identity;
- creates version-one births for new exact family IDs;
- continues exact family IDs with version and observation count incremented by one;
- removes absent active families from active state and records `source_removed`;
- rejects reappearance of cumulative removed family IDs with
  `unsupported_removed_family_reappearance`;
- carries active family objects and removed IDs byte-for-byte through source
  abstention/failure, with no transitions or version changes.

The public API added only:

```python
track_trendline_families(
    selection,
    *,
    previous,
    policy,
) -> TrendlineTrackingSnapshot
```

`previous` and `policy` are mandatory keyword arguments. Discovery and
selection APIs remain unchanged. Root exports now include exactly:

```text
ExactSelectedStructureTrackingPolicy
TrackedTrendlineFamily
TrendlineTrackingSnapshot
track_trendline_families
```

Runtime tracking imports only selection/domain code. No provider, configuration
loader, script, viewer, old Trendline Family, storage, interaction, or Regime
dependency exists in the tracking package.

## 7. Phase 9D source binding

The committed Phase 9D verifier was invoked before selection deserialization.
No Phase 9D source bytes were modified.

```text
Phase 9D commit:              722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f
Phase 9D decision ID:         c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd
Phase 9D manifest ID:         51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585
Phase 9D output inventory:    aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8
Phase 9C.2 inventory:         ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
Selection policy identity:    3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc
Tracking policy identity:     82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce
```

Selection snapshot IDs and initial tracking snapshot IDs:

| Dataset | Selection snapshot ID | Tracking snapshot ID | Families | Births |
| --- | --- | --- | ---: | ---: |
| btcusdt_1h | ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab | 3b6508ddce3495af3d7eeefc2c467007abe54a50c723e9a8bd4c312e7721b26b | 422 | 422 |
| btcusdt_4h | 31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da | 8412309f155294e819b5243e3ee1af276d1bcf5c0ca971aaed97558965bbb2b9 | 106 | 106 |
| ethusdt_1h | 7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b | 584b6b2c032f65176f8a993ffa50ab41b62509ada163ab9fd5de119c6848cfb5 | 433 | 433 |
| ethusdt_4h | f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56 | c7f342c906ae1d551b0e2d982f2db88a807fa2ac885b76b66d733a20dd62f919 | 109 | 109 |
| suiusdt_1h | d2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db | 6fbbedaf9345c1b50d7419d5ed297c472ee3330110309f86c82cd636e6e34fca | 437 | 437 |
| suiusdt_4h | c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b | 4d80da14de530fd51e49d01e88bbce11b929156616e6bf9e0d9e00e2cf5092e4 | 112 | 112 |

Totals: `1,619` selected source candidates, `1,619` active families,
`1,619` births, zero continuations and zero source removals.

## 8. Evidence bundle

Published only outside Git:

```text
/tmp/trendline_v2_phase10a_tracking_foundation/20260522_20260701/
```

Decision and manifest:

```text
Decision ID:       44fe6f1c0c86563416f023c1c7530be61f30b0755ccf5335fbe0a4086df9ff0f
Manifest ID:       064a641c797c655d2726a4d332168cd3740159790dff1129047ca8bd12979d6a
Output inventory:  bc560cda8f4cd478313b8e4fb84338dc332679940ba6a56fde7b50dc97415080
Status:            TRACKING_FOUNDATION_INITIAL_BIRTHS_VERIFIED
```

Output inventory:

```text
birth_summary.csv                                      1164  52dcb2431fa4d88613be20050cfb76b8d63dcb38311a956d440b3ef43f335b69
datasets/btcusdt_1h/tracking_snapshot.json            902807 d438b2c076a6735436bdc1370e82045a9ea6d22050d532959447c7b209a4f4c3
datasets/btcusdt_4h/tracking_snapshot.json            227817 625d1bdb5895b2b53365279ca65a50f9050f184d18821b1fbb9a6e32a9734fd2
datasets/ethusdt_1h/tracking_snapshot.json            925937 31fc29a3ea616333a6710b539febd5d8d29e445725fc8722628c546187cdfbd7
datasets/ethusdt_4h/tracking_snapshot.json            234100 d54730a0ce1bae84bf2a83376c0bdfeaa90eb0c6bd9319bcc4e7e075b9564417
datasets/suiusdt_1h/tracking_snapshot.json            932913 555695c0ecee12fb943b9062a7ec9a91c288e3652c893aa937dfbf7cd353df02
datasets/suiusdt_4h/tracking_snapshot.json            240136 e74f1c452a6eab899c7939c89c090f265f2cea4b9083a3eb8f5c022662a067f2
decision.json                                           3786 4a8c1a27c1e53f31a705a18186809e3657a89403dd0406e9cbf73796ebc82514
manifest.json                                           1863 57ad12058568de109f0667f98093563d031c5858a998441425077b1d5f3ecede
source_audit.json                                       4667 66bdef519b91dd51ef042ad13149044ee8cf9360166d8647614398e758a55120
study_contract.json                                     1889 7d5299de270d8f44e20462e02492d9c8b35563b1eca9b3b195b00413f80fe5ec
```

The Phase 9D source inventory was byte-identical before and after verifier,
snapshot loading and tracking execution. Its full inventory hash is the fixed
`aca26bb...` value above.

## 9. Execution accounting

```text
Source selection snapshot loads: 6
Tracking update executions:      6 (study path; verifier is read-only rederivation)
Selected source candidates:      1,619
Active tracked families:        1,619
Birth transitions:              1,619
Continuation transitions:          0
Source-removed transitions:        0
Historical provider executions:     6 (upstream Phase 9D evidence only)
Phase 10A provider executions:      0
Network requests:                  0
```

## 10. Validation

```text
Focused tracking/API/script tests: 66 passed, 1 skipped (normal)
External evidence script:            7 passed
Trendline V2 + viewer:             202 passed
Protected Trendline Family:        400 passed
Provider benchmark:                  4 passed
Frontend npm test:                  13 passed
npm audit:                            0 vulnerabilities
Ruff:                                 passed
compileall:                           passed
git diff --check:                     passed
```

The external evidence test was run with
`TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1` and checks exact source selection
IDs, tracking snapshot IDs, per-dataset counts, decision ID, manifest ID and
output inventory.

Codebase-memory reindex completed once with non-zero indexes:

```text
flipperAgent-src:       22,716 nodes / 118,048 edges
flipperAgent-tests:      5,520 nodes / 23,182 edges
flipperAgent-scripts:    1,288 nodes /  5,687 edges
flipperAgent-plans:      5,245 nodes /  5,231 edges
flipperAgent-docs:         433 nodes /    431 edges
flipperAgent-conductor:    196 nodes /    981 edges
```

GitNexus completed on the current branch and records HEAD
`722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f` with `48,844` nodes and `80,984`
edges. The worktree remains uncommitted by authorization.

## 11. Explicit limitations and unauthorized boundaries

This evidence bundle validates only initial births from one frozen selected
snapshot per dataset. Continuation, source removal, source-unavailable
carry-forward and removed-family reappearance are hermetically tested but not
measured through real multi-snapshot market replay.

Not implemented or authorized in this phase:

```text
Phase 10B causal temporal replay
approximate geometry/ATR/score matching
confidence, dormancy, reactivation, market invalidation, expiry
ranking, capacity, interactions, events, role reversal, MTF
viewer migration, storage/repository, Regime integration
provider/network/YAML changes, merge, push, commit
```

## 12. Review request

Review the exact eleven-file diff, runtime dependency boundary, immutable
contract invariants, source/output hashes, and validation evidence above.
Commit is not authorized by the Phase 10A handoff.

`READY_FOR_ORCHESTRATOR_REVIEW`
