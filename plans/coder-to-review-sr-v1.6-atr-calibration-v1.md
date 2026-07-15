---
goal: Deliver SR-V1.6 ATR-period calibration evidence for review
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Coder Agent
status: 'Review Ready'
tags: [handoff, quant, sr, atr-calibration, taousdt, walk-forward, holdout, evidence]
source_agent: Coder Agent
target_agent: Quant Review Agent
---

# SR-V1.6 ATR Calibration — Coder To Review

## Scope Executed

Implemented the approved, leakage-controlled ATR-period calibration protocol
from base `1ee8cdea0b1ca9563d55f7ddab6d4a087fc3f2b4` on branch
`feature/sr-v1.6-atr-calibration`.

The implementation commit is:

`3250dc47cd28e71b12593cd6f6b8247ef689a00a`

Implementation lineage:

- `e6217fbf47ce9a89ed63d76622d333db3b4e3db4` — initial V1.6 implementation and tests;
- `660f09e2bd21bd291e1cb6f4c1866147811efb40` — exact-context development artifact discovery;
- `3250dc47cd28e71b12593cd6f6b8247ef689a00a` — sealed-source identity hardening.

The separate documentation-only handoff commit is the commit immediately
following the implementation commit in this branch and is reported with the
final handoff. No merge was performed.

## Changes Made

Added:

- `configs/sr_trials/taousdt_1d_atr_calibration.yaml` with the locked
  TAOUSDT/1d protocol, candidate periods `[7, 10, 14, 20, 28]`, baseline and
  reference ATR(14), six UTC development folds, the 2026-01-01 to 2026-07-01
  holdout boundary, and all approved gates.
- `src/libs/models/sr/scripts/atr_calibration/` containing strict config and
  source contracts, frozen V1.5 source validation, development/sealed source
  capsules, existing-ATR candidate replay, first-touch metrics, development
  selection, holdout recommendation gates, deterministic artifact publication,
  and the three-command CLI.
- `tests/models/sr/scripts/atr_calibration/` with 24 configuration, contract,
  source, causality, metric, selection, artifact, CLI, and runner tests.

The development selector has no holdout input. Holdout evaluation accepts only
the immutable development selection plus the sealed source and evaluates only
ATR(14) and the selected challenger. This run selected no challenger, so no
sealed holdout replay or non-14 holdout evaluation was opened.

## Blast Radius Considered

The new package is isolated below `libs.models.sr.scripts.atr_calibration` and
is not exported from `libs.models.sr`. It calls only the approved existing
SR resolver, ATR implementation, domain factory, replay runner, evaluation
trace builder, and diagnostics APIs. No existing SR symbol was changed.

Protected-path comparison against the exact base commit is clean for:

- `src/libs/models/sr/config/`, `domain/`, `detection/`, `association/`,
  `lifecycle/`, `replay/`, `serialization/`, and `evaluation/`;
- `configs/sr.yaml`, `configs/sr_inputs.yaml`, and the V1.5 baseline config;
- `src/libs/models/sr/scripts/baseline_trial/`;
- `src/libs/models/sr/tools/zone_viewer/`; and
- `apps/ingestion_app/adapters/binance_native.py`.

The import-boundary test passes with no Binance adapter, network client, or
provider call in the V1.6 integration. The package root remains side-effect
free.

## Frozen Source And Configuration Evidence

The exact approved V1.5 parent was validated before capsule publication:

| Identity | Value |
|---|---|
| parent bundle | `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925` |
| parent implementation | `2b8306b21a7e69f097218ffa05c34515b607de75` |
| venue / symbol / timeframe | `binance_usdm / TAOUSDT / 1d` |
| source rows | `811` |
| source window | `[2024-01-01T00:00:00Z, 2026-07-01T00:00:00Z)` |
| actual source | `2024-04-11T00:00:00Z` through `2026-07-01T00:00:00Z` |
| `source_bars.json` SHA-256 | `b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535` |
| resolved SR config hash | `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299` |
| resolved V1.5 input hash | `5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d` |
| V1.6 calibration config hash | `142f6cc34bbd343cb676e01caf1d5f9ab138a433213412c1e41607c192d67b5e` |

Final evidence groups under ignored `research/tmp_sr_v1_6`:

| Stage | ID | Path | Rows / result |
|---|---|---|---|
| development source | `9892862e0adba2ff3fb299b4918f45d666572696d8859b0ccc97ca1c367fc70e` | `source/development/9892862e0adba2ff3fb299b4918f45d666572696d8859b0ccc97ca1c367fc70e/` | 629 prefix rows; all `closed_at < 2026-01-01` |
| sealed source | `d484c2f9775b86626caa57d73a90dab3af039780cac5df392c83e376c6949edb` | `source/sealed_holdout/d484c2f9775b86626caa57d73a90dab3af039780cac5df392c83e376c6949edb/` | 811 validated parent rows |
| development selection bundle | `d797af79d5eb1c85cee8bc158ddaa8f9a51395981c1ec33090a25314bbb9fff1` | `development/d797af79d5eb1c85cee8bc158ddaa8f9a51395981c1ec33090a25314bbb9fff1/` | selection `483fcbb423568f003725653c3ca5d121df7d5fbca23842f3ece987b504d8a734` |
| holdout recommendation bundle | `5b1b5b3235941d5273602ae59146ec392218f21ceae8a6406511177fb1acb658` | `holdout/5b1b5b3235941d5273602ae59146ec392218f21ceae8a6406511177fb1acb658/` | `RETAIN_GLOBAL_14`; holdout bars not opened |

Every final manifest binds implementation commit
`3250dc47cd28e71b12593cd6f6b8247ef689a00a`, source/config identity, protocol
fields, member hashes/lengths, and a recomputable content identity. Source
capsule manifests bind their recomputed capsule identity separately.

## Development Results

The baseline had 36 completed first touches pooled across development. Every
non-14 challenger was fully evaluable under the development gates, but none
passed all gates; therefore the disposition is `RETAIN_GLOBAL_14`, not
`INSUFFICIENT_EVIDENCE`.

Fold cells are `completed outcomes / median quality in reference ATR(14) units`.

| Period | 2024 Q3 | 2024 Q4 | 2025 Q1 | 2025 Q2 | 2025 Q3 | 2025 Q4 | Pooled completed | Pooled median quality | Disposition |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 7 | 7 / -1.5167 | 8 / -0.5278 | 6 / 0.8112 | 5 / 0.9828 | 3 / 2.1127 | 4 / 0.9266 | 35 | 0.1250 | ineligible |
| 10 | 7 / -1.5167 | 8 / -0.0459 | 6 / 0.8112 | 5 / 0.9828 | 3 / 2.1127 | 4 / 0.9266 | 35 | 0.1250 | ineligible |
| 14 baseline | 7 / -1.5167 | 8 / -0.0459 | 6 / 0.8112 | 6 / -1.1546 | 3 / 0.4786 | 4 / 0.9266 | 36 | -0.0141 | baseline |
| 20 | 7 / -1.7637 | 8 / -0.0459 | 6 / 0.8112 | 6 / -1.1546 | 3 / 0.4786 | 4 / 0.6534 | 36 | -0.1850 | ineligible |
| 28 | 6 / -1.7348 | 8 / -0.0459 | 6 / 0.8112 | 6 / -1.1546 | 3 / 0.4786 | 4 / 0.6534 | 35 | -0.1531 | ineligible |

Gate results and reasons for each challenger:

| Candidate | Eligible folds | Pooled coverage | Fold-win fraction | Pooled quality delta | Invalidation delta | Density ratio | Churn delta | Censoring delta | Failed reason |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| 7 | 5 — pass | 35/36 — pass | 0.20 — fail | +0.1391 — pass | -0.0468 — pass | 1.0000 — pass | 0.0000 — pass | 0.0000 — pass | strict wins below 0.75 |
| 10 | 5 — pass | 35/36 — pass | 0.20 — fail | +0.1391 — pass | -0.0183 — pass | 1.0000 — pass | 0.0000 — pass | 0.0000 — pass | strict wins below 0.75 |
| 20 | 5 — pass | 36/36 — pass | 0.00 — fail | -0.1709 — fail | 0.0000 — pass | 1.0000 — pass | 0.0000 — pass | 0.0000 — pass | fold wins and pooled quality fail |
| 28 | 5 — pass | 35/36 — pass | 0.00 — fail | -0.1391 — fail | -0.0468 — pass | 0.9778 — pass | -0.0010 — pass | +0.0278 — pass | fold wins and pooled quality fail |

Ranking was not used to rescue any candidate because no challenger passed all
development gates. No holdout result was used to select or reject a period.

## Holdout And Recommendation

The immutable development selection was validated before the holdout command.
Because it selected no challenger, the holdout command propagated
`RETAIN_GLOBAL_14` without reading the sealed capsule or running any non-14
replay. The holdout bundle contains an explicit no-selection result and no
holdout metrics for a candidate.

No production override is proposed. `configs/sr_inputs.yaml` remains ATR(14),
and no `assets.TAOUSDT.timeframes.1d.atr.period` override was written.

## Validation Performed

- Full SR suite: **378 passed**.
- V1.6 targeted suite: **24 passed**.
- Import boundaries: **4 passed**.
- Ruff: passed for `src/libs/models/sr` and `tests/models/sr`.
- Compilation: passed for `src/libs/models/sr` and `tests/models/sr`.
- `git diff --check`: passed.
- Frozen V1.5 bundle/member/identity validation: passed.
- Duplicate-key, semantic identity, member hash/length, source split, and
  sealed-source tamper checks: passed.
- Independent ATR-prefix, common-start, candidate identity, reference-ATR,
  state-sequence, selection, and artifact-identity probes: passed.
- Two clean `prepare-source` runs: identical IDs and bytes.
- Two clean `select-development` runs: identical selection/bundle IDs and
  bytes.
- Two clean `evaluate-holdout` runs: identical recommendation/bundle IDs and
  bytes.
- No Binance/network/provider call occurred.

## Not Changed

No production configuration, SR domain behavior, detection, association,
lifecycle, replay, serialization, evaluation, ATR implementation, Binance
adapter, V1.5 baseline code, V1.5 evidence, or viewer code was changed. No
generated evidence was committed. Pre-existing `.codebase-memory` changes and
untracked plan drafts were not staged or modified.

## Risks Or Follow-Up Items

- This is one asset and one timeframe with a finite first-touch sample.
- The horizon is fixed at 10 subsequent daily bars; no costs, returns, PnL, or
  trading-readiness claim is made.
- The current evidence retains global ATR(14); no exact asset/timeframe
  override passed development gates.
- The holdout remains unopened for this no-challenger disposition. A future
  protocol that selects a challenger must open the locked holdout once and
  cannot retune against it.
- No viewer, database, optimizer framework, or V1.7 work was started.

The package is complete for independent review and is intentionally unmerged.
