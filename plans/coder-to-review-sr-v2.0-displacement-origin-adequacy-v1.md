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

Implemented the approved V3 remediation on
`feature/sr-v2.0-displacement-origin-adequacy`. The code change is
`0c93096d05396c6d3791e036284773faaad94c23`, on top of the original V2
implementation.

- Preserved the frozen 629-row TAOUSDT/1d development input; no provider,
  network, holdout, or production path was used.
- Replaced the invalid real-touch-time control with an independently evaluated,
  prior-close naïve band for every in-fold displacement-origin candidate.
- Regenerated deterministic V2 evidence twice from the remediation commit.

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
- Paired metrics now use completed same-side pairs only:
  `real directional quality - same-side naïve control directional quality`.
  Readiness evaluates 24 completed pairs, four comparable folds, four pairs per
  comparable fold, and four controls per side per comparable fold before
  utility gates.
- The runner uses the canonical cohort `source_capsule()` adapter. The study
  now records the outer cohort source bundle and the underlying frozen source
  capsule identity separately.
- Updated strict configuration, contracts, deterministic artifacts and semantic
  recomputation. Tests cover corrected ATR ownership, candle direction,
  independent control touches, pair/config/source identity tampering, and
  readiness/utility disposition precedence.

Deterministic evidence was generated twice with byte-identical outputs:

- Bundle: `7b4ce100136be1ad74f8e29858a127f46b4b467ff577275ec8543e11547372bc`
- Study: `db98da4de57285673f909d0b4c6ae272268bbf74f653675174fcd61b8bef32ee`
- Manifest SHA-256: `d2c28de5b67c6ddd19f5a1a7d67d0b9ccc3b2ef89f4b4ef6c3aef6e0ccb7ca6a`
- Study SHA-256: `d877dfa5dac6b57783c7f6ef8515897077c36e042bd483f4245b6323e92dfd91`
- Manifest/study byte lengths: `6524` / `2879`

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

The old V2 bundle `2623894d…` and study `9856c448…` are superseded, remain
ignored, and were neither modified nor deleted.

# Blast Radius Considered

`detect_displacement_origins` remains an isolated V2 detector; it is not wired
into `SREngine`. The V2 control/outcome and artifact changes are confined to
the V2 study package. Architecture checks confirm no provider, network, legacy
`libs.sr`, sibling-study, or production-engine dependency was introduced.

# Validation Performed

- V2 study, displacement detector, and architecture suites: `86 passed`.
- Full SR suite: `964 passed in 642.43s`.
- V2 artifact semantic recomputation: passed.
- Two V2 CLI evaluations from `0c93096…`: same bundle ID and byte-identical
  `manifest.json` / `study.json`.
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
