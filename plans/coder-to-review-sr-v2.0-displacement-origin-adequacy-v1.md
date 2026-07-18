---
goal: Review SR-V2.0 displacement-origin adequacy implementation and frozen development evidence.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: Codex
status: Ready
tags: [handoff, quant, sr, v2, displacement-origin, adequacy]
source_agent: Codex quant-coder
target_agent: Quant Review Agent
---

# Scope Executed

Implemented the approved SR-V2.0 displacement-origin adequacy experiment on
`feature/sr-v2.0-displacement-origin-adequacy`, based on
`4dd1f74d22dc0296c3d09599ef75906a7d0f147a`.

- Added a pure, closed-bar displacement-origin candidate detector with the
  locked four-parameter V2 baseline.
- Added strict trial configuration and a standalone canonical research study.
- Evaluated only the frozen 629-row TAOUSDT/1d development input. No provider,
  refresh, holdout, or production engine path was used.
- Reused neutral ATR, source, fold, control, artifact, path-safety, and
  provenance services. The small shared control-outcome extraction preserves
  V1 baseline-control behavior.

# Changes Made

- `detection/displacement_origin.py`: causal candidate detection using prior
  ATR, strict five-bar structure, nearest opposing base in the prior three
  bars, and immutable full-range geometry.
- `configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml`:
  locked source, ATR, detector, folds, outcomes, gates, controls, and artifact
  protocol; no numeric fallback defaults.
- `research/studies/displacement_origin_adequacy/`: strict configuration,
  raw-zone first-touch outcomes, matched controls, gates, artifact publication,
  semantic validation, runner, and CLI.
- `research/evidence/baseline_adequacy/controls.py`: extracted the existing
  pure control-outcome calculation for neutral reuse; V1 wrapper behavior is
  retained.
- Focused detector, configuration, outcome, gate, runner, import-boundary, and
  rehashed-artifact tamper tests. Added exact 50-bar expiry coverage and tests
  for case, metric, identity, and disposition tampering.

Final implementation commit: `159806458bfce5b4a480ac33242269b51c5724e2`.

Deterministic evidence was generated twice from that commit with identical
member bytes:

- Bundle: `2623894d6cc782a967c6f2c83305c42d598eba34effa45ae34407734fb3cd5c4`
- Study: `9856c44834cd1355431c8b4b2adf92fbefadbbcc203f85b31b6628236db5fd58`
- Manifest SHA-256: `7435d0b785d00502ead5024c0d680c182ca2cc7955f07f38f5c4b0d8beab581c`
- Study SHA-256: `3ad4a962bb5751f13bdafe5ca57df75beb62a7afe86276befee16b6789fed85a`
- Cases SHA-256: `6a6fc55c34a51d0c3407807689cfc94731403755fd5e42d2052fbd043a3445b8`

Result: `INSUFFICIENT_EVIDENCE`.

- 28 candidates: 19 support, 9 resistance.
- 23 completed first-touch outcomes; 5 no-touch cases; 46 matched controls.
- Fold candidate counts: 2024_q3=7, 2024_q4=4, 2025_q1=1, 2025_q2=8,
  2025_q3=5, 2025_q4=3.
- Base-distance counts: one bar=13, two bars=6, three bars=9.
- Four comparable folds. Readiness fails only completed outcomes: 23 vs 24.
- Diagnostic utility values: pooled median excess `0.6662978121065044 ATR`,
  positive comparable-fold fraction `0.5`, worst fold `0.0 ATR`.

# Blast Radius Considered

`detect_displacement_origins` is a new isolated detector, not wired into
`SREngine`. The only shared-symbol change is the pure control-outcome helper;
its direct V1 control regression was included in the focused validation and
the complete SR suite. Architecture checks confirm the V2 study has no sibling
study, provider, network, or legacy `libs.sr` imports.

# Validation Performed

- `tests/models/sr/detection/test_displacement_origin.py -q -rA`: 21 passed.
- `tests/models/sr/research/studies/displacement_origin_adequacy -q -rA`:
  21 passed.
- `tests/models/sr/architecture -q`: 34 passed.
- `tests/models/sr -q`: 954 passed in 656.93 seconds.
- Ruff: `$HOME/.local/bin/ruff check src/libs/models/sr tests/models/sr`.
- Compilation: `PYTHONPATH=src .venv/bin/python -m compileall -q
  src/libs/models/sr`.
- Package import and V2 CLI help: passed.
- `git diff --check`: passed.
- V2 bundle semantic recomputation: passed.
- V1.12 public semantic validation: passed with 65 candidates, 50 created
  zones, 15 eligible matches, 13 unique reinforced zones, and
  `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Frozen protected hashes remain exact:
  `configs/sr.yaml` `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`,
  V1.12 manifest `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`,
  V1.12 audit `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

# Not Changed

No V1 engine, lifecycle, association, detection behavior, `configs/sr.yaml`,
provider, network, database, holdout, viewer, deployment, production decision,
or legacy `libs.sr` code changed. Generated V2 evidence is ignored and was not
committed. No merge or V2.1 work was performed.

# Risks or Follow-Up Items

No implementation blocker is known. The result is a readiness failure, not
permission to loosen V2.0 parameters or fetch more data. Review should verify
the causal detector, raw-zone outcome timing, control equivalence, and semantic
artifact validator against the locked plan. If accepted, route the result using
the plan's `INSUFFICIENT_EVIDENCE` decision rule; do not tune this detector in
this branch.
