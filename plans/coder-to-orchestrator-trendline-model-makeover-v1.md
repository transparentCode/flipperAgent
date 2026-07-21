# Coder to Orchestrator: Trendline Model Makeover V1

## Branch and worktree

- Base branch: `origin/main`
- Base commit: `c85a2b366133e7d7be4bc18b51bedfd793742189`
- Feature branch: `refactor/trendline-model-makeover-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-makeover-v1`
- Final commit: `HEAD` after the closeout commit containing this handoff
- Original checkout: remained on `main`, clean, and at the base commit
- Push/merge/rebase/cherry-pick: none

## Commit sequence

1. `e890c9c` `test(trendline): lock makeover architecture boundaries`
2. `2bb7b39` `refactor(trendline): decompose canonical domain contracts`
3. `9fc89c9` `refactor(trendline): formalize scoped yaml configuration`
4. `95d2834` `refactor(trendline): modularize candidate discovery`
5. `a1950b2` `refactor(trendline): modularize tracking and interactions`
6. `23520d2` `refactor(trendline): decompose mtf and storage boundaries`
7. `dc2ebbe` `refactor(trendline): isolate regime integration ownership`
8. `2729807` `perf(trendline): add deterministic numba kernels`
9. `HEAD` `docs(trendline): close canonical model makeover`

## Package result

```text
trendline/
├── api.py
├── domain/{geometry,candidates,families,interactions,events,snapshots,context,serialization,identity,validation}.py
├── configuration/{contracts,field_policy,loader,resolver,derived,profiles,provenance}.py
├── discovery/{contracts,registry,provider}.py
│   ├── pivots/{contracts via package seam,fractal}.py
│   └── fitting/{contracts via package seam,pathfinding}.py
├── tracking/{matching,rails,corridors,ranking,service}.py
├── interaction/{atr,zones,observations,lifecycle,state,features}.py
├── mtf/{contracts,projection,freshness,relations,clustering,composition,serialization,features,store}.py
├── storage/{repository,serialization,memory}.py
├── kernels/{atr}.py
├── optimization/
└── research_lab/
```

Transitional root modules explicitly re-export owning objects. `libs.models.trendline_family` remains forwarding-only.

## Ownership map

| Historical path | Canonical owner |
| --- | --- |
| `contracts.py` | `domain/*` |
| `pivots.py` | `discovery/pivots/fractal.py` |
| `fitting.py` | `discovery/fitting/pathfinding.py` |
| `provider.py`, `registry.py` | `discovery/provider.py`, `discovery/registry.py` |
| `matching.py`, `rails.py`, `corridors.py`, `ranking.py`, `tracker.py` | `tracking/*` |
| `interactions.py`, `event_lifecycle.py`, `events.py`, `features.py` | `interaction/*` |
| `mtf.py` | `mtf/*` with orchestration in `mtf/composition.py` |
| repository serialization | `storage/serialization.py` |
| Regime feature ablation | `libs.integrations.trendline_regime_v2.ablation` |

## Configuration classification

The machine-readable registry contains exactly 49 fields, with duplicate/missing/unknown ownership checks at import. The complete field-by-field table is in `configs/trendline/README.md`.

| Classification | Fields / ownership |
| --- | --- |
| Global | providers, fitter, quality/matching policy, weights, confidence decay, representative and MTF composition policies |
| Timeframe | lookback/warm-up, fractal windows, lifecycle/event bar horizons, ATR windows, freshness/intersection horizons |
| Asset | birth threshold and minimum tick-zone policy; compatibility scopes are explicit |
| Asset-timeframe | distance/tolerance fields with existing pair-specific evidence |
| Derived | timeframe seconds, minimum warm-up, maximum historical horizon; not YAML-writable |
| Runtime/non-semantic | no active fields; execution backend flags remain outside semantic hashes |
| Invariant | enum values, identity schema, UTC, ordering, lifecycle transition table, normalization definitions |

Scope validation rejects disallowed placement, unknown fields, incomplete canonical YAML, runtime/derived injection, and unresolved asset/timeframe conflicts. Existing precedence and provenance strings are unchanged.

## Identity and compatibility evidence

- Old/root/new domain, discovery, and compatibility imports resolve to identical runtime objects.
- Historical pickle fixture loads.
- Candidate fixture hashes, provider identity, field/default order, enum values, JSON round trips, and serialized snapshots pass unchanged.
- Representative Phase-G snapshot ID remains `be628af8-a752-545d-9466-122df5853355`.
- BTCUSDT 4h resolved config hash remains `da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f`.
- MTF config hash remains `d9cae516fb96eb3449c8ad684453789e0fed825bda57d0913c111b0cd6b8aa7b`.
- Replay coverage includes abstention, birth, continuation, dormancy, reactivation, expiry, break confirmation, retest, failed break, role reversal, rails, MTF, and causal repository reads.

## Import boundaries

AST guards and direct scans report zero canonical imports from:

```text
libs.trendlines
libs.models.trendlines_old
app.trendlines
libs.models.sr
libs.models.regime_v2
libs.integrations.trendline_regime_v2
```

Regime integration imports canonical seams in the permitted direction.

## Numba evidence

Added `kernels.atr.true_range_mean` with `@njit(cache=True, nogil=True)`. It accepts only NumPy arrays and an integer scalar. The validating wrapper rejects dimensional mismatch, unequal lengths, invalid windows, NaN, and infinity. Tests cover compiled versus `.py_func`, minimum/empty input, repeat determinism, and causal-prefix parity. No `fastmath`, parallel reductions, randomness, or cache files are used.

Fixed benchmark: three float64 arrays, 4,096 rows (96 KiB input), trailing window 4,096, one compiled warm-up, 2,000 timed repetitions:

| Python p50 | Compiled warm p50 | Cold compile/call | Parity | Memory observation |
| --- | --- | --- | --- | --- |
| 1,761.979 µs | 4.291 µs | 76.732 ms | exact | fixed input arrays; no output array allocation |

The kernel remains behind an explicit numeric wrapper and does not alter the current semantic model path.

## Validation

Baseline before edits:

- canonical family suite: `377 passed in 22.05s`
- canonical consumers: `21 passed in 2.75s`

Final required combined pytest command: `406 passed in 26.27s`.

Additional final checks:

- Ruff over canonical, compatibility, configuration/regime integrations, and family tests: passed
- `compileall` over canonical, compatibility, and integrations: passed
- `git diff --check`: passed
- branch/worktree gate: passed
- original checkout clean/on `main`: passed

## Intentionally unchanged and deferred

No changes were made to `src/libs/trendlines`, `src/libs/models/trendlines_old`, `src/app/trendlines`, `src/libs/models/sr`, protected research evidence, model thresholds/formulas, RegimeV2 policy, or application signals. Hough, candidate-quality research, SQLite, TVLC, new providers, and parameter optimization remain deferred.

## Residual risks

- MTF responsibility modules expose stable seams while the behavior-heavy orchestration remains concentrated in `mtf/composition.py`; later internal extraction must repeat byte-identity replay.
- Only the measured ATR kernel was accepted. Other profiling candidates remain Python until independently benchmarked.
- Transitional root forwarders remain public compatibility debt and should be removed only in a separately versioned release.

READY_FOR_ORCHESTRATOR_REVIEW
