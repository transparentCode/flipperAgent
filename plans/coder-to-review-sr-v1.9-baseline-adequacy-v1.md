---
goal: Deliver the SR-V1.9 TAOUSDT baseline-adequacy implementation and deterministic development evidence for review
stage: coder-to-review
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Codex
status: Ready
tags: [handoff, quant, sr, v1.9, baseline-adequacy, null-benchmark, taousdt]
source_agent: Codex quant-coder
target_agent: Quant Review / Orchestrator
---

# SR-V1.9 Baseline Adequacy

## Scope Executed

Implemented the approved development-only TAOUSDT/1d baseline-versus-naive-null
study on:

- branch: `feature/sr-v1.9-baseline-adequacy`;
- approved V1.8 base: `0fc43a19ab696811e8c7e214c56f5351e50c4e1f`;
- authorization handoff commit: `e0fb98749c1ab89649f4ffb4fc88c60b8494f816`;
- implementation commit: `542faeb0991617ec38a3f7cc13551a26c0f567f0`.

The branch remains unmerged. The approved handoff was committed before the
implementation. Generated evidence remains untracked.

The study consumes the validated frozen V1.7 source/evaluation and V1.8 study
directly. It does not contact Binance, prepare a source capsule, access or
score a holdout, change production SR behavior, or promote a result.

## Changes Made

Added exactly one V1.9 trial configuration and one additive research package:

- `configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml`;
- `src/libs/models/sr/scripts/baseline_adequacy/` — strict config loading,
  immutable contracts, causal control construction, metrics/decision logic,
  frozen-input replay/parity, deterministic artifacts, and `evaluate`/
  `validate` CLI;
- `tests/models/sr/scripts/baseline_adequacy/` — configuration, contract,
  control, metrics, runner, artifact, and import-boundary coverage.

The implementation enforces:

- the frozen six-fold UTC protocol and exact TAOUSDT baseline parameters;
- previous-snapshot visibility with only ACTIVE/BREACH_PENDING zones;
- inclusive side-independent zone intersection;
- deterministic eligibility precedence and two controls per eligible bar in
  SUPPORT, RESISTANCE order;
- same-fold/same-side null medians and per-real-outcome excess quality;
- exact sample/comparability/quality gate semantics and disposition precedence;
- exact 13-gate names/categories/operators/thresholds with value-derived
  pass flags and diagnostic-only fold gates;
- explicitly separated approved-pooled, fold-local, and comparable-mapped
  populations;
- duplicate-safe canonical JSON, semantic recomputation, and identity binding;
- manifest implementation identity defaults that remain valid after later docs
  commits while retaining explicit mismatch rejection;
- no provider, network, source-preparation, database, viewer, production, or
  holdout import path.

## Frozen Inputs and Parity

| Input | Identity |
|---|---|
| V1.7 source bundle | `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9` |
| TAOUSDT source member | `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120` |
| V1.7 evaluation bundle | `824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d` |
| V1.7 evaluation ID | `49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d` |
| V1.8 study bundle | `b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941` |
| V1.8 study ID | `2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954` |
| V1.8 disposition | `RETAIN_BASELINE_GEOMETRY` |
| Baseline candidate | `37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c` |
| Production SR config hash | `cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299` |
| Frozen input config hash | `5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d` |

Baseline parity passed before controls. The exact replay comparison covers
source/config identities, aligned model bars, ATR references, state,
snapshots, visibility, events, accounting, first-touch outcomes, censoring,
and economic aggregates.

## Final Evidence

The evaluation command was run twice at implementation commit
`542faeb0991617ec38a3f7cc13551a26c0f567f0`:

```text
PYTHONPATH=src .venv/bin/python -m libs.models.sr.scripts.baseline_adequacy.cli evaluate --config configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml
```

Both runs produced identical IDs, member bytes, metrics, gates, and
disposition:

| Evidence field | Value |
|---|---|
| Bundle ID | `12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6` |
| Study ID | `ed19698fec505e2e8cf1057c41336da7c0720bcf412530244139e5c523f12c9f` |
| Disposition | `BASELINE_NOT_BETTER_THAN_NAIVE_NULL` |
| Evidence path | `research/tmp_sr_v1_9/evaluation/12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6` |
| Manifest bytes | `10528` |
| Manifest SHA-256 | `5e0942b7c47d1cb31aae93a1b676abf1eafb46592453ccb357801fa59ad1c9d3` |
| `study.json` bytes | `857146` |
| `study.json` SHA-256 | `fe80a2933b7f0ef266bbc43756e9a043515f153d6af64b50660ebe832b9c8abf` |
| Manifest implementation commit | `542faeb0991617ec38a3f7cc13551a26c0f567f0` |
| Manifest source ID | `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120` |

Final CLI validation passed:

```text
PYTHONPATH=src .venv/bin/python -m libs.models.sr.scripts.baseline_adequacy.cli validate --config configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml --bundle research/tmp_sr_v1_9/evaluation/12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6
```

Named outcome populations:

| Population | Total | Completed | Right-censored | Folds | Median quality |
|---|---:|---:|---:|---:|---:|
| Approved pooled | 36 | 36 | 0 | 6 | `-0.014070405071082426` |
| Fold-local | 36 | 34 | 2 | 6 | `0.1807362526958346` |
| Comparable mapped | 31 | 31 | 0 | 5 | `0.12499422337239618` |

Fold-local same-fold comparison and all promotion gates remain unchanged;
population labels now prevent pooled and fold-local audit values from being
conflated.

### Decision gates

| Gate | Value | Threshold | Result |
|---|---:|---:|---|
| Completed mapped real outcomes | 31 | >= 24 | pass |
| Comparable folds | 5 | >= 4 | pass |
| Minimum real outcomes per comparable fold | 4 | >= 4 | pass |
| Minimum controls per side per comparable fold | 35 | >= 4 | pass |
| Pooled median excess quality | 0.026200435413100243 | >= 0.10 | fail |
| Positive comparable-fold fraction | 0.4 | >= 0.60 | fail |
| Worst comparable-fold excess | -1.1546071281136923 | >= -0.10 | fail |

The failed quality gates produce `BASELINE_NOT_BETTER_THAN_NAIVE_NULL`; they do
not authorize parameter changes or holdout access.

Control accounting:

- 601 anchors considered;
- 323 eligible;
- rejected: 1 no previous snapshot, 51 outside/warmup, 0 invalid ATR,
  189 visible-zone intersections, 37 incomplete same-fold horizons;
- six fold completed real counts: `7, 8, 6, 6, 3, 4`;
- five folds comparable; `2025_q3` is diagnostic-only because it has three
  completed real outcomes;
- approved pooled population: 36 total, 36 completed, 0 right-censored;
- fold-local population: 36 total, 34 completed, 2 right-censored;
- comparable mapped population: 31 completed across five comparable folds.

## Blast Radius Considered

The dependency direction is additive:

```text
baseline_adequacy -> frozen V1.7/V1.8 loaders and replay -> approved SR core
```

No existing production symbol was changed. The new runner has no provider,
network, source-preparation, holdout, database, viewer, or execution path.
The protected SR domain/config/replay/lifecycle/detection/association,
provider, viewer, and holdout surfaces are unchanged.

Pre-existing user-owned worktree state was preserved and excluded from commits:

- modified `.codebase-memory/artifact.json`;
- deleted `.codebase-memory/graph.db.zst`;
- historical untracked plan drafts.

## Validation Performed

| Check | Result |
|---|---|
| V1.9 focused suite | 27 passed |
| Complete `tests/models/sr` suite | 499 passed in 497.06s |
| V1.9 import boundary test | 1 passed |
| Ruff on V1.9 source/tests | passed (`ruff 0.15.20`) |
| Python compilation | passed |
| Final CLI semantic validation | passed |
| Two evaluation runs | identical IDs, member bytes, metrics, gates, and disposition |

The focused tests include strict YAML/config mutation, contract invariants,
causal control eligibility, formula parity, fold accounting, metric gates,
provider/network spies, replay/parity, artifact recomputation, duplicate-key
rejection, and import allowlist checks. The complete SR run includes the
existing V1.7/V1.8 and protected SR suites.

## Not Changed

- no merge;
- no Binance/provider call;
- no new source or holdout capsule;
- no holdout evaluation or scoring;
- no production SR configuration or model behavior;
- no `configs/sr.yaml` or `configs/sr_inputs.yaml` change;
- no V1.7/V1.8 evidence or handoff rewrite;
- no generated evidence staged or committed.

## Risks or Follow-up Items

V1.9 now persists approved-pooled and fold-local populations separately. The
approved pooled baseline remains 36 completed / 0 censored with median
`-0.014070405071082426`; fold-local same-fold accounting remains 36 total,
34 completed, and 2 right-censored. Comparable mapping remains 31 completed
outcomes across five comparable folds. No values were imputed.

This is a development adequacy result for one asset/timeframe and one
pre-registered naive null. It is not profitability, generalization,
production-readiness, parameter-promotion, or holdout evidence. The package is
complete for review without guessing; no V1.10 or merge action is implied.
