---
goal: Review the frozen SR-V2.1 pivot-rejection adequacy implementation and development evidence.
stage: coder-to-review
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Codex
status: Review Ready
tags: [handoff, quant, sr, v2.1, pivot, rejection-wick, adequacy]
source_agent: Codex quant-coder
target_agent: Quant Review Agent
source_base: 83428720308f7cce8a3ba5823911b23638792d96
implementation_commit: 13f5ae54d29fdb8bf9934071c09fa8e276ee9b27
---

# Scope Executed

Implemented SR-V2.1 on `feature/sr-v2.1-pivot-rejection-adequacy` from exact
base `8342872…`. The immutable implementation commit is `13f5ae5…`.

- Added an unregistered strict span-5 pivot-rejection detector. It uses only
  causal confirmation, stores confirmation-bar ATR, and emits observed wick
  rectangles: resistance `[max(open, close), high]`, support
  `[low, min(open, close)]`.
- Added V2.1-only strict YAML, local frozen-source loading through canonical
  `source_capsule()`, independently evaluated same-width prior-close controls,
  paired metrics, immutable artifacts, semantic validation, CLI, and focused
  tests.
- Extracted only inclusive band intersection into neutral research metrics and
  made V2.0 use it; V2.0 semantic evidence still recomputes exactly.

No V1 engine/runtime wiring occurred. The detector is not registered with
`SREngine`.

# Changes Made

- `detection/pivot_rejection.py`: pure strict causal pivot/rejection-wick
  candidate detection, deterministic resistance-before-support ordering, tie
  rejection, zero-width suppression, and confirmation-ATR provenance.
- `research/metrics/first_revisit.py`: detector-neutral inclusive band
  intersection, causal first-revisit/horizon calculation, and prior-close
  matched-band construction. It has no study, provider, network, or I/O
  imports.
- `research/studies/pivot_rejection_adequacy/`: study-owned V2.1 config,
  contracts, outcome/metric semantics, artifact publication/validation, runner
  and CLI. It imports no sibling study.
- `configs/sr_trials/sr_v2_1_taousdt_1d_pivot_rejection_adequacy.yaml`:
  strict frozen TAOUSDT/1d configuration; SHA-256
  `0ab7b7ff86a9e0388489131a5e55f27ca12dce3d77d1ab087754c9a1d4960aa2`.
- Added detector/config/study/artifact/import-boundary regressions, including
  causal control identity, wrong-prior-close rejection, exact two-control
  topology, independent control touch timing, strict config mutation, and
  semantic recomputation.
- Updated architecture’s canonical study-set assertion to include the approved
  V2.1 package; added the test-package marker required for hermetic full-suite
  collection.

# Evidence

Two evaluations from `13f5ae5…` produced byte-identical V2.1 evidence:

- Bundle: `a031f6067ffd256fbeb882933394f12d80d6997152d5d5d948227aae7319b157`
- Study: `05ea5b0c8b17a8bdb585bc9d33098971368ca6e59cfca1d9c00d9ae82297fdd0`
- Manifest SHA-256 / bytes: `cb3c8bf46a87db213db70e3d86b8e5557ee30bb63c0977c1ee0cc9dac3f77944` / `6370`
- Study SHA-256 / bytes: `1d6a61815d875375667d71652cb80c686db94ed8d6348a9533be383ba1e77d00` / `2956`
- Cases SHA-256 / bytes: `eb23f3c6278f85e0ca041190988838ec49d623ae2d6bd7600de296fd38d70f9c` / `233373`

Source identity is unchanged:

- Outer cohort bundle:
  `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`
- Canonical source capsule:
  `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`
- Source ID: `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`

The earlier ignored V2.1 bundle `04ea1b60…` was produced before the required
test-package/architecture correction and is superseded. It was not modified
or committed.

## Result

`PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL`.

- Candidates: `65`; in-fold candidates: `60`; controls: `120`; completed
  same-side pairs: `38`.
- Real statuses: completed `40`, no-touch `17`, right-censored `3`,
  outside-fold `5`.
- Control statuses: completed `104`, no-touch `8`, right-censored `8`.
- Comparable folds: `2024_q3`, `2024_q4`, `2025_q1`, `2025_q2`, `2025_q4`.
- Per-fold completed pairs: `7`, `8`, `7`, `6`, `3`, `7` respectively.
- Readiness gates all pass: pairs `38/24`, comparable folds `5/4`, minimum
  comparable-fold pairs `6/4`, minimum controls per side `8/4`.
- Utility gates fail: pooled median paired excess `0.0 < 0.10`, positive fold
  fraction `0.4 < 0.60`, worst median `-0.46570768758912295 < -0.10` ATR.

# Blast Radius Considered

The new detector and study are research-only. The only V2.0 touch is a pure
intersection delegation; its exact protected semantic bundle still validates.
No production configuration, core state, lifecycle, detection registry,
association, replay, checkpoint, provider, viewer, database, or legacy
`libs.sr` path changed.

# Validation Performed

- V2.1 focused detector/study/artifact/import suite: `10 passed`.
- Existing V2 displacement-origin/detector suite after neutral extraction:
  `56 passed`.
- V2.1 semantic reconstruction and CLI help: passed.
- V2.0 semantic reconstruction: passed exactly with study
  `5d9a85ef…`, `28` candidates, `56` controls, `23` pairs, and
  `INSUFFICIENT_EVIDENCE`.
- Full active SR suite: `978 passed in 684.76s`.
- Ruff (`$HOME/.local/bin/ruff check src/libs/models/sr tests/models/sr`),
  `compileall`, package imports, and `git diff --check 8342872..HEAD`: passed.
- Protected V1.12 bytes remain exact: `configs/sr.yaml`
  `0c7c11ae…`, manifest `c2d0e03f…`, audit `41bd97da…`.
- Deterministic rerun: same V2.1 bundle ID and member SHA-256 values above.

# Not Changed

No tuning, parameter change, provider/network call, source refresh, holdout
access, V1 production behavior, runtime integration, merge, deployment,
viewer work, legacy import, V2.0 artifact rewrite, or V2.2 work occurred.
Generated V2.1 evidence remains ignored.

# Risks or Follow-Up Items

No implementation blocker is known. Review should independently verify strict
span-5 prefix causality, wick formulas and confirmation ATR, causal control
identity/topology, independent touch outcomes, pair/gate math, semantic
tamper/path rejection, and the negative development disposition. This result
does not authorize tuning, holdout access, runtime wiring, trading, or
promotion.
