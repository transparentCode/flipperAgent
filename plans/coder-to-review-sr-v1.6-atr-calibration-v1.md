---
goal: Deliver remediated SR-V1.6 ATR calibration development evidence for review
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Coder Agent
status: 'Ready'
tags: [handoff, quant, sr, atr-calibration, taousdt, development-evidence, leakage-control]
source_agent: Coder Agent
target_agent: Quant Review Agent
---

# SR-V1.6 ATR Calibration — Coder To Review

## Scope Executed

Applied the issued V1.6 remediation on branch
`feature/sr-v1.6-atr-calibration`, based on the approved V1.5 lineage. The
implementation/test commit is:

`8109b6c400639be2f1b2057cc37117b3fab08020`

The handoff is a separate documentation-only commit immediately following
that implementation commit. No merge was performed.

This correction intentionally regenerates development evidence only. It does
not open or score a holdout.

## Changes Made

- Development selection now discovers exactly one published development
  capsule for the current implementation context. It no longer calls
  `build_source_capsules()` or `load_frozen_source()`.
- The no-challenger holdout path uses the same published-development loader
  and does not open sealed bars.
- Development artifact validation recomputes all candidate replays, metrics,
  and `select_development()` from the validated development capsule and
  requires exact selection payload equality.
- Added a complete holdout bundle validator. Selected-challenger holdout
  metrics are recomputed from the validated sealed capsule before acceptance;
  no-selection bundles are checked against the immutable disposition without
  sealed input.
- Manifests and protocol members bind the ATR implementation contract, exact
  candidate set, baseline/reference/common periods, six folds, half-open
  window policy, outcome protocol, gates, source identity, resolved SR/input
  hashes, and implementation commit.
- Configuration now locks offset `1`, horizon `10`, all six approved fold
  boundaries, and all approved gate values.
- Terminal/cohort accounting now uses the explicit half-open rule: events at a
  window end belong to the following window.
- Added adversarial coverage for sealed-source denial, rehashed selection and
  protocol tampering, selected-challenger holdout validation, rehashed
  holdout metric tampering, exact protocol mutations, and the half-open end
  boundary.

## Blast Radius Considered

Changed only these V1.6 calibration modules:

- `src/libs/models/sr/scripts/atr_calibration/artifacts.py`
- `src/libs/models/sr/scripts/atr_calibration/config.py`
- `src/libs/models/sr/scripts/atr_calibration/metrics.py`
- `src/libs/models/sr/scripts/atr_calibration/runner.py`
- `src/libs/models/sr/scripts/atr_calibration/selection.py`
- `src/libs/models/sr/scripts/atr_calibration/source.py`

And the matching calibration tests in
`tests/models/sr/scripts/atr_calibration/`.

The protected SR domain/config/detection/association/lifecycle/replay/
serialization/evaluation packages, production YAML, V1.5 baseline code and
evidence, ATR implementation, Binance adapter, and viewer remain unchanged.
The working-tree changes under `.codebase-memory/` and all unrelated plan
drafts remain unstaged and untouched.

## Frozen Source And Development Evidence

The approved V1.5 parent remains:

| Identity | Value |
|---|---|
| parent bundle | `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925` |
| parent implementation | `2b8306b21a7e69f097218ffa05c34515b607de75` |
| source rows | `811` |
| source bars SHA-256 | `b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535` |
| resolved SR config hash | `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299` |
| resolved input hash | `5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d` |

The parent bundle was validated before preparing the new development capsule;
no Binance, network client, or provider call occurred.

Current development-only evidence, bound to implementation commit
`8109b6c400639be2f1b2057cc37117b3fab08020`:

| Stage | ID | Path | Result |
|---|---|---|---|
| development source | `7329c32250dd3af8b0e27091ab2306fce6aae7ce79c4e92ef8c9b585e3397642` | `research/tmp_sr_v1_6/source/development/7329c32250dd3af8b0e27091ab2306fce6aae7ce79c4e92ef8c9b585e3397642/` | 629 prefix rows |
| development selection bundle | `053ddeb3ebd9fc763d71e14b963315c4bf1a8c70365718dbd833ab099260a5f8` | `research/tmp_sr_v1_6/development/053ddeb3ebd9fc763d71e14b963315c4bf1a8c70365718dbd833ab099260a5f8/` | `RETAIN_GLOBAL_14` |
| selection | `9ad1ac408d109e83138dead259771225d402a1cecbff2567256e966a6cef58dd` | inside the development bundle | no challenger |

Two development-capsule publications produced the same source ID and bytes.
Two `select-development` runs produced identical selection and bundle IDs and
byte-identical members. No sealed capsule or current-commit holdout bundle was
created.

The earlier V1.6 evidence is not reusable: the prior sealed source was
accessed programmatically by the rejected implementation. Therefore the prior
development source `9892862e…`, sealed source `d484c2f…`, development bundle
`d797af79…`, selection `483fcbb4…`, and holdout bundle `5b1b5b32…` are recorded
as contaminated/unusable and are not described as unopened evidence.

## Development Results

Fold cells are `completed outcomes / median quality in reference ATR(14)
units`; folds are ordered `2024_q3`, `2024_q4`, `2025_q1`, `2025_q2`,
`2025_q3`, `2025_q4`.

| Period | Fold cells | Pooled completed | Pooled median quality | Disposition |
|---:|---|---:|---:|---|
| 7 | 7/-1.5167, 8/-0.5278, 6/0.8112, 5/0.9828, 3/2.1127, 4/0.9266 | 35 | 0.1250 | ineligible |
| 10 | 7/-1.5167, 8/-0.0459, 6/0.8112, 5/0.9828, 3/2.1127, 4/0.9266 | 35 | 0.1250 | ineligible |
| 14 baseline | 7/-1.5167, 8/-0.0459, 6/0.8112, 6/-1.1546, 3/0.4786, 4/0.9266 | 36 | -0.0141 | baseline |
| 20 | 7/-1.7637, 8/-0.0459, 6/0.8112, 6/-1.1546, 3/0.4786, 4/0.6534 | 36 | -0.1850 | ineligible |
| 28 | 6/-1.7348, 8/-0.0459, 6/0.8112, 6/-1.1546, 3/0.4786, 4/0.6534 | 35 | -0.1531 | ineligible |

All four non-14 challengers were fully evaluable under the development
coverage gates, but none passed the strict fold-win and/or pooled-quality
gates. The frozen development disposition is `RETAIN_GLOBAL_14`; no challenger
was eligible for holdout scoring.

## Holdout Status

The prior sealed window is contaminated and unusable because it was accessed
programmatically during the earlier development-selection path. No current
implementation holdout was opened or scored. Since development selected no
challenger, no holdout score is needed for this disposition. A fresh forward
holdout remains reserved for any future protocol that produces a selected
challenger; it must not reuse the contaminated window.

`configs/sr_inputs.yaml` remains unchanged and retains global Wilder ATR(14).
No asset/timeframe override was written.

## Validation Performed

- Full SR suite: **387 passed**.
- V1.6 targeted suite: **33 passed**.
- Import boundaries: **2 passed**.
- Ruff: passed with `ruff check src/libs/models/sr tests/models/sr`.
- Compilation: passed for `src/libs/models/sr` and `tests/models/sr`.
- `git diff --check`: passed.
- Rehashed development selection tampering: rejected after semantic
  recomputation.
- Rehashed protocol mutation: rejected against the locked protocol.
- Rehashed selected-holdout metrics: rejected after sealed-input
  recomputation.
- Sealed-source spies: `load_frozen_source()` and `build_source_capsules()`
  were denied successfully during development selection and the no-challenger
  path.
- Current development source and selection reruns: identical IDs and
  byte-identical members.

## Not Changed

No holdout was scored, no production configuration was edited, no SR model
behavior was changed, and no generated evidence was committed. No provider or
network call occurred. Existing contaminated artifacts, `.codebase-memory`
changes, and unrelated drafts were not modified or staged. No merge was
performed.

## Risks Or Follow-Up Items

- The prior sealed/holdout evidence must remain permanently excluded from any
  approval claim.
- Any future challenger requires a fresh forward holdout under a new auditable
  protocol; this run must not become a tuning loop.
- Evidence remains one asset/timeframe with a finite first-touch sample and a
  fixed 10-bar horizon; it is not PnL, profitability, or trading-readiness
  evidence.

This package is ready for independent rereview of the remediation and
development-only evidence. It is intentionally unmerged and does not claim
final V1.6 holdout approval.
