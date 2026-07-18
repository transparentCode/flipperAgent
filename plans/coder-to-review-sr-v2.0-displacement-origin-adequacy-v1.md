---
goal: Review the corrected SR-V2.0 displacement-origin adequacy implementation and frozen development evidence.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: Codex
status: Review Ready
tags: [handoff, quant, sr, v2, displacement-origin, adequacy]
source_agent: Codex quant-coder
target_agent: Quant Review Agent
---

# Scope Executed

Implemented bounded review remediation on
`feature/sr-v2.0-displacement-origin-adequacy`. Implementation commit:
`689990051168bed5c58cd08130a451afcc6ab600`, on top of V3 correction
`0c93096d05396c6d3791e036284773faaad94c23`.

- Preserved the frozen 629-row TAOUSDT/1d development input; no provider,
  network, holdout, or production path was used.
- Replaced the invalid real-touch-time control with an independently evaluated,
  prior-close naïve band for every in-fold displacement-origin candidate.
- Regenerated deterministic V2 evidence twice from `6899900…`.

# Changes Made

- `detection/displacement_origin.py`: prior-bar ATR still scales only the
  displacement threshold; each candidate stores confirmation-bar ATR. Support
  now requires `close > open`; resistance requires `close < open`, in addition
  to the existing strict structural-break conditions.
- `research/studies/displacement_origin_adequacy/`: builds two controls per
  in-fold candidate at `close[t-1]`, with the real candidate's half-width,
  confirmation time, confirmation ATR, fold, and each stable side. Controls
  locate their own first touch from `t+1`; they are not conditioned on a real
  touch.
- `CandidateCase.confirmation_id` is a causal confirmation-time identity.
  Controls bind it instead of outcome-bearing `case_id`; real status/outcome
  remains in the casebook and study identity.
- Study construction now requires exact ordered
  `(confirmation_id, SUPPORT), (confirmation_id, RESISTANCE)` controls for
  each in-fold candidate. Missing, extra, reordered, or duplicate-side controls
  fail before pairing.
- Paired metrics now use completed same-side pairs only:
  `real directional quality - same-side naïve control directional quality`.
  Readiness evaluates 24 completed pairs, four comparable folds, four pairs per
  comparable fold, and four controls per side per comparable fold before
  utility gates.
- The runner uses the canonical cohort `source_capsule()` adapter. The study
  now records the outer cohort source bundle and the underlying frozen source
  capsule identity separately.
- Updated contracts, deterministic artifacts and semantic recomputation. Tests
  cover outcome-independent control IDs, exact per-case topology, ATR body
  strictly between prior/current ATR thresholds, width-dependent naïve touch,
  independent control touches, and rehashed causal-ID tampering.

Deterministic evidence was generated twice with byte-identical outputs:

- Bundle: `60d8ac404b4e5a6aaf44eb9325bba7ddf6be154f663aa6a08e7a634bedbe695c`
- Study: `5d9a85ef87bac80407f969eba244f258ae198a1af508ed1ab27cda079e96360a`
- Manifest SHA-256: `223821f50a9e4b2e6329b9441510eb3d46dc32258ef1c298262ca3467c7631f2`
- Study SHA-256: `5d7fa49cec06811cd71113e97bf9c0f0a043b3dcf484a512be59b7095536a480`
- Cases SHA-256: `1dbc19acb1944e89ad02ecc518c4498662dcf9aaf4a9b798b0cf45cda956fb47`
- Manifest/study/cases byte lengths: `6524` / `2879` / `107625`

Semantic reconstruction returns 28 candidates, 56 controls, and 23 completed
same-side pairs. The outer cohort source bundle is
`6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`; the
canonical source capsule bundle is
`d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`.

Result: `INSUFFICIENT_EVIDENCE`.

- Comparable folds: `2024_q3`, `2024_q4`, `2025_q2`, `2025_q3`.
- Completed pairs: `23 / 24` required; the readiness disposition is therefore
  authoritative.
- Diagnostic paired utility: pooled median `0.0 ATR`, positive comparable-fold
  fraction `0.0`, worst comparable-fold median `-0.14263155242029035 ATR`.

Old V2 bundles `2623894d…` and `7b4ce100…`, with studies `9856c448…` and
`db98da4…`, are superseded, remain ignored, and were neither modified nor
deleted.

# Blast Radius Considered

`detect_displacement_origins` remains an isolated V2 detector; it is not wired
into `SREngine`. The V2 control/outcome and artifact changes are confined to
the V2 study package. Architecture checks confirm no provider, network, legacy
`libs.sr`, sibling-study, or production-engine dependency was introduced.

# Validation Performed

- V2 study suite: `32 passed`.
- Detector, focused V2 remediation, and architecture suites: `90 passed`
  (detector `24`, V2 study `32`, architecture `34`).
- Full SR suite: `968 passed in 640.17s`.
- V2 artifact semantic recomputation: passed.
- Two V2 CLI evaluations from `6899900…`: same bundle ID and byte-identical
  `manifest.json`, `study.json`, and `cases.json`.
- Ruff: `$HOME/.local/bin/ruff check src/libs/models/sr tests/models/sr`.
- Compilation: `PYTHONPATH=src .venv/bin/python -m compileall -q
  src/libs/models/sr`.
- V2 CLI help and package import: passed.
- `git diff --check 4dd1f74..HEAD`: passed.
- V1.12 public semantic validation: passed with 65 candidates, 50 created
  zones, 15 eligible matches, 13 unique reinforced zones, and
  `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Protected hashes remain exact: `configs/sr.yaml`
  `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`, V1.12
  manifest `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`,
  V1.12 audit `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

# Not Changed

No V1 model, engine, lifecycle, association, `configs/sr.yaml`, provider,
network, database, holdout, viewer, production decision, deployment, legacy
`libs.sr`, merge, tuning, or V2.1 work changed. Generated V2 evidence is
ignored and is not committed.

# Risks or Follow-Up Items

No implementation blocker is known. The corrected result is an evidence
shortfall, not permission to loosen parameters, fetch data, access holdout, or
promote this detector. Review should verify candidate ATR/direction semantics,
prior-close control geometry and independent touch timing, paired gate
accounting, source-capsule provenance, and semantic artifact reconstruction.
