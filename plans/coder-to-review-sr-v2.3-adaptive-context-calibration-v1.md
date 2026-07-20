---
goal: Review the immutable SR-V2.3 adaptive-context calibration implementation and frozen evidence.
stage: coder-to-review
date_created: 2026-07-19
last_updated: 2026-07-20
owner: Codex
status: Approved Research Only
tags: [handoff, quant, sr, v2-3, adaptive-context-calibration]
source_agent: Codex
target_agent: Quant Review
---

# SR-V2.3 Adaptive Context Calibration — coder-to-review

## Scope Executed

Implemented the approved offline adaptive-context calibration study, then applied the separately authorized source-boundary and evidence-contract remediations.

- Original implementation commit: `89e66650c0c0e70aac65ddbc2c146cf46a66ed5d`.
- Source-boundary remediation commit: `cbc9d3cc621f47b42a35151c154d87e95b9e4dca`.
- Evidence-contract remediation commit: `275c2a5e67fe2f8bad11851396f89b878dd8cf52`.
- Current evaluation evidence binds `275c2a5`; `89e6665`, `cbc9d3c` as an evaluation identity, and evaluation bundle `28710c9…` are superseded for V2.3 decisions.
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
- Preserved pre-2025 candidates as serialized `HISTORY_ONLY` cases. They are never predicted or scored, but their completed labels enter calibration only when `label_available_at < prediction_at`; completed 2025 labels retain that same strict causal admission rule.
- Preserved every selected hierarchical-bootstrap cohort/fold cell as an independent replica, including duplicate cell selections.
- Hardened evaluation publication/validation against manifest/member/parent symlinks and non-regular members, and added semantic rehash-tampering and implementation-identity mismatch coverage.

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

- Bundle: `f855933bac9e796872a9ac4485c16bbbe250309663bef6f3e08017446b09bde4`
- Study: `eaef681d564d93cbd5af478eb336ad4afb00bc69e90d0877abc543cf46af808c`
- Disposition: `INSUFFICIENT_CALIBRATION_EVIDENCE`
- Evaluation manifest SHA-256: `625682c45763a438d62e7d2ef7482eb2444e6b2ba9fd57f7972b126f283eaaa7`
- Cases SHA-256: `8ffd1a7609705759008b3bca917712619a964179d7b8a16c7822a44e1486dbfe`
- Predictions SHA-256: `34a31eeb01511f038843a5e8de297e81666115a4db933a48cb7b9d0fd5a56118`
- Study SHA-256: `32ae4952234c140ee93979d332f31bed4931586bcbfedbfbdbd70186347f9df4`
- Case accounting: `1,632` total cases, including `476` history-only cases; `1,156` predictions, of which `892` are scored.

The V2.3 semantic validator recomputed the published evaluation successfully with the same study ID and disposition. Both network-free runs produced the exact same bundle, study, and member hashes.

## Blast Radius Considered

The remediation is isolated to V2.3 study contracts, outcomes, metrics, artifact validation, and tests. No runtime path is affected. The real adapter's documented seventh output column is accepted without changing adapter behavior or any shared source contract. Bar payloads retain only OHLCV, so changing taker volume alone leaves V2.3 source/bar identities unchanged by regression.

## Validation Performed

- V2.3 focused study suite: `28 passed`.
- Causal-swing detector suite: `9 passed`.
- SR architecture/import-boundary suite: `36 passed`.
- Ruff, full SR compilation, and `git diff --check`: passed.
- Source bundle structural and semantic load: passed.
- Evaluation executed twice from the frozen source: identical bundle ID and immutable bytes.
- V2.3 public semantic recomputation: passed.
- Protected V2.0 semantic validation: passed; study `5d9a85ef…`, disposition `INSUFFICIENT_EVIDENCE`.
- Final local full SR suite: `1,035 passed in 694.28s`.
- Protected V1.12 manifest and audit byte hashes remain exact:
  - manifest `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`
  - audit `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`

## Not Changed

- `configs/sr.yaml` remains `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`.
- Frozen V2.0, V2.1, V2.2, and V1.12 artifacts were not regenerated or modified.
- Shared daily source contracts, runtime SR model behavior, lifecycle, detection outside V2.3, configuration resolution, and provider adapter code were not changed.
- User-owned untracked architect/review plan drafts were not staged or modified.

## Risks or Follow-up Items

- The long-running V1.12 public semantic-validator invocation completed locally, but the workspace connector did not return its terminal payload. The exact protected bytes are recorded above; re-run the public validator in the review environment for an independently captured result.
- Local closeout command completed outside the workspace connector:

  `PYTHONPATH=src .venv/bin/pytest -q tests/models/sr`

  Result: `1,035 passed in 694.28s`.
- `INSUFFICIENT_CALIBRATION_EVIDENCE` is a research disposition only. It does not authorize tuning, provider refresh, holdout access, runtime integration, production promotion, merge, or V2.4 work.

This package is complete enough for independent review without further implementation changes.
