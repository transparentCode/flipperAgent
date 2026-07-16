---
goal: Review SR-V1.7 frozen-config multi-asset 1d cohort-readiness implementation and development evidence
stage: coder-to-review
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Quant Coder
status: Review Ready
tags: [handoff, quant, sr, cohort-readiness, multi-asset, baseline, evidence]
source_agent: Coder Agent
target_agent: Quant Reviewer
base_commit: 72072d2076af379d807cdbd390bb73ff82fe5f8c
source_branch: feature/sr-v1.6-atr-calibration
target_branch: feature/sr-v1.7-cohort-readiness
implementation_commits: [42d62f048da1afff6b2b250472fd7c8ab6030279, 1d9b34145aae41b2b3520d97926514e65270b4e2, be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2]
handoff_commit: ab0abad13be92a9252b6d7fd5709723cac76547d
---

# Coder To Reviewer: SR-V1.7 Cohort Readiness v1

## Verdict and scope

Status is `Review Ready`. This is a development-only descriptive cohort trial;
it does not authorize a config edit, parameter sensitivity study, holdout use,
production integration, merge, or V1.8.

The implementation starts at the approved V1.6 commit
`72072d2076af379d807cdbd390bb73ff82fe5f8c` and remains on
`feature/sr-v1.7-cohort-readiness`. The branch is unmerged.

The implementation is additive under
`src/libs/models/sr/scripts/cohort_readiness/`, with mirrored tests and the
approved trial YAML only. `configs/sr.yaml`, `configs/sr_inputs.yaml`, all SR
core packages, the Binance adapter, and V1.5/V1.6 implementation paths are
unchanged.

Implementation commits:

- `42d62f048da1afff6b2b250472fd7c8ab6030279` — V1.7 package, tests, and trial YAML.
- `1d9b34145aae41b2b3520d97926514e65270b4e2` — accepts the approved adapter’s documented extra `taker_buy_base_asset_volume` column while retaining required OHLCV validation; adds regression coverage.
- `be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2` — binds per-asset resolved SR/input field provenance in source and evaluation manifests.

One pre-correction source attempt under `1d9b341` made a bounded BTC request,
then rejected the valid seven-column adapter result before publication. No
evidence from that attempt is used. The final source evidence below was
prepared once under `be6459a`, with the required `0/1/1/1` provider-call
record.

## Frozen protocol

The committed trial config is
`configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml` with config hash
`370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7`.

The canonical cohort is Binance USD-M `1d`, in this exact order:

`TAOUSDT`, `BTCUSDT`, `ETHUSDT`, `SOLUSDT`.

The eight SR parameters remain frozen at the approved global defaults:

| Parameter | Value |
| --- | ---: |
| `detection.pivot_span_bars` | 5 |
| `detection.zone_half_width_atr` | 0.25 |
| `association.merge_distance_atr` | 0.50 |
| `lifecycle.touch_tolerance_atr` | 0.25 |
| `lifecycle.break_buffer_atr` | 0.25 |
| `lifecycle.break_confirm_closes` | 2 |
| `lifecycle.max_age_bars` | 50 |
| `runtime.max_active_zones` | 8 |

The resolved SR hashes are `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299`
for TAO and the per-asset values in the source table below. The resolved input
config is Wilder/RMA ATR with SMA seed, period 14, common start period 28;
the approved TAO input hash is
`5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d`.
All resolved SR and input field-provenance entries are `defaults` for all four
assets, and those tables are directly bound into both artifact manifests.

The outcome protocol is start offset `1`, horizon `10`, and descriptive
first-touch favorable/adverse/quality excursion in reference ATR(14). The
source window is half-open:

`open_time >= 2024-04-11T00:00:00Z` and
`open_time < 2025-12-31T00:00:00Z`, with causal `closed_at <=` the latter
boundary. Provider requests use `startTime=1712793600000` and
`endTime=1767139199999` (`requested_until_ms - 1`). The shared daily-grid hash
is `d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8`.

The six half-open folds are:

| Fold | Start | End |
| --- | --- | --- |
| `2024_q3` | 2024-07-01 | 2024-10-01 |
| `2024_q4` | 2024-10-01 | 2025-01-01 |
| `2025_q1` | 2025-01-01 | 2025-04-01 |
| `2025_q2` | 2025-04-01 | 2025-07-01 |
| `2025_q3` | 2025-07-01 | 2025-10-01 |
| `2025_q4` | 2025-10-01 | 2026-01-01 |

State is continuous across folds within an asset and independent between
assets. There are no candidates, tuning, ranking, selection, or holdout/sealed
source paths.

## Source evidence

The final source bundle is:

`research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`

Bundle ID: `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`.
It binds implementation commit `be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2`,
the V1.7 config hash above, all four resolved SR/input hash pairs, complete
field provenance, request metadata, bars hashes, grid hash, and member hashes.

| Asset | Source ID | Source bars SHA-256 | Bundle member SHA-256 | Rows | Provider calls |
| --- | --- | --- | --- | ---: | ---: |
| TAOUSDT | `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120` | `703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163` | `e879ff30c3a22cc8ad9c911c21354838c32893de9c48b4ce7abfdf7469427fa1` | 629 | 0 |
| BTCUSDT | `63a803b9ad2d896527bad135d78f84be9b444e8296c69becd8fc0ad8602dc9c2` | `a7f429ef383301c4232ff7cd43f2de1e4485f756a5345173a33859b44824b9f9` | `63fdbbcd98002b908f929767535995533dda078777616480ccad09b63200e64c` | 629 | 1 |
| ETHUSDT | `3c525aca69ebba5931f7f6da2648ae79d2ce35315edab47ba7bea97f1cd32837` | `4f6a898a74cc0ea1c10f6f5d166c6a2c9d3990458af5cf0b876af6419c3f6231` | `a3c8a01b8a452d153387ade4ede02d2ff734eb3bdefdb4c8845dec2441fff6e7` | 629 | 1 |
| SOLUSDT | `2fc22c565f84fbdac4f8607ba7ea43432f5e6cd4c5073e8f29a320513d404685` | `810b973c78b632b839e992002649c5e73865e75b8750701cf058336997c8ba82` | `eba04d295120bfcd4fa4b9bee990c2a59354412e26d7783ed6f76bc5ae9ae57b` | 629 | 1 |

Resolved per-asset hashes are:

- TAOUSDT — SR `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299`; input `5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d`.
- BTCUSDT — SR `7f2d9367983598d6b3cb153ff593adab213ed9bac0bc8441fb72a65e9d555e3f`; input `c99298cac6ef7ae783833116a80e4d5edd28d81fabc2b2bb3e8bf699d6068241`.
- ETHUSDT — SR `f2a5d88d933aae6bd3a3fdd3a7baa5f2cc9557a0776e5bae0fe3a3d620ac4f38`; input `fcc248cd2a2f0dd2684d4cb7fffd3010243dd66adf40d0b632dc17f05282cfa8`.
- SOLUSDT — SR `f4d244b3503c4f0f308b506131351d44d3541452ab940384ce37c88e70991c6`; input `3ecd452e590788e2fe2251a46c52517ae5de52a7dd7f28c0a752d476cf187dc8`.

All assets run from `2024-04-11T00:00:00Z` through causal close
`2025-12-31T00:00:00Z`. TAOUSDT is the exact approved V1.6 development
capsule, source bundle `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`,
with frozen capsule member hash
`b9ed3cf63e87fd3c413843f6bbc88d647eb051131cac6524af079fc1458c2ff3`.

The source bundle was loaded and validated twice without provider access. The
validator rejects a fully rehashed mutation of the frozen TAOUSDT bar because
the approved source identity and bars hash are fixed by the trial config.

## Evaluation evidence

The final evaluation bundle is:

`research/tmp_sr_v1_7/evaluation/4440028682097fec6519708c13c29e6d71292a9f7ecd6da60913d1f848aa1dfc`

Bundle ID: `4440028682097fec6519708c13c29e6d71292a9f7ecd6da60913d1f848aa1dfc`.
Evaluation ID:
`949f732489b457797942ed0e80376e9f13e7c56babdc5237b5d95890124dc0eb`.
The evaluation member SHA-256 is
`8237e5d6b84f4945da6dbfc141e0b03e27e817cfa3cf42eca81533c95a1f6a65`.
The validator recomputes all four replays, traces, metrics, aggregation, gates,
and disposition from the validated source bundle and accepts the exact payload.

### TAOUSDT V1.6 parity

The independent parity probe and the mirrored regression both returned:

- exact `CandidateMetrics.to_payload()` equality;
- exact trace ID equality: `5e58eeb1e3aef84a096d348779d92d76268da619ad4445dee397d56fe688047f`;
- 36 completed pooled first-touch outcomes.

### Pooled per-asset metrics

`S/R` in the completed-touch column is support/resistance completed outcomes.
The created support/resistance counts in the final column are complete-replay
created-zone side counts; pooled window metrics remain the authoritative fold
and pooled accounting.

| Asset | Eligible bars | Pooled created zones | Terminal / churn | Total / completed / right-censored | S/R completed | Invalidated / rate | Median favorable / adverse / quality ATR | Created S/R zones |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| TAOUSDT | 549 | 45 | 43 / 0.955556 | 36 / 36 / 0 | 19 / 17 | 13 / 0.361111 | 1.134091 / 1.500195 / -0.014070 | 26 / 24 |
| BTCUSDT | 549 | 57 | 52 / 0.912281 | 42 / 41 / 1 | 19 / 22 | 18 / 0.439024 | 1.374830 / 1.834854 / -0.416910 | 30 / 31 |
| ETHUSDT | 549 | 57 | 52 / 0.912281 | 43 / 42 / 1 | 28 / 14 | 16 / 0.380952 | 1.618336 / 1.065582 / 0.613687 | 36 / 27 |
| SOLUSDT | 549 | 49 | 45 / 0.918367 | 35 / 34 / 1 | 15 / 19 | 14 / 0.411765 | 1.162076 / 1.596270 / -0.483164 | 26 / 28 |

Per-asset event accounting (`CREATED`, `TOUCHED`, `BREACH_STARTED`,
`FALSE_BREAKOUT`, `BREAK_CONFIRMED`, `EXPIRED`, observed total) is:

| Asset | Created | Touched | Breach started | False breakout | Break confirmed | Expired | Observed total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TAOUSDT | 50 | 239 | 31 | 10 | 21 | 27 | 378 |
| BTCUSDT | 61 | 252 | 39 | 8 | 31 | 25 | 416 |
| ETHUSDT | 63 | 223 | 38 | 6 | 32 | 26 | 388 |
| SOLUSDT | 54 | 257 | 43 | 18 | 25 | 25 | 422 |

### Per-fold metrics

Columns are `eligible bars | created zones | completed S/R | total
outcomes/completed/right-censored | invalidated | median quality ATR |
terminal/churn`.

| Asset | Fold | Metrics |
| --- | --- | --- |
| TAOUSDT | 2024_q3 | `92; 8; 4/3; 7/7/0; 4; -1.516684; 6/0.750000` |
| TAOUSDT | 2024_q4 | `92; 9; 5/3; 8/8/0; 3; -0.045947; 6/0.666667` |
| TAOUSDT | 2025_q1 | `90; 7; 3/3; 7/6/1; 2; 0.811224; 5/0.714286` |
| TAOUSDT | 2025_q2 | `91; 9; 2/4; 6/6/0; 4; -1.154607; 6/0.666667` |
| TAOUSDT | 2025_q3 | `92; 5; 1/2; 4/3/1; 0; 0.478649; 2/0.400000` |
| TAOUSDT | 2025_q4 | `92; 7; 2/2; 4/4/0; 0; 0.926572; 5/0.714286` |
| BTCUSDT | 2024_q3 | `92; 9; 3/3; 6/6/0; 3; -0.989925; 7/0.777778` |
| BTCUSDT | 2024_q4 | `92; 11; 2/5; 7/7/0; 3; -0.157077; 8/0.727273` |
| BTCUSDT | 2025_q1 | `90; 10; 5/4; 9/9/0; 4; -0.416910; 6/0.600000` |
| BTCUSDT | 2025_q2 | `91; 10; 1/6; 8/7/1; 3; -0.773948; 5/0.500000` |
| BTCUSDT | 2025_q3 | `92; 7; 2/2; 5/4/1; 2; -0.186394; 5/0.714286` |
| BTCUSDT | 2025_q4 | `92; 10; 4/2; 7/6/1; 3; 1.153128; 5/0.500000` |
| ETHUSDT | 2024_q3 | `92; 9; 7/3; 10/10/0; 6; -2.125228; 7/0.777778` |
| ETHUSDT | 2024_q4 | `92; 8; 5/4; 9/9/0; 2; 1.285197; 6/0.750000` |
| ETHUSDT | 2025_q1 | `90; 12; 4/2; 7/6/1; 2; -1.226608; 8/0.666667` |
| ETHUSDT | 2025_q2 | `91; 10; 3/3; 6/6/0; 3; -0.913900; 6/0.600000` |
| ETHUSDT | 2025_q3 | `92; 7; 1/2; 4/3/1; 0; 2.012151; 4/0.571429` |
| ETHUSDT | 2025_q4 | `92; 11; 6/0; 7/6/1; 2; 0.960248; 6/0.545455` |
| SOLUSDT | 2024_q3 | `92; 10; 3/5; 8/8/0; 4; -0.801594; 7/0.700000` |
| SOLUSDT | 2024_q4 | `92; 10; 3/3; 7/6/1; 4; -1.623725; 7/0.700000` |
| SOLUSDT | 2025_q1 | `90; 8; 1/2; 4/3/1; 1; -0.425347; 3/0.375000` |
| SOLUSDT | 2025_q2 | `91; 7; 3/3; 6/6/0; 2; -0.648757; 4/0.571429` |
| SOLUSDT | 2025_q3 | `92; 6; 0/4; 4/4/0; 3; -2.481916; 4/0.666667` |
| SOLUSDT | 2025_q4 | `92; 8; 4/1; 6/5/1; 0; 0.482343; 4/0.500000` |

### Cohort aggregation

The micro view concatenates outcome rows and recomputes rates from summed
denominators. The macro view is the unweighted median/minimum/maximum across
the four pooled asset metrics; it is not an average of per-asset medians.

| Metric | Micro | Macro median | Macro minimum | Macro maximum |
| --- | ---: | ---: | ---: | ---: |
| Eligible model bars | 2196 | 549 | 549 | 549 |
| Created zones | 208 | 53 | 45 | 57 |
| Terminal cohort count | 192 | 48.5 | 43 | 52 |
| Churn rate | 0.923077 | 0.915324 | 0.912281 | 0.955556 |
| Total outcomes | 156 | 39 | 35 | 43 |
| Completed outcomes | 153 | 38.5 | 34 | 42 |
| Right-censored outcomes | 3 | 1 | 0 | 1 |
| Right-censoring rate | 0.019231 | 0.023533 | 0 | 0.028571 |
| Support/resistance completed | 81 / 72 | 19 / 18 | 15 / 14 | 28 / 22 |
| Invalidated completed outcomes | 61 | 15 | 13 | 18 |
| Invalidation rate | 0.398693 | 0.396359 | 0.361111 | 0.439024 |
| Median favorable ATR | 1.283210 | 1.268453 | 1.134091 | 1.618336 |
| Median adverse ATR | 1.551609 | 1.548233 | 1.065582 | 1.834854 |
| Median quality ATR | -0.216888 | -0.215490 | -0.483164 | 0.613687 |
| Zone density per 100 bars | 9.471766 | 9.653916 | 8.196721 | 10.382513 |

Micro event accounting is `created=228`, `touched=971`,
`breach_started=151`, `false_breakout=42`, `break_confirmed=109`,
`expired=103`, `observed_event_count=1604`; the six event counts sum exactly to
the observed total.

## Readiness gates and disposition

All 20 structural gates pass: every asset has non-zero created zones, support
zones, resistance zones, first touches, and terminal cohort events.

The sample gates are:

| Asset | Eligible folds | Completed development outcomes | Failed gate |
| --- | ---: | ---: | --- |
| TAOUSDT | 5 | 36 | `2025_q3` has 3 completed first touches (< 4) |
| BTCUSDT | 6 | 41 | none |
| ETHUSDT | 5 | 42 | `2025_q3` has 3 completed first touches (< 4) |
| SOLUSDT | 5 | 34 | `2025_q1` has 3 completed first touches (< 4) |

All four assets meet the minimum four eligible folds and 24 development
outcomes. Three fold-level sample gates fail, so the exact ordered disposition
is:

`INSUFFICIENT_EVIDENCE`

This is a sample-coverage result, not a quality or profitability judgment.

## Determinism, causality, and adversarial validation

- The two CLI evaluation runs against source bundle `6b5a0a…` returned the same evaluation bundle ID `4440028682…` and evaluation ID `949f7324…`.
- A further network-free local rerun was compared byte-for-byte against the existing bundle: `evaluation.json` SHA `8237e5d6…` and `manifest.json` SHA `2911bc08…` were unchanged.
- Two source-bundle loads passed with the same source ID and per-asset provider-call counts.
- Evaluation with the provider constructor replaced by a failing spy completed twice without reaching the provider path.
- Independent TAOUSDT replay matched V1.6 metrics and trace exactly.
- Checkpoint encode/decode split-resume parity matched uninterrupted replay for all four assets: final states and suffix snapshots were equal.
- Mutating only the final source bar left every earlier snapshot equal for all four assets.
- A fully rehashed frozen TAOUSDT source-bar mutation was rejected against the approved source identity.
- Existing artifact tests reject duplicate JSON keys, member/hash tampering, protocol mutation, and fully rehashed evaluation disposition tampering through semantic recomputation.

## Validation

| Check | Result |
| --- | --- |
| V1.7 targeted suite | 24 passed |
| Full SR suite | 417 passed |
| Import-boundary tests | 4 passed |
| Ruff | passed using system `ruff` (`.venv/bin/ruff` is unavailable) |
| Compileall | passed |
| `git diff --check` | passed |
| Final source validator | passed |
| Final evaluation validator | passed; `INSUFFICIENT_EVIDENCE` |

## Scope and residual limitations

No production SR config, input config, model behavior, provider adapter,
runtime integration, viewer, database, holdout/sealed capsule, tuning,
selection, feature, PnL, or V1.8 work was performed. Generated evidence under
`research/tmp_sr_v1_7/` is untracked and not part of any commit.

The pre-existing `.codebase-memory` working-tree entries and unrelated plan
drafts remain excluded from all commits. The protected-path diff from the
approved base contains only the committed V1.7 YAML, the new cohort-readiness
package, and its mirrored tests.

The evidence covers one fixed daily development window and descriptive zone
behavior only. The three failed fold sample gates mean no later parameter
sensitivity study is authorized by this result. Any future holdout must be
defined and opened under a separately approved protocol.

This handoff is documentation-only and is the final action on the branch until
review feedback is issued. No merge was performed.
