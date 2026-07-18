---
goal: Preserve lifecycle-utility and candidate-reinforcement-audit behavior while completing canonical study ownership and eliminating all sibling-study imports.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r3d]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R3d — Lifecycle Utility and Candidate Reinforcement Audit

## Scope Executed

Completed Package E / R3d from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Moved V1.11 reusable frozen-evidence implementation to
  `libs.models.sr.research.evidence.lifecycle_utility`.
- Added the canonical V1.11 study facade at
  `libs.models.sr.research.studies.lifecycle_utility`.
- Moved V1.12 Candidate Reinforcement Audit implementation to
  `libs.models.sr.research.studies.candidate_reinforcement_audit`.
- Retained every historical `libs.models.sr.scripts.lifecycle_utility` and
  `libs.models.sr.scripts.candidate_reinforcement_audit` module as a
  logic-free forwarding facade, including CLI `__main__` forwarding.
- Moved V1.10 frozen-evidence services to
  `research.evidence.context_audit`, so V1.11 consumes the exact V1.10
  semantic validator and frozen-context loader without importing a sibling
  study.
- Moved the pure, existing V1.10 casebook serializer to
  `research.viewer.casebook_payload`. The historical
  `tools.zone_viewer.payload.build_casebook_chart_payload` is an exact direct
  re-export; no viewer payload semantics or rendered behavior changed.
- Candidate Reinforcement Audit now consumes neutral V1.9 evidence services,
  shared input/SR resolution, and neutral V1.11 evidence services. Its V1.12
  semantic manifest, `ReplayParity`, parity-check matrix, accounting,
  publication, and path guards remain study-owned and unchanged.
- Restored historical direct V1.12 config aliases for `FrozenSource`,
  `UpstreamV11`, `UpstreamV19`, `UpstreamV10`, and the tested parser helpers.

Implementation commits:

- `08a57c3` — `refactor(sr): migrate lifecycle utility study`
- `fc72ec3` — `refactor(sr): migrate candidate audit study`

## Compatibility and Dependency Accounting

- Legacy, canonical, and neutral Context Audit frozen-evidence config,
  contract, runner, and artifact validator exports retain exact identity.
- Legacy, canonical, and neutral Lifecycle Utility config, contracts,
  extraction, runner, and artifact-validator exports retain exact identity.
- Legacy and canonical Candidate Reinforcement Audit config, contracts,
  computation, runner, artifact validator, parser, and CLI main exports retain
  exact identity where public.
- Historical V1.12 config imports continue to expose the pre-existing identity
  classes and tested parser-helper aliases.
- All eight canonical studies now exist under `research/studies/`.
- Canonical studies import neither historical `scripts` packages nor another
  canonical study.
- Logical sibling-study imports are now:
  - legacy `scripts/` edges: **0**;
  - canonical `research/studies/` edges: **0**;
  - total: **0** (**9 → 0** for Package E; **41 → 0** from the R2 baseline).

## Behavior Preservation

- Lifecycle resolution event selection, event-side mapping, ATR alignment,
  next-bar outcome windows, null-cell reuse, fold censoring, metrics, gates,
  and `LIFECYCLE_CONTEXT_NOT_SUPPORTED` semantics are unchanged.
- V1.12 candidate detection/replay, first-confirmation fold assignment,
  accounting, decision/disposition calculation, manifest schema, audit payload,
  publication, path safety, and symlink/non-regular-file guards are unchanged.
- The immutable V1.12 result remains:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`;
  - accounting: 65 candidates, 50 created zones, 15 eligible matches, and 13
    unique reinforced zones.
- No provider, network, database, source refresh, holdout access, evidence
  publication, model change, configuration-value change, or merge occurred.

## Validation Performed

- Lifecycle Utility focused suite: **47 passed**.
- Candidate Reinforcement Audit focused suite: **52 passed**.
- V1.12 config-identity/primitives plus focused audit suite: **108 passed**.
- Context Audit frozen-evidence replay suite: **32 passed**.
- Architecture plus viewer-payload compatibility suite: **29 passed**.
- Full active SR suite: **853 passed** in 675.01 seconds.
- Historical CLI help commands passed:
  - `python -m libs.models.sr.scripts.lifecycle_utility.cli --help`
  - `python -m libs.models.sr.scripts.candidate_reinforcement_audit.cli --help`
- Ruff, full SR compilation, and `git diff --check`: passed before handoff.
- Public V1.12 semantic validation passed through the historical CLI with the
  original implementation binding `2412fbb5a26b4429ecd99025e0edb028d8cb46c4`:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Frozen SHA-256 identities remain exact:
  - `configs/sr.yaml`:
    `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`;
  - V1.12 YAML:
    `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`;
  - manifest (11,670 bytes):
    `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`;
  - audit (104,978 bytes):
    `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

## Review Request

Review this as the final R3 ownership/dependency migration. Confirm every
historical facade is logic-free, the sibling-import count is exactly zero for
both legacy and canonical paths, all eight canonical study packages exist, the
V1.10/V1.11 frozen-evidence boundaries retain semantic validation, and V1.12's
manifest/accounting/path-safety contract plus immutable evidence bytes remain
unchanged. Do not begin R4, merge, access a provider or holdout, or regenerate
evidence as part of this review.
