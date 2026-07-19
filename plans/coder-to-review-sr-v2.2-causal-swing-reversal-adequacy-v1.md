---
goal: Review SR-V2.2 causal swing-reversal adequacy implementation and frozen development evidence.
stage: coder-to-review
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Codex
status: Ready
tags: [handoff, quant, sr, v2-2, research]
source_agent: quant-coder
target_agent: quant-review
---

# SR-V2.2 causal swing-reversal adequacy — coder to review

## Scope executed

Implemented the approved V2.2 price-only hypothesis on branch
`feature/sr-v2.2-causal-swing-reversal-adequacy`, based on V2.1 closeout
`bd6c73281629c60c087417ab4e77dd7383feb07a`.

Implementation commit: `5340c519a502c67afc0a9715c962374630a6a91f`.

- Added the causal alternating ATR-reversal detector.
- Added the isolated `swing_reversal_adequacy` research study, typed trial YAML,
  strict artifacts, CLI, and tests.
- Added the study to the research-boundary architecture test.
- Added the missing V2.2 test-package marker required for full-suite collection.

The study is a negative development result:
`SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL`.

## Changes made

### Detector and causal contract

- `src/libs/models/sr/detection/causal_swing_reversal.py` implements the strict
  `UNSEEDED → SEEK_HIGH/SEEK_LOW` state machine, first-unequal-close seeding,
  strict extreme replacement, equal-extreme retention, and alternating
  confirmation.
- A high confirms only at `close[t] <= high[e] - 1.5 * ATR[e]`; a low uses the
  exact mirror. A newly set extreme cannot confirm on the same bar.
- Candidate geometry is the existing V2.1 rejection-wick rectangle. The
  confirmation bar ATR is retained as `atr_at_creation`; the extreme-bar ATR is
  used only for the reversal threshold.
- Candidate availability is the confirmation timestamp; no swing is backdated
  or made available before causal confirmation.

### Study and evidence contract

- Trial configuration is
  `configs/sr_trials/sr_v2_2_taousdt_1d_swing_reversal_adequacy.yaml` with the
  sole detector parameter `{reversal_atr: 1.5}`. Config hash:
  `b543ba3a1e737a3ed6adc438437a1a45a2a609a4b4073ec8a00a4e5005ddfc48`.
- The study consumes the approved frozen TAOUSDT/1d source only:
  outer source bundle `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`,
  source capsule `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`,
  and source ID `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`.
- Each candidate receives two independently evaluated, identical-width
  prior-close naive controls—one per side—using the same confirmation time,
  confirmation ATR, fold, 50-bar expiry, and 10-bar outcome horizon.
- The seven ordered gates are fail-closed and reconcile with disposition.
  Artifact validation rejects semantic tampering, unsafe paths, symlinked
  members, and symlinked bundle parents before reconstructing the complete
  study.

## Blast radius considered

The shared `first_revisit_outcome` and prior-close control helpers also support
V2.1, so they were treated as a high-integrity surface. They were imported
unchanged; no shared outcome, control, V1, V2.0, or V2.1 semantics changed.

The only active-model addition is the new detector module. The V2.2 study is a
separate canonical research package and its import-boundary tests prohibit
sibling-study, legacy `libs.sr`, provider/network, dataframe, and numerical
library imports.

## Evidence produced

Two independent local runs from implementation commit
`5340c519a502c67afc0a9715c962374630a6a91f` produced byte-identical output:

- Bundle: `e50c0a2237c5e909d148eab39a19e75f76037d29c6f92d4a316c348190b47660`
- Study: `34e44ea7c16384bd98bbc99aef162d4f9a516ae0b6ca2e4cc52d75a894e4c846`
- Disposition: `SWING_REVERSAL_NOT_BETTER_THAN_NAIVE_NULL`
- Counts: 56 confirmed swings, 56 candidate cases, 104 controls, 35 completed
  real/control pairs.

Artifact members:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| `manifest.json` | 6,356 | `65583e212ccca19cba3178ad79bd56fe452c2a5b28dc197dcd69a5c802213f42` |
| `study.json` | 3,011 | `3a61c4a7a3ebe3866b99e151ce33d7e7d564c39a8ab089a0c03297453633241f` |
| `cases.json` | 219,282 | `21b3a05576a53f12dc8e92c16fc888346254f44383082b0d45b7f490e9a2a333` |

Readiness passes: 35 completed pairs, five comparable folds, minimum five
pairs per comparable fold, and minimum five controls per side per comparable
fold. Utility does not pass:

- pooled median paired excess: `0.09259058053905056 ATR` vs `>= 0.10`;
- positive comparable-fold fraction: `0.8` vs `>= 0.60`;
- worst comparable-fold median excess: `-1.1099568460331941 ATR` vs `>= -0.10`.

Comparable fold medians are: 2024_q3 `-1.1099568460331941`, 2024_q4
`0.09259058053905056`, 2025_q1 `2.5277414213939577`, 2025_q2
`0.4908152777181951`, and 2025_q4 `0.8443019815959614`. 2025_q3 has two pairs
and is non-comparable.

## Validation performed

- V2.2 detector, study, artifact, config, import-boundary, and architecture
  suite: **37 passed**.
- Full active SR suite: **1002 passed**.
- Ruff, full SR compilation, CLI help, and `git diff --check`: passed.
- V2.2 public semantic reconstruction: passed against bundle `e50c0a22…` and
  implementation `5340c51…`.
- Protected V2.1 semantic reconstruction: bundle
  `99686050a4e8ad17c2bfe0cbda5f2c75278cc9935e5903ab6590460100ac3e94`, study
  `a726b09e1523dbcb90954ba0975dab404ea387c856bd58e35ac4a304b5dac146`,
  disposition `PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL`.
- Protected V2.0 semantic reconstruction: bundle
  `60d8ac404b4e5a6aaf44eb9325bba7ddf6be154f663aa6a08e7a634bedbe695c`, study
  `5d9a85ef87bac80407f969eba244f258ae198a1af508ed1ab27cda079e96360a`,
  disposition `INSUFFICIENT_EVIDENCE`.
- Protected V1.12 public semantic validation: bundle
  `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`, audit
  `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`,
  disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Protected V1.12 hashes remain exact: `configs/sr.yaml`
  `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`, manifest
  `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`, and audit
  `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

## Not changed

- No V1, V2.0, or V2.1 algorithm, configuration, evidence, runtime wiring, or
  viewer behavior.
- No provider call, source refresh, database access, holdout access, tuning,
  parameter grid, production change, merge, or V2.3 work.
- Existing ignored V2.2 evidence was not committed.
- The six pre-existing untracked architect/review plan drafts were left
  untouched.

## Risks or follow-up items

There are no implementation blockers known to the coder. This is the final
predeclared price-only V2 screening hypothesis. Its negative disposition does
not justify rescue tuning or another price-structure kernel on this frozen
TAOUSDT development cohort. Review should assess contract preservation and
evidence integrity only; it must not authorize holdout access, runtime
integration, production promotion, merge, or V2.3 work.
