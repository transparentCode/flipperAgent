---
goal: Preserve exact SR lifecycle-engine behavior while extracting validation, existing-zone transitions, and candidate-to-zone construction from SREngine.step.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r4, lifecycle]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R4 — Lifecycle Engine Cohesion

## Scope Executed

Completed Package G from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Added behavior-characterization locks before extraction, including exact
  final, per-bar, snapshot, event, candidate, and checkpoint digests.
- Extracted step-input/state/config validation into `lifecycle.validation`.
- Extracted existing-zone lifecycle advancement and event construction into
  `lifecycle.transitions`.
- Extracted candidate association, capacity handling, zone construction, and
  created-event construction into `lifecycle.creation`.
- Reduced `SREngine.step()` to deterministic ordered orchestration:
  validation, existing-zone transitions, causal candidate detection and
  sorting, candidate-to-zone handling, state construction, then snapshot
  construction.
- Retained `detect_confirmed_pivots` imported from `lifecycle.engine` to
  preserve the established engine-level test patch seam.

Implementation commits:

- `06f9b68` — `test(sr): lock lifecycle engine behavior`
- `07a7404` — `refactor(sr): extract lifecycle validation and transitions`
- `2ff317f` — `refactor(sr): extract lifecycle candidate creation`

## Changes Made

- `validate_step_inputs()` preserves the prior validation and exception order:
  exact previous-state type, exact closed-bar type, bar closure, exact
  resolved-config type, state-key equality, resolved-config hash equality,
  configured recent-bar capacity, zone ownership, and per-zone chronology and
  configuration validity.
- `advance_existing_zones()` preserves stored-zone iteration order, terminal
  retention, availability handling, lifecycle transition behavior, and
  lifecycle event ordering.
- `create_candidate_zones()` preserves candidate order; original
  non-terminal association visibility; the growing same-batch association
  pool; association suppression; post-transition capacity accounting; no
  eviction; candidate-to-definition arithmetic; and `CREATED` event payloads
  and IDs.
- `SREngine.step()` preserves raw-event-before-created-event ordering, bounded
  recent-bar construction, aggregate state assembly, snapshot construction,
  deterministic snapshot event ordering, and returned tuple identity.
- Added exact behavior locks for no-candidate and multi-candidate bars,
  existing-zone association, same-step changed-zone association, capacity,
  pending breach confirmation, false breakout, expiry, terminal-zone
  retention, invalid input ordering, and checkpoint splits around every bar of
  the representative transition stream.

## Blast Radius Considered

- `SREngine.step()`: **CRITICAL** graph impact — replay, checkpoint, snapshot,
  evaluation, and V1.12 candidate-audit paths consume its output.
- Candidate association/construction: **CRITICAL** graph impact — matching,
  same-batch visibility, capacity, deterministic zone IDs, and event IDs are
  downstream identity inputs.

Mitigation: characterized canonical outputs before each extraction; retained
the detector patch seam; moved logic without redesign; ran lifecycle, replay,
checkpoint, association, detection, evaluation, architecture, full-SR, and
public V1.12 semantic gates after extraction.

## Validation Performed

- Initial lifecycle/replay/checkpoint focused suite: **76 passed**.
- Characterization, lifecycle-engine, replay, and checkpoint-parity suite:
  **74 passed**.
- After validation/transition extraction: **86 passed**.
- After candidate-creation extraction, including association coverage:
  **98 passed**.
- Lifecycle, replay, serialization, evaluation, association, and detection
  suite: **186 passed**.
- Architecture/import-boundary and V1.12 candidate-audit suite: **89 passed**.
- Full active SR suite: **909 passed** in **635.39 seconds**.
- Ruff over active SR and SR tests: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- Public V1.12 semantic validation passed through the historical CLI using
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

- No detection, association, rules, lifecycle thresholds, configuration,
  state/snapshot/event contract, serialization, replay, checkpoint,
  evaluation, artifact, or research-study behavior change.
- No changes to existing zone/candidate order, floating-point operation order,
  IDs, payloads, capacity policy, terminal behavior, source data, or frozen
  evidence.
- No provider/network/database call, source refresh, holdout access, evidence
  regeneration, viewer change, V2 work, merge, or legacy `libs.sr` change.

## Risks or Follow-up Items

- Package review must independently recompute the locked state, snapshot,
  event, candidate, checkpoint, created-zone, and terminal-status outputs;
  verify exception ordering and same-batch matching/capacity behavior; and
  confirm the extracted modules contain no redesign.
- Package H/R5 has not started. Do not begin it, merge, access provider or
  holdout data, or regenerate evidence during this review.
