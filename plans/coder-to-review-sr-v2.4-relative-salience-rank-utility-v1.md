---
goal: Review the immutable SR-V2.4 causal relative-salience rank-utility implementation and fresh six-cohort evidence.
stage: coder-to-review
date_created: 2026-07-20
last_updated: 2026-07-21
owner: Codex
status: Ready
tags: [handoff, quant, sr, v2-4, relative-salience-rank-utility]
source_agent: Codex
target_agent: Quant Review
---

# SR-V2.4 Causal Relative-Salience Rank Utility — coder-to-review

## Scope Executed

Implemented the approved fixed SR-V2.4 rank-utility study and its frozen six-cohort source/evaluation protocol.

- Branch: `feature/sr-v2.4-relative-salience-rank-utility`.
- Offline implementation commit: `8c303b37229018a902ca664bcc71752cec13fc4c`.
- Narrow file-scoped import-boundary remediation commit: `f4d2fe28b524daf0c3439a995a62bab86fd3dc9a`.
- Provenance remediation commit: `a671105407e333713bf6238dd3f9f796d5555674`.
- All frozen source and evaluation evidence binds `f4d2fe28`; `8c303b3` is superseded as an evidence implementation identity.

This is research-only. It does not authorize parameter tuning, another provider request, holdout access, runtime integration, production promotion, merge, a viewer, or V2.5.

## Changes Made

- Added the immutable V2.4 trial configuration and `relative_salience_rank_utility` research study.
- Reused the approved continuous-swing candidates, ATR(14), geometry, lifecycle, paired prior-close controls, and outcome contracts.
- Added a causal `relative_salience_rank` in `[0, 1]`, normalized only against prior cases in the same asset/timeframe with deterministic tie treatment.
- Added fixed evaluation-only quartiles, readiness checks, hierarchical asset/timeframe/month-cell bootstrap (10,000 PCG64 draws, seed `2404`), artifact publication, semantic validation, and tamper/path safety coverage.
- Added exact import-boundary exceptions only for:
  - `relative_salience_rank_utility/metrics.py` -> `numpy`
  - `relative_salience_rank_utility/source.py` -> `apps.ingestion_app.adapters.binance_native`

  The allowlist remains file-scoped and module-exact; it does not broaden SR-wide NumPy or ingestion-app access.
- Corrected provenance-only command behavior: `prepare-source` and `evaluate` resolve current repository HEAD, while `validate` recomputes against `source.implementation_commit`.
- Added a fail-closed source/evaluation implementation-identity check before case construction. A later implementation cannot publish an evaluation from frozen source evidence bound to another commit.

## Blast Radius Considered

The implementation is isolated to the new V2.4 study, its immutable trial YAML, focused tests, and the two explicit import-boundary entries. The shared continuous-swing detector and existing V1/V2 contracts are consumed without modification. The six provider calls occurred only after the evidence implementation commit and full offline validation. The later provenance fix does not alter study semantics or frozen bytes.

## Validation Performed

- Import-boundary, V2.4 focused, and research-architecture tests: `38 passed in 14.32s`.
- Ruff, compilation, and `git diff --check`: passed before the remediation commit.
- The initial full-suite run from `8c303b3` exposed only the missing V2.4 import-boundary allowlist: `1 failed, 1,049 passed in 698.11s`.
- After the authorized narrow remediation, the one permitted full rerun from unchanged `f4d2fe28` passed: `1,050 passed in 700.30s (0:11:40)`.
- Exactly six one-shot provider requests were made after that pass: TAOUSDT, ETHUSDT, and SOLUSDT at `1d` and `12h`; no request retried or failed.
- The source bundle loaded structurally and semantically with each daily cohort at `629` history + `181` fresh rows and each 12-hour cohort at `1,000` history + `362` fresh rows.
- Evaluation ran twice from the immutable source and produced byte-identical output with the same bundle and study IDs.
- V2.4 semantic validation passed, reconstructing the published study and disposition.
- Provenance regression, V2.4 focused, import-boundary, and research-architecture tests: `42 passed in 84.87s`.
- Ruff, compilation, and `git diff --check`: passed for the provenance remediation.
- Required post-remediation full SR suite from unchanged `a671105`: `1,054 passed in 793.65s (0:13:13)`; log: `/tmp/sr-v2.4-provenance-full-suite.log`.
- Protected V2.0 semantic validation passed: study `5d9a85ef87bac80407f969eba244f258ae198a1af508ed1ab27cda079e96360a`, `INSUFFICIENT_EVIDENCE`.
- Protected V2.3 semantic validation passed: study `eaef681d564d93cbd5af478eb336ad4afb00bc69e90d0877abc543cf46af808c`, `INSUFFICIENT_CALIBRATION_EVIDENCE`.
- Protected V1.12 manifest and audit hashes remain exact:
  - manifest `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`
  - audit `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`

## Evidence Produced

Frozen source:

- Bundle: `5c8a9a326e09832ea7b8be33ecea89e94edd8390d58580721197fcdb486ea948`
- Path: `research/tmp_sr_v2_4/source/5c8a9a326e09832ea7b8be33ecea89e94edd8390d58580721197fcdb486ea948`
- Implementation: `f4d2fe28b524daf0c3439a995a62bab86fd3dc9a`
- Manifest SHA-256: `f2334b45b6e463e7aefa35ecc1860962eeda9924d45f4c939dd8caf6f70baa29`

Deterministic evaluation, run twice from that frozen source:

- Bundle: `608314ec70af574b8c233dcc48d631f3059a92fc6a483a7b1c51eab1ba17c7c9`
- Study: `2622e0baa78d7e1a0e1a5fe71edaf48c0fa937721734d8f7d0e54bf8dc1f83ac`
- Disposition: `INSUFFICIENT_RANK_EVIDENCE`
- Evaluation manifest SHA-256: `a1f713f875c8b05e80ed149cd07fe3f69eb8fe7d002b4267734102e4ef3d7468`
- Study SHA-256: `97178df8bd6e2e059bad3473781702d4b522b7563c20b337bd1079fd49d8c3e1`
- Cases SHA-256: `175ce3e7cc39b2b5b39b3e58d2801f757f7b5e729b7c3893ddd451eea44af4cc`
- Cases: `567` total, `462` scored and completed, `23` censored, `101` completed Q4 cases.

Readiness passes for every cohort: TAOUSDT `1d` 57 / `12h` 98; ETHUSDT `1d` 54 / `12h` 102; SOLUSDT `1d` 44 / `12h` 107 completed cases.

Published metrics and central 90% bootstrap intervals:

| Metric | Value | 90% interval |
| --- | ---: | ---: |
| Rank AUC | 0.64965 | [0.57849, 0.71747] |
| Q4 success-rate lift | 0.14161 | [0.02326, 0.26155] |
| Q4 mean paired excess quality (ATR) | 0.12367 | [-0.29212, 0.49287] |
| Median cohort rank lift | 0.13210 | [-0.02940, 0.24865] |

The AUC and Q4 success-lift support gates pass. The Q4 paired-excess and median-cohort-lift lower bounds do not exceed zero; neither non-support upper-bound guardrail fires. The preregistered disposition is therefore `INSUFFICIENT_RANK_EVIDENCE`.

## Not Changed

- No protected V1, V2.0, V2.1, V2.2, or V2.3 evidence was regenerated or modified.
- `configs/sr.yaml` remains SHA-256 `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`.
- No shared runtime S/R model, detector parameter, lifecycle rule, geometry, outcome, control topology, provider adapter, or production configuration changed.
- No provider code, holdout, tuning, viewer, merge, or V2.5 work was started.
- No provider call, source preparation, evaluation publication, artifact regeneration, or new artifact directory occurred during provenance remediation.
- User-owned untracked architect/review plan drafts were not staged or modified.

## Risks or Follow-up Items

- The V1.12 public semantic-validator process stalled without output through this workspace connector and was stopped; this matches prior connector behavior, not a validation failure. Its frozen member hashes remain exact. Re-run that public validator in the review environment if an independently captured terminal result is required.
- The result is insufficient evidence, not support or rejection of the broader descriptive S/R domain. It does not authorize a rescue variant on this source window.

This package is complete enough for independent review without further implementation changes.
