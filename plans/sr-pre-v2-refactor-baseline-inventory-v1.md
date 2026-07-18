---
goal: Lock SR pre-V2 refactor baseline and record architecture inventory before code movement
stage: coder-baseline-inventory
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Codex Quant Coder
status: Complete
tags: [quant, sr, pre-v2, refactor, baseline, inventory]
source_plan: plans/architect-to-coder-sr-pre-v2-modular-refactor-v1.md
---

# SR Pre-V2 Modular Refactor — R0 Baseline Inventory

## Authority and Working Tree

- Exact base: `2ae7e0812a937c63663d528d7fe2465319818123` (`main`).
- Branch: `refactor/sr-pre-v2-modularization`.
- Authorization commit: `df959627a2f93723d75d29fd5635f93fe6b584c8`.
- Working tree was clean immediately after authorization commit.
- R0 modifies no implementation, test, configuration, artifact, provider, or
  legacy SR file. This inventory is R0's only deliverable.

## Baseline Validation Lock

| Check | Command/result |
|---|---|
| Active SR suite | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr` — **628 passed** in 639.43s |
| V1.12 focused suite | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/scripts/candidate_reinforcement_audit` — **49 passed** in 0.26s |
| V1.12 semantic validation | Historical CLI command passed against approved bundle, bound to `2412fbb5a26b4429ecd99025e0edb028d8cb46c4` |
| Graph inventory | `codebase-memory` re-indexed in moderate mode before discovery; its configured exclusion omits `src/libs/models/sr/scripts`, so direct AST/text scans cover research scripts |
| Diff baseline | `git diff --check` passed before R0 documentation |

Semantic validator result:

```json
{
  "audit_id": "cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb",
  "bundle_id": "fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206",
  "disposition": "INSUFFICIENT_REINFORCEMENT_EVIDENCE"
}
```

## Frozen Inputs and Evidence

| Item | SHA-256 | Bytes |
|---|---|---:|
| `configs/sr.yaml` | `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119` | 367 |
| `configs/sr_inputs.yaml` | `97804c20c5eebb4cf6a41d135b6ad51a249dfafbff0440d494a93906fdef468e` | 111 |
| V1.12 trial YAML | `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665` | 4,637 |
| V1.12 `manifest.json` | `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6` | 11,670 |
| V1.12 `audit.json` | `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32` | 104,978 |

- Bundle: `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`.
- Audit: `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`.
- Bound implementation: `2412fbb5a26b4429ecd99025e0edb028d8cb46c4`.
- Accounting: 65 candidates; 50 created zones; 15 eligible matches; 13 unique reinforced zones.
- State digest: `8333187c131b93fc70aba102209d336ac4885afbaa92224d75a7d64e275443e4`.
- Snapshot digest: `2b2465848b0816d0e120cc8e21fc0fdb12524cebbc55d54f8bfc0a79ce91ebe2`.
- Event digest: `028c9cf94ff80357ddbedbd86e8289b04af844454fd630463abc145931773d25`.
- Candidate digest: `1d50f701c0cb4acafc2110269bbe327bf386795cbef985331c23dc5414383ea4`.

## Active Package and Public Surface

Canonical active package is `libs.models.sr`. Root public exports are:

`AssociationConfig`, `CandidateLevel`, `ClosedBar`, `ContractValidationError`,
`DetectionConfig`, `LifecycleConfig`, `ResolvedSRConfig`, `RuntimeConfig`,
`SREngine`, `SRConfig`, `SRConfigResolver`, `SREvent`, `SREventType`,
`SRState`, `SRStateKey`, `SRSnapshot`, `ZoneDefinition`, `ZoneGeometry`,
`ZoneRecord`, `ZoneRuntimeState`, `ZoneSide`, `ZoneStatus`, `canonical_json`,
`create_initial_state`, `deterministic_hash`, `hash_candidate_level`,
`hash_event`, `hash_snapshot`, `hash_zone_definition`, and `require_utc`.

Observed core ownership at baseline:

| Area | Current owner | Refactor concern |
|---|---|---|
| Config | `config/models.py` (632 lines), `config/resolver.py` | Typed sections, schema, resolution, and resolved identity cohabit current modules |
| Domain | `domain/contracts.py` (711 lines) | Bars, geometry, candidates, zones, events, state, snapshots remain co-located |
| Lifecycle | `lifecycle/engine.py` | `SREngine.step` orchestrates validation, transitions, detection, association, and creation |
| Evaluation | `evaluation/contracts.py` (683 lines), `evaluation/diagnostics.py` (651 lines) | Contract and diagnostic ownership require cohesion split |
| Replay/serialization | `replay/`, `serialization/` | Stable behavior boundary; retain public APIs |
| Research | eight packages under `scripts/` | Direct sibling imports and duplicated infrastructure |

`SREngine.step` and `SRConfigResolver.resolve` have high immediate graph impact:
replay, V1.12 audit, CLI, viewer, and focused tests call them. This is within
approved R1/R4 scope, but requires compatibility-first moves and digest checks.

## Import Inventory

### Legacy `libs.sr`

No active source import of `libs.sr` exists under `src/libs/models/sr`.
Only two V1.11/V1.12 boundary tests contain `"libs.sr"` as denylist data.
No source import of `libs.models.sr` exists outside the canonical package;
current external consumers are SR tests.

### Production sibling-study imports

AST scan found **37 distinct sibling-study edges** from **24 importing modules**
across eight studies:

| Importing study | Sibling studies imported |
|---|---|
| `atr_calibration` | `baseline_trial` |
| `cohort_readiness` | `atr_calibration`, `baseline_trial` |
| `geometry_sensitivity` | `baseline_trial`, `cohort_readiness` |
| `baseline_adequacy` | `atr_calibration`, `baseline_trial`, `cohort_readiness`, `geometry_sensitivity` |
| `context_audit` | `atr_calibration`, `baseline_adequacy`, `baseline_trial`, `cohort_readiness` |
| `lifecycle_utility` | `baseline_trial`, `cohort_readiness`, `context_audit` |
| `candidate_reinforcement_audit` | `baseline_adequacy`, `baseline_trial`, `lifecycle_utility` |

`baseline_trial` is source-only at baseline. R3 moves shared concepts first,
then retains historical `scripts/<study>` imports as facades.

## Repeated Research Infrastructure

| Concern | Duplicate implementations | Canonical R2 target |
|---|---:|---|
| Atomic publication | 8 `_atomic_publish` functions | `research/artifacts/publisher.py` |
| Canonical bytes | 9 `_bytes` functions | `research/artifacts/canonical_json.py` |
| Duplicate JSON keys | 9 `_reject_duplicate_keys` functions | `research/config/strict_yaml.py` plus artifact JSON loader ownership |
| JSON loader | 7 `load_json` functions | `research/artifacts/validator.py` |
| Member identity | 6 `_member` functions | `research/artifacts/manifest.py` |
| Manifest validation | 6 `_validate_manifest` functions | `research/artifacts/manifest.py` / `validator.py` |
| Repository provenance | 7 `repository_commit` functions | `research/provenance/repository.py` |
| Source/fold/candidate/first-touch contracts | Sibling imports, not duplicate definitions only | `research/source`, `research/windows`, `research/replay`, `research/metrics` |

V1.12's `lstat` path-component checks and regular-member checks are frozen
behavior. R2 must extract them without changing valid bundle bytes.

## Files Above 500 Lines

| Lines | File |
|---:|---|
| 1,167 | `tests/models/sr/lifecycle/test_engine.py` |
| 1,075 | `src/libs/models/sr/scripts/baseline_adequacy/contracts.py` |
| 819 | `tests/models/sr/domain/test_contracts.py` |
| 816 | `src/libs/models/sr/scripts/atr_calibration/artifacts.py` |
| 759 | `src/libs/models/sr/scripts/cohort_readiness/contracts.py` |
| 711 | `src/libs/models/sr/domain/contracts.py` |
| 691 | `src/libs/models/sr/scripts/baseline_trial/contracts.py` |
| 683 | `src/libs/models/sr/evaluation/contracts.py` |
| 679 | `src/libs/models/sr/scripts/candidate_reinforcement_audit/contracts.py` |
| 651 | `src/libs/models/sr/scripts/lifecycle_utility/contracts.py` |
| 651 | `src/libs/models/sr/evaluation/diagnostics.py` |
| 632 | `src/libs/models/sr/config/models.py` |
| 578 | `src/libs/models/sr/scripts/baseline_trial/artifacts.py` |
| 557 | `src/libs/models/sr/scripts/context_audit/contracts.py` |
| 543 | `src/libs/models/sr/scripts/candidate_reinforcement_audit/config.py` |
| 513 | `src/libs/models/sr/scripts/candidate_reinforcement_audit/audit.py` |

No R0 split is authorized. R1–R4 must explain ownership before touching each
production file above 500 lines.

## Model and Protocol Literal Inventory

AST inventory found **251 selected operational constants** in historical study
modules. These are inputs, frozen identities, windows, gates, or thresholds;
they are not authority for future behavior. R3 must read typed trial YAML and
shared identity contracts instead, without changing historical YAML bytes.

| File | Count | Operational categories to migrate |
|---|---:|---|
| `atr_calibration/config.py` | 17 | source/holdout boundaries, source identity, folds, selection gates |
| `baseline_adequacy/contracts.py` | 30 | venue/asset/timeframe, source/ATR identity, outcomes, control count, gates, folds |
| `baseline_trial/contracts.py` | 7 | asset/timeframe/venue/window and ATR identity |
| `candidate_reinforcement_audit/config.py` | 58 | upstream bundles/hashes/bytes, source identity, eight SR parameters, ATR, folds, readiness gates |
| `cohort_readiness/contracts.py` | 16 | assets, source identity, ATR/input identity |
| `context_audit/config.py` | 48 | source, ATR, eight SR parameters, outcomes, folds, upstream identities |
| `context_audit/contracts.py` | 3 | case/comparison population and folds |
| `geometry_sensitivity/config.py` | 19 | candidate grid, baseline geometry, source/input identity, outcomes, selection thresholds |
| `lifecycle_utility/config.py` | 51 | upstream bundle identity, source/ATR identity, outcomes, folds, readiness/quality gates |
| `atr_calibration/contracts.py` | 2 | ATR implementation/contract identity |

Code-owned candidates retained only after R1–R3 review: enum member sets,
schema versions, canonical serialization/hash rules, deterministic ordering,
finite/type rules, and explicit path-safety invariants. `DAY_MS`, fixed
window policy, source selections, sample thresholds, and all `APPROVED_*`,
`EXPECTED_*`, `FROZEN_*`, `SOURCE_*`, `V10_*`, `V11_*`, `V17_*`, `V18_*`,
and `V19_*` values require typed-configuration or frozen-identity ownership.

## R1 Entry Conditions

- Preserve root/package public imports through explicit facades.
- Keep `configs/sr.yaml`, `configs/sr_inputs.yaml`, and all historical trial
  YAML files byte-identical.
- First code change: additive four-layer SR resolver and config ownership split.
- Before each existing-symbol edit, use fresh graph caller/callee impact.
- No provider, source refresh, holdout, artifact publication, V2 model work,
  tuning, legacy `src/libs/sr` modification, or broad formatting.

## R0 Disposition

Baseline is valid. No fail-closed condition triggered. Proceed to R1 only on
this branch, with behavior-preserving tests and V1.12 semantic validation after
each logical commit.
