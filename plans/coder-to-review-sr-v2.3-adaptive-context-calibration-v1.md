---
goal: Review the immutable SR-V2.3 adaptive-context calibration implementation and frozen evidence.
stage: coder-to-review
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Codex
status: Ready
tags: [handoff, quant, sr, v2-3, adaptive-context-calibration]
source_agent: Codex
target_agent: Quant Review
---

# SR-V2.3 Adaptive Context Calibration — coder-to-review

## Scope Executed

Implemented the approved offline adaptive-context calibration study, then applied the separately authorized source-boundary remediation before any valid source artifact was published.

- Implementation commit: `89e66650c0c0e70aac65ddbc2c146cf46a66ed5d`.
- Source-boundary remediation commit: `cbc9d3cc621f47b42a35151c154d87e95b9e4dca`.
- Evidence binds `cbc9d3c`; `89e6665` is superseded for V2.3 evidence purposes.
- Branch: `feature/sr-v2.3-adaptive-context-calibration`.

The study remains research-only. It adds no runtime wiring, parameters, tuning grid, provider retry, holdout access, production behavior, merge, or V2.4 work.

## Changes Made

- Added the V2.3 immutable trial configuration and the `adaptive_context_calibration` study package.
- Added the causal continuous-swing salience detector and offline calibration/evaluation flow defined by the approved handoff.
- Kept the shared daily `SourceBar` contract untouched; V2.3's 12-hour `IntervalBar` remains study-local.
- Corrected the provider boundary to accept exactly the documented Binance adapter schema, in this order:

  `timestamp, open, high, low, close, volume, taker_buy_base`

  `taker_buy_base` is validated finite and nonnegative, then discarded before `IntervalBar` construction. It is neither a model feature nor part of interval-bar/source identities.
- Added an offline integration regression using `BinanceNativeAdapter`'s real parser with mocked raw Binance kline rows, plus strict missing/unknown/reordered-column and negative-taker-volume cases.

## Evidence Produced

Provider accounting is complete and exhausted:

- The first TAOUSDT request under `89e6665` consumed one request but was rejected before publication because the old six-column boundary was incorrect. No source or evaluation evidence was published from it.
- After `cbc9d3c` and all offline gates, exactly one replacement TAOUSDT request, one ETHUSDT request, and one SOLUSDT request succeeded.
- No retries or further provider requests were made.

Frozen source bundle:

- Bundle: `041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e`
- Path: `research/tmp_sr_v2_3/source/041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e`
- Implementation: `cbc9d3cc621f47b42a35151c154d87e95b9e4dca`
- Three provider members: TAOUSDT, ETHUSDT, SOLUSDT, each exactly 1,000 12-hour rows.
- Source manifest SHA-256: `bb3720101cd9f87dca9665f768b293c76d7f5c3eb58324473c9db883d38238a4`.

Deterministic evaluation, run twice from that frozen source:

- Bundle: `28710c9cf50fc955893ed23a1e9120a9f506f0a041c3547068b1339ae9d6ba3c`
- Study: `5d6c0743b2c91272f02da5be2a4bb0245e5c29624c9f055d4c7d05e76b37fd2e`
- Disposition: `INSUFFICIENT_CALIBRATION_EVIDENCE`
- Evaluation manifest SHA-256: `ff3e6ae33fa950d2236c8057044f5231e08b98f746c6a4479b2fc81e8d6e09ca`
- Cases SHA-256: `72299e508b92d80b4c943de1b63ddc31befc5204c96589ac307b6ec0df2757b3`
- Predictions SHA-256: `7e085d96400954947e2a215d741ca980e43fd88b8796445ea15f4e7e3020746e`
- Study SHA-256: `4ef8da9ea0321800526670f429f392bca9689670e79ed63ceed88a1fe7d8fc66`

The V2.3 semantic validator recomputed the published evaluation successfully with the same study ID and disposition.

## Blast Radius Considered

The remediation is isolated to V2.3's provider-response boundary and its tests. The real adapter's documented seventh output column is accepted without changing adapter behavior or any shared source contract. Bar payloads retain only OHLCV, so changing taker volume alone leaves V2.3 source/bar identities unchanged by regression.

## Validation Performed

- V2.3 focused detector/study/architecture/import-boundary suite: 47 tests passed.
- Full active SR suite: 1,026 tests passed.
- Ruff, full SR compilation, import-boundary checks, and `git diff --check`: passed before live calls.
- Source bundle structural and semantic load: passed.
- Evaluation executed twice from the frozen source: identical bundle ID and immutable bytes.
- V2.3 public semantic recomputation: passed.
- Protected V2.0 semantic validation: passed; study `5d9a85ef…`, disposition `INSUFFICIENT_EVIDENCE`.
- Protected V2.1 semantic validation: passed; study `a726b09e…`, disposition `PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL`.
- Protected V1.12 manifest and audit byte hashes remain exact:
  - manifest `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`
  - audit `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`

## Not Changed

- `configs/sr.yaml` remains `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`.
- Frozen V2.0, V2.1, V2.2, and V1.12 artifacts were not regenerated or modified.
- Shared daily source contracts, runtime SR model behavior, lifecycle, detection outside V2.3, configuration resolution, and provider adapter code were not changed.
- User-owned untracked architect/review plan drafts were not staged or modified.

## Risks or Follow-up Items

- The long-running V1.12 public semantic-validator invocation started correctly but was terminated by the workspace connector response limit before it returned a result. This is a validation-channel limitation, not a source/evidence mutation; the exact V1.12 bytes are recorded above. Re-run that public validator in the review environment.
- `INSUFFICIENT_CALIBRATION_EVIDENCE` is a research disposition only. It does not authorize tuning, provider refresh, holdout access, runtime integration, production promotion, merge, or V2.4 work.

This package is complete enough for independent review without further implementation changes.
