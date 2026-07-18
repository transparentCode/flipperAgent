---
goal: Preserve all SR domain and evaluation contracts while moving each cohesive contract group to canonical ownership modules and retaining exact public facades.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r4, contracts]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R4 — Domain and Evaluation Contract Cohesion

## Scope Executed

Completed Package F from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Established `domain.errors.ContractValidationError` as canonical owner.
  `domain.identity.ContractValidationError` and
  `domain.contracts.ContractValidationError` remain exact re-exports.
- Split immutable domain contracts into cohesive canonical modules:
  - `domain.bars`: `SRStateKey`, `ClosedBar`;
  - `domain.geometry`: `ZoneGeometry`;
  - `domain.candidates`: `CandidateLevel`;
  - `domain.zones`: sides, statuses, definitions, runtime, records;
  - `domain.events`: event type and event;
  - `domain.state`: schema version and aggregate state;
  - `domain.snapshots`: immutable snapshot.
- Added private `domain._validation` only for shared primitive validation.
- Retained `domain.contracts` as export-only compatibility facade with its
  existing public `__all__` and exact class/function identity.
- Split evaluation trace ownership into:
  - `evaluation.observations`: schema version, render kind, snapshot
    reference, observed event, and zone observation;
  - `evaluation.traces`: `SREvaluationTrace` aggregate contract;
  - `evaluation._validation`: private shared primitive validation.
- Retained `evaluation.contracts` as export-only compatibility facade.
- Updated active SR imports away from both contract facades to canonical
  package exports or direct core owners. Architecture tests now forbid new
  active imports of either facade.

Implementation commits:

- `fb5378d` — `refactor(sr): split domain contract ownership`
- `dff318a` — `refactor(sr): split evaluation contract ownership`
- `f6f5578` — `test(sr): lock core contract compatibility`

## Changes Made

- Added identity, constructor-signature, field-order, enum-order, and
  immutability compatibility coverage for every moved public domain and
  evaluation contract type.
- Preserved all constructor signatures, dataclass field order, `init=False`
  identity fields, frozen status, validation messages, enum values/order,
  canonical JSON ordering, deterministic hashes, snapshot/event ordering, and
  serialization formats.
- Retained public package exports from `domain`, `evaluation`, and historical
  `contracts` modules.
- Preserved existing top-level import-cycle baseline; Package F adds no cycle
  and adds no core-to-research dependency.

## Blast Radius Considered

- `ZoneDefinition`: **CRITICAL** graph impact — direct consumers span
  lifecycle, serialization, association, replay, evaluation, and studies.
- `SRState`: **CRITICAL** graph impact — direct lifecycle engine, replay, and
  state-codec consumers.
- `SREvaluationTrace`: **MEDIUM** graph impact — direct trace builder,
  diagnostics, viewer payload, replay, and study consumers.

Mitigation: leaf contracts moved first, old module names are exact re-exports,
active code moved only after facade identity tests passed, and full replay,
serialization, evaluation, architecture, and active-SR regression suites ran.

## Validation Performed

- Domain/detection/association/lifecycle/replay/serialization focused suite:
  **230 passed**.
- Domain/evaluation/replay/serialization focused suite: **190 passed**.
- Architecture/import-boundary suite: **28 passed**.
- Final export-compatibility and architecture suite: **68 passed**.
- Full active SR suite: **895 passed** in **687.60 seconds**.
- Ruff over active SR and SR tests: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- Public V1.12 semantic validation passed through historical CLI using frozen
  original implementation binding `2412fbb5a26b4429ecd99025e0edb028d8cb46c4`:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Frozen SHA-256 identities remain exact:
  - `configs/sr.yaml`:
    `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`;
  - V1.12 YAML:
    `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`;
  - manifest:
    `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`;
  - audit:
    `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

## Not Changed

- No lifecycle behavior extraction or `SREngine.step()` rewrite.
- No configuration values, schemas, input resolution, candidate/detection,
  association, lifecycle, replay, checkpoint, metric, disposition, artifact,
  or serialization behavior changes.
- No study migration, provider/network/database call, source refresh, holdout
  access, evidence regeneration, viewer change, V2 work, merge, or legacy
  `libs.sr` change.

## Risks or Follow-up Items

- Package G lifecycle-engine cohesion has **not** started.
- Review must verify facades remain logic-free, all old/new public symbols are
  exact objects, no canonical state/event/snapshot/replay digest changed, no
  core import cycle was added, and V1.12 evidence remains byte-identical.
- Do not start Package G, merge, access provider or holdout data, or regenerate
  evidence during this review.
