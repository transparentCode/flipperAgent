---
goal: Complete Trendline Model Makeover V1 remediation without behavior drift
stage: coder-to-orchestrator
date_created: 2026-07-21
last_updated: 2026-07-21
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendline, remediation]
---

# Trendline Model Makeover V1 Remediation Handoff

## Outcome

All six remediation phases are implemented on the existing feature branch. The
canonical runtime now uses direct owner imports, tracker update orchestration is
split into explicit phases, MTF modules own their implementations, both semantic
ATR paths use the deterministic Numba kernel, and historical ablation imports are
restored as deprecated identity-preserving facades. No observed model output,
identity, serialization, configuration hash, or causal replay changed.

## Branch and worktree

- Base branch: `origin/main`
- Repository base commit: `c85a2b366133e7d7be4bc18b51bedfd793742189`
- Reviewed pre-remediation implementation: `999096449230292c903d21c498dec9ceea36e6af`
- Remediation contract commit: `e2e0f28b12bb4bd4bcd51a0d31b3be4f07ea602e`
- Feature branch: `refactor/trendline-model-makeover-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-makeover-v1`
- Final implementation commit before closeout: `ca4ec9f`
- Final branch commit: `HEAD` at the closeout commit containing this handoff
- Original checkout: clean on `main` at the repository base commit
- Push, merge, rebase, force-push, branch switch, cherry-pick: none

The worktree-local `.venv` is a symlink to
`/Users/aloobhujia/flipperAgent/.venv`. The literal `.venv` path is ignored in
addition to `.venv/`, so the documented commands run locally without committing
environment contents.

## Commit sequence

Original nine makeover commits remain intact:

1. `e890c9c` `test(trendline): lock makeover architecture boundaries`
2. `2bb7b39` `refactor(trendline): decompose canonical domain contracts`
3. `9fc89c9` `refactor(trendline): formalize scoped yaml configuration`
4. `95d2834` `refactor(trendline): modularize candidate discovery`
5. `a1950b2` `refactor(trendline): modularize tracking and interactions`
6. `23520d2` `refactor(trendline): decompose mtf and storage boundaries`
7. `dc2ebbe` `refactor(trendline): isolate regime integration ownership`
8. `2729807` `perf(trendline): add deterministic numba kernels`
9. `9990964` `docs(trendline): close canonical model makeover`

Remediation commits:

1. `e2e0f28` `docs(trendline): define makeover remediation contract`
2. `45fdb00` `refactor(trendline): enforce direct owner dependencies`
3. `3451026` `refactor(trendline): extract tracker update phases`
4. `26ac1c2` `refactor(trendline): complete mtf responsibility ownership`
5. `63df565` `perf(trendline): wire deterministic atr kernel`
6. `ca4ec9f` `fix(trendline): restore ablation compatibility`
7. `HEAD` `docs(trendline): close makeover remediation`

## Final package ownership

```text
trendline/
├── api.py
├── domain/
├── configuration/
├── discovery/
│   ├── contracts.py
│   ├── provider.py
│   ├── pivots/
│   └── fitting/
├── tracking/
│   ├── matching.py
│   ├── rails.py
│   ├── corridors.py
│   ├── ranking.py
│   └── service.py
├── interaction/
│   ├── atr.py
│   ├── observations.py
│   ├── lifecycle.py
│   ├── state.py
│   └── features.py
├── mtf/
│   ├── contracts.py
│   ├── projection.py
│   ├── freshness.py
│   ├── relations.py
│   ├── clustering.py
│   ├── composition.py
│   ├── serialization.py
│   ├── features.py
│   └── store.py
├── storage/
├── kernels/atr.py
└── optimization/ablation.py  # deprecated compatibility only
```

### Old-to-new ownership map

| Previous concentration or facade | Final owner |
| --- | --- |
| discovery result/protocol contracts in `provider.py` | `discovery/contracts.py` |
| root domain/config/storage imports inside owner packages | direct `domain`, `configuration`, `storage`, and `interaction` owners |
| monolithic `TrendlineFamilyTracker.update()` | nine phase methods with frozen phase-result records in `tracking/service.py` |
| MTF contracts and validation in `composition.py` | `mtf/contracts.py` |
| MTF family/member projection | `mtf/projection.py` |
| MTF age and freshness | `mtf/freshness.py` |
| MTF relations and intersections | `mtf/relations.py` |
| MTF clustering | `mtf/clustering.py` |
| MTF identities and primitive serialization | `mtf/serialization.py` |
| MTF feature payload | `mtf/features.py` |
| MTF latest-source store | `mtf/store.py` |
| MTF source validation and orchestration | `mtf/composition.py` |
| duplicated semantic ATR loops | shared adapter in `interaction/atr.py` and numeric kernel in `kernels/atr.py` |
| RegimeV2 ablation implementation under canonical optimization | integration ownership plus deprecated forwarding facades |

`mtf/composition.py` is 194 lines after remediation, down from 2,154. Its former
forwarding-only sibling modules now contain their responsibility implementations.
`TrendlineFamilyTracker.update()` is 54 lines, down from 325, and delegates the
confirmed-frame, prior-state, candidate, rail-association, family-lifecycle,
interaction/event, snapshot, persistence, and output phases.

## Configuration evidence

The field-policy registry still contains exactly 49 unique semantic fields. The
complete classification and allowed-scope table remains in
`configs/trendline/README.md`; its broken literal `\x60` markup is corrected.

Canonical BTCUSDT 4h resolution is unchanged:

- resolved configuration hash:
  `da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`
- MTF configuration hash:
  `d9cae516fb96eb3449c8ad684453789e0fed825bda57d0913c111b0cd6b8aa7b`

## Import-boundary evidence

AST tests prove:

- owner packages do not import transitional canonical root facades;
- `discovery/contracts.py` does not import the provider implementation;
- canonical runtime imports none of the old trendline, SR, RegimeV2, or
  trendline-Regime integration packages;
- only the two explicit deprecated optimization ablation facades may reference
  the RegimeV2 integration.

The dependency scan covers:

```text
libs.trendlines
libs.models.trendlines_old
app.trendlines
libs.models.sr
libs.models.regime_v2
libs.integrations.trendline_regime_v2
```

The final code-graph impact review identifies both semantic ATR paths as CRITICAL
direct tracker dependencies and MTF composition as a CRITICAL store dependency.
The exact replay, serialization, identity, and broad consumer suites below cover
those high-impact paths.

## Compatibility and identity evidence

- Direct canonical, root forwarding, and `trendline_family` contracts retain
  runtime object identity.
- All five historical ablation exports resolve to integration-owned identical
  objects through four surfaces: canonical package, canonical submodule,
  `trendline_family` package, and `trendline_family` submodule.
- Representative Phase-G snapshot ID remains
  `be628af8-a752-545d-9466-122df5853355`.
- Tracker phase replay compares exact serialized snapshot bytes, snapshot IDs,
  transitions, events, features, ordering, and repository writes with public
  `update()`.
- MTF tests preserve source order, projection, freshness, clustering, identities,
  serialization, and feature keys.
- Compiled and `.py_func` tracker runs produce byte-identical snapshots and equal
  feature payloads.

## Numba runtime and benchmark evidence

Both actual semantic call sites now use the same validated numeric adapter and
`kernels.atr.true_range_mean`:

- `interaction.atr.calculate_interaction_atr`
- `tracking.matching.calculate_normalization_atr`

Both apply `effective_window = min(configured_window, row_count)`, retain their
historical method strings and sample counts, and expose a non-semantic `compiled`
execution switch. Kernel inputs remain NumPy arrays and numeric scalars only.

Benchmark command:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/trendline_numba_atr.py
```

Methodology: fixed `(4096, 3)` float64 pandas fixture, window 4096, one compiled
public-path warm-up, 500 timed calls per mode, median latency, DataFrame-to-array
conversion included, and `tracemalloc` Python allocation peak recorded.

| Public path | Python p50 | Compiled warm p50 | First compiled call | Python/compiled peak | Parity |
| --- | ---: | ---: | ---: | ---: | --- |
| interaction ATR | 1,763.688 us | 39.833 us | 261.869 ms | 6,411 / 6,411 bytes | exact |
| normalization ATR | 1,745.083 us | 38.125 us | 0.058 ms | 6,451 / 6,451 bytes | exact |

The normalization first-call measurement reuses the already-compiled shared
dispatcher, so it is not a second compilation-cost measurement. `tracemalloc`
reports Python allocations, not native Numba cache or allocator memory. These
figures support only public ATR-path acceleration, not an end-to-end tracker
speedup claim. No Numba cache files are committed.

## Validation

Focused remediation evidence:

- direct owner/import phase: `21 passed`; canonical suite: `387 passed`
- tracker phase extraction: `70 passed`; canonical suite: `388 passed`
- MTF ownership: `36 passed`; canonical suite: `391 passed`
- ATR runtime: `21 passed`; canonical suite: `393 passed`
- ablation compatibility: `28 passed`; canonical suite: `394 passed`
- final identity/import/config/phase/kernel probe: `19 passed in 0.98s`
- direct public ablation import probe: passed, 5 symbols across 4 surfaces

Exact final combined command:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  -q -ra
```

Result: `415 passed in 24.31s`.

Other final checks:

- Ruff over canonical, compatibility, integration, and family-test paths: passed
- compileall over canonical, compatibility, and integrations: passed
- `git diff --check`: passed
- protected configuration hashes: exact
- representative snapshot identity: exact
- public ablation identity: exact
- compiled/Python ATR and serialized tracker parity: exact

## Files intentionally not changed

No changes were made to:

```text
src/libs/trendlines/
src/libs/models/trendlines_old/
src/app/trendlines/
src/libs/models/sr/
```

No protected research evidence, model threshold, candidate formula, lifecycle
policy, RegimeV2 policy, or application signal was changed.

## Deferred work

- Hough provider
- candidate-quality research
- new pivots, fitters, and providers
- parameter optimization
- SQLite storage
- TradingView Lightweight Charts
- end-to-end tracker profiling beyond the accepted ATR benchmark

## Residual risks

- `tracking/service.py` remains a large stateful implementation because lifecycle
  policy was intentionally not rewritten. The public update orchestration is now
  short and phase-explicit; any future extraction into separate service modules
  must repeat byte-level replay tests.
- `mtf/contracts.py` is large because it owns the full immutable MTF contract set.
  Responsibilities are no longer hidden in composition, but further contract-file
  subdivision would need another compatibility review.
- Deprecated ablation facades intentionally load the RegimeV2 integration only
  when historical optimization APIs are imported. Core runtime owner modules
  remain clean; removal requires a separately versioned breaking release.
- Benchmark results are local machine measurements and may vary by environment.

## Coder assessment

The bounded remediation acceptance criteria are met. The branch is suitable for
independent orchestrator rereview. This is not a production-readiness or research
promotion declaration.

READY_FOR_ORCHESTRATOR_REVIEW
