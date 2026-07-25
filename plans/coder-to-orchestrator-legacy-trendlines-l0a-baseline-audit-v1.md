# Legacy Trendlines Phase L0-A
## Baseline Inventory and Static Risk Audit

Audit scope: pinned canonical package src/libs/trendlines/. Read-only audit.
No production code, tests, configuration, existing plan, or artifact changed.

## 1. Disposition

Worktree preconditions passed. Canonical package identity is clear. Static
inventory, entry-point map, component map, causal-coverage audit, side-effect
audit, and frozen-data inventory are complete.

Full canonical-package validation is blocked before test execution: mandated
.venv/bin/python does not exist, and fallback system Python lacks core package
dependencies (numpy, pandas, yaml). Therefore this handoff does not claim the
historical 271 passed, 1 failed result from
plans/trendlines-model-context-map.md:614-617 as current evidence.

## 2. Worktree and provenance

| Field | Result | Evidence |
|---|---|---|
| Branch | research/legacy-trendlines-quality-stability-v1 | git branch --show-current |
| HEAD | 2e12b9e2dbed8c7e761714adb80ee788bbf01d78 | git rev-parse HEAD |
| Worktree | /Users/aloobhujia/flipperAgent-wt-legacy-trendlines | git worktree list --porcelain |
| Preflight status | clean | git status --short --untracked-files=all before audit |
| Canonical tracked files | 147 | git ls-tree -r --name-only HEAD -- src/libs/trendlines | wc -l |
| Archive tracked files | 143 | git ls-tree -r --name-only HEAD -- src/libs/models/trendlines_old | wc -l |
| Canonical existence at pinned commit | confirmed | git ls-tree -d --name-only HEAD -- src/libs/trendlines |
| Archive existence at pinned commit | confirmed | git ls-tree -d --name-only HEAD -- src/libs/models/trendlines_old |
| Shim existence at pinned commit | confirmed | git ls-tree -d --name-only HEAD -- src/app/trendlines |

git worktree list --porcelain showed current worktree plus separate
/Users/aloobhujia/flipperAgent; no branch, merge, rebase, cherry-pick, or
other-worktree mutation was performed.

## 3. Applicable instructions

- /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/AGENTS.md: repository
  policy; root role is orchestrator; coder scope is bounded implementation;
  this phase explicitly overrides implementation with audit-only scope.
- No nested AGENTS.md found by rg --files -g AGENTS.md.
- .agents/skills/mcp-tiered-code-intelligence/SKILL.md and
  .agents/skills/codebase-memory-exploring/SKILL.md were read. Code discovery
  used codebase-memory graph tools first; text search was used for literals,
  configs, docs, tests, and non-code inventory.
- Allowed write scope: this handoff only. Temporary code-graph tool settings
  added to .codex/config.toml were restored exactly; final status contains no
  configuration change.

## 4. Canonical-package identity

src/libs/trendlines/ is canonical. Its __init__.py exports contracts, registry
builders, pipeline functions, and facade functions
(src/libs/trendlines/__init__.py:1-54).

src/app/trendlines/__init__.py:5-8 sets:

~~~
_TRENDLINES_ROOT = Path(__file__).resolve().parents[2] / "libs" / "trendlines"
__path__ = [str(_TRENDLINES_ROOT), *[p for p in globals().get("__path__", [])]]
~~~

Consequently app.trendlines.contracts, app.trendlines.pivots.*,
app.trendlines.fitting.*, app.trendlines.pipeline.*, and app.trendlines.api
resolve through the shim package path to physical modules under
src/libs/trendlines/. src/app/trendlines/__init__.py:10-25 then re-exports the
canonical public surface. src/libs/trendlines/api.py is the physical API
implementation; no src/app/trendlines/api.py exists.

src/libs/models/trendlines_old/ is archive/duplicate scope, not canonical runtime
scope. Its files mostly import app.trendlines.*, so it is not an independent
runtime package. Static scan found duplicate definitions for Ray,
QualityMetrics, BoundaryResult, boundary policy classes,
INTERACTION_DIRECTION, interaction_direction, decluster_touch_indices,
trendline_to_boundary_ray, and build_boundary_result_from_trendline_result.
This matches the AST test contract in
src/libs/trendlines/tests/test_import_boundaries.py:342-350 and the archive
report in plans/trendlines-old-file-by-file-context.md:86-105.

## 5. Existing-document accuracy

| Document | Claims still accurate | Claims stale or inaccurate | Stabilization omissions |
|---|---|---|---|
| plans/trendlines-model-context-map.md | Canonical/archive/shim split; extraction -> fitting -> boundary -> signal flow; optimizer and RegimeV2 prefer ensemble; facade defaults pathfinding. Current code: api.py:76-345, registry/registry.py:11-13. | 271 passed, 1 failed at lines 614-617 is historical, not current baseline. “Tests mostly pass” cannot be revalidated because imports fail in current environment. | No prefix replay, suffix perturbation, checkpoint geometry, output-hash, repeated-RANSAC, RDP-revision, or side-effect matrix. |
| plans/trendlines-file-by-file-context.md | Registry, active four-fitter model, archive warning, and default split are accurate; lines 712, 738, 843-861, 1846-1858 agree with current files. | No material ownership contradiction found. | Does not turn causal/stability hypotheses into explicit test contracts. |
| plans/trendlines-old-file-by-file-context.md | Archive is duplicate/non-self-contained; shim routes its app.trendlines.* imports to active package; duplicate-symbol risk accurate at lines 16-22, 74-105. | No material ownership contradiction found. | Does not quantify which old files are reachable from normal canonical entry points. |
| src/libs/trendlines/docs/architecture.md | Layer model, facade flow, shim concept, and boundary ownership direction remain accurate. | Test path is conceptual/stale: it describes app/trendlines/tests/test_import_boundaries.py; actual tracked test is src/libs/trendlines/tests/test_import_boundaries.py. The “15 test functions” count is consistent with actual file. Public facade default pathfinding versus optimizer/RegimeV2 ensemble split is under-explained. | No causal contract or fit-only side-effect boundary. |
| src/libs/trendlines/docs/pivots.md | Fractal and RDP roles, ATR-scaled RDP epsilon, and pivot output concepts match pivots/fractal.py and pivots/rdp_zigzag.py. | RDP “O(n log n) amortized” does not state nested interior scans and possible O(n^2) worst case. “Min segment spacing keeps the higher/lower extreme of each cluster” overstates code: extract() only skips candidates using last_accepted_bar (rdp_zigzag.py:60-80). | No prefix-extension or future-suffix perturbation test specification. |
| src/libs/trendlines/docs/fitting.md | Pathfinding, LS, and RANSAC descriptions broadly match implementation. | Registry list omits active ensemble (fitting/__init__.py:3-7). Metadata example says extractor_name/fitter_name, while pipeline writes nested metadata["pipeline"]["extractor"]/["fitter"] (pipeline/orchestrator.py:44-51). RANSAC metadata table says n_trials; implementation emits max_trials and no n_trials field (ransac.py:85-90). Pathfinding pair-only O(n^2) description omits intermediate-bar scans (pathfinding.py:129-149,163-187). | No seed-None, equal-score tie, post-OLS cut-validity, or exception-degradation contract. |
| src/libs/trendlines/docs/pipeline.md | Pipeline stages and typed configuration concept match pipeline/orchestrator.py:28-96. | TrendlineFitResult.is_valid documentation describes both-side validity; fitters set bool(support_lines or resistance_lines) (contracts/contracts.py:80-109; pathfinding.py:72-77; ensemble.py:131-142). One-sided result can therefore be is_valid=True while has_closed_channel=False. | No distinction between score/fold stability and checkpoint line-geometry stability. |
| src/libs/trendlines/docs/data.md | Dataset/manifest/temporal abstractions and explicit artifact persistence match data/artifacts.py:17-66. | No current contradiction found. | Persistence is documented, but no API-level as-of/known-at/checkpoint replay contract exists. |

Important distinction: walk-forward fold-score stability is covered in
tests/test_optimization_benchmarks.py:192-220; it is not evidence that line
indices, slopes, intercepts, boundaries, or signals remain invariant when a
checkpoint prefix is replayed.

## 6. Runtime entry-point map

All rows below are verified from src/libs/trendlines/api.py and
pipeline/orchestrator.py, not inferred from docs.

| Entry point | Source and called pipeline | Extractor/fitter construction | Config and boundary/signal path | Network, persistence, as-of |
|---|---|---|---|---|
| fit_trendlines | api.py:76-103; calls execute_trendline_pipeline() | Defaults fractal + pathfinding; orchestrator resolves registry objects at orchestrator.py:38-42, extracts pivots, passes PivotSet to fitter at :41-42. | No boundary, signal, asset resolution, or history. Returns TrendlineOutput with stages extract, fit. | No network; no writes; no as_of, checkpoint, known-at, replay, or historical-output persistence parameter. |
| fit_trendlines_to_boundary | api.py:106-167; calls execute_trendline_pipeline(), then build_boundary_result_from_trendline_result() at :150-157. | Same defaults and registry path. | Optional resolve_asset_config() at :141-148 supplies boundary ATR/tolerance; adapter at boundary/adapters.py:279-...; no signal stage. | No network or writes; no point-in-time contract. |
| fit_oscillator_to_boundary | api.py:170-230; resolves oscillator config, builds TrendlinePipelineConfig, calls execute_trendline_pipeline() at :204-207, then boundary adapter at :209-217. | Extractor/fitter come from resolved oscillator config. | resolve_oscillator_config() at :187-190; boundary only. Docstring explicitly says signal extraction is not performed (api.py:178-186). | No network or writes; no as-of/checkpoint parameter. |
| fit_and_signal | api.py:233-316; pipeline at :263-270, boundary at :279-287, signal orchestrator at :290-296. | Same registry construction; fitter receives pipeline pivots. | Loads/resolves asset config at :272-276; TrendlineSignalOrchestrator.run() receives in-memory history and context. | No network or write in normal call; history/context are not checkpoint/as-of state APIs. |
| optimize_trendlines | api.py:319-345; constructs TrendlinesOptimizer and calls optimize(). | Optimizer owns pipeline factory/config; source optimization/optimizer.py:115-148. | Walk-forward objective and Optuna study; no boundary/signal facade stage. | API itself does not fetch or save; optimizer has stochastic sampler and n_jobs at optimizer.py:136-146; returned result can be explicitly saved via optimization/models.py:252-266. No as-of/checkpoint API. |

Normal fit-only execution stays in memory after input DataFrame creation. The
only normal-import mutation is decorator registration into global registries
(pivots/base.py:19-29, fitting/base.py:19-29).

## 7. Extractor inventory

Registry population is import-triggered by registry/registry.py:8-13.
pivots/__init__.py:3-5 registers exactly two active extractors.

| Extractor | Inputs and defaults | Causality/full-series behavior | Ordering/revision | Complexity and label |
|---|---|---|---|---|
| fractal -> FractalPivotExtractor | high, low; defaults window_left=3, window_right=3; registration/grid at pivots/fractal.py:17-31. | sliding_window_view uses centered window; core_slice = [L, n-R) at :48-58. Last window_right rows excluded. Pivot at index i first observable once rows through i+R exist. | np.flatnonzero yields ascending indices. Equal consecutive same-value candidates are grouped and midpoint retained (:80-95). Output deterministic for fixed frame. A plateau touching prior availability boundary can change which member is retained when more rows make full group eligible: LIKELY_RISK_REQUIRES_DYNAMIC_TEST. | Required work linear in frame length plus linear masks/dedup; no complete-history algorithm beyond bounded window. CONFIRMED_FROM_CODE. |
| rdp_zigzag -> RDPZigZagPivotExtractor | high, low, close; defaults epsilon_atr=0.5, min_segment_bars=3, atr_window=14; pivots/rdp_zigzag.py:33-40. | Computes rolling ATR then mean_atr over available frame and epsilon at :44-56; RDP starts at first and final available close (:119-156). Full available prefix and final endpoint affect simplification. | Kept indices and classified pivots are ascending. Adding candles can alter prior retained points through changed endpoint geometry, changed RDP splits, and changed full-prefix mean ATR/epsilon. Static mechanism: CONFIRMED_FROM_CODE; historical repainting result: LIKELY_RISK_REQUIRES_DYNAMIC_TEST, not proven here. | _rdp_iterative scans every interior point for each stack segment (:130-155); O(n log n) is not a safe worst-case bound. Likely O(n^2) worst case: LIKELY_RISK_REQUIRES_DYNAMIC_TEST. |

## 8. Fitter inventory

Registry population imports all four implementation modules
(fitting/__init__.py:3-7). Active names: pathfinding, least_squares, ransac,
ensemble. Aliases: fractals -> fractal, rdp-zigzag -> rdp_zigzag, ols and
least-squares -> least_squares (registry/registry.py:19-28).

| Fitter | Inputs/defaults/output | Candidate, cut, selection behavior | Randomness/ties/complexity |
|---|---|---|---|
| pathfinding -> PathfindingFitter | Requires open, high, low, close; defaults pivot_window=3, optional pivot_extractor, line_fit_mode=endpoint (fitting/pathfinding.py:24-41). Produces at most one support and one resistance line (:61-77). If called directly without pivots, builds a fractal extractor (:41-46); normal pipeline passes shared pivots. | _find_path() nests current and prior pivot positions (:109-149). _segment_is_valid() checks every intermediate candle body for support/resistance cuts (:163-187). DP score is accumulated segment length; only strict new_score > current updates. best_end=max(dp, key=score) (:146-156). Endpoint mode uses final two path points; OLS mode refits path points (:189-230). | No RNG. Equal DP scores retain first inserted dict candidate through strict comparison and Python insertion order: deterministic for ordered pivots, upstream-order sensitivity remains a static risk. Pair count is O(P^2); body checks add up to O(B) per candidate, likely O(P^2*B) per side: LIKELY_RISK_REQUIRES_DYNAMIC_TEST. L0-E counters: pivot count, candidate segments, bars checked, valid/accepted segments, DP updates, path length, line count. |
| least_squares -> LeastSquaresFitter | Requires OHLC; defaults pivot_window=3, optional extractor, residual_threshold_atr=0.5, atr_window=14 (fitting/least_squares.py:20-43). At most one line per side; is_valid accepts one-sided output (:43-80). | Fits np.polyfit independently per side (:118-139), marks ATR-threshold inliers, builds line from fit/inlier metadata. No pair search, body-cut test, or candidate ranking. | No RNG; deterministic for fixed ordered pivots and numeric environment. Tie rule not applicable. Complexity linear in rows/pivots after extraction: CONFIRMED_FROM_CODE; numeric-condition drift remains LIKELY_RISK_REQUIRES_DYNAMIC_TEST. |
| ransac -> RansacFitter | Requires OHLC; defaults pivot_window=3, residual_threshold_atr=0.5, max_trials=250, max_cut_fraction=0.15, min_coverage=0.3, atr_window=14, seed=42 (fitting/ransac.py:36-46). At most one line per side (:63-85). | Each side creates np.random.default_rng(self.seed) (:142), samples pivot pairs for max_trials (:150-170), computes ATR inliers/coverage, projects all bars, applies support/resistance body cuts and cut fraction (:171-186). Strict score comparison retains first equal-score candidate (:186-200). OLS refit on selected inliers occurs after candidate cut checks (:201-237), so refit geometry is not visibly revalidated against original cuts. | Default 42 deterministic for fixed input; seed=None uses entropy and can vary repeated runs. Equal score keeps first sampled candidate. Likely O(T*(P+B)) per side with T=max_trials: LIKELY_RISK_REQUIRES_DYNAMIC_TEST. Required L0-C tests: repeated seeded hashes, repeated seed=None, equal-score fixture, post-refit penetration validity, per-side selection. |
| ensemble -> EnsembleFitter | Requires OHLC; defaults pivot_window=3, optional extractor, slope dedup tolerance 1e-4, intercept dedup ATR fraction .15, path mode endpoint (fitting/ensemble.py:30-64). Runs Pathfinding, LS, RANSAC on shared pivots (:95-108); can retain up to three non-near-duplicate lines per side, one contribution per sub-fitter. | Each sub-fitter is wrapped in except Exception (:110-123). Failure is debug-logged and represented only as sub_meta[name] = {"error": str(exc)}. Dedup ranks sorted(lines, key=score, reverse=True) (:40-50), then keeps non-near-duplicates. Any surviving side makes is_valid=True (:131-142). | Child RANSAC default seed is 42; no ensemble seed parameter. Stable sort preserves input order for equal scores; upstream nondeterministic ordering would affect equal-score dedup. Exceptions can silently reduce output while retaining partial validity: CONFIRMED_FROM_CODE; deterministic degradation needs L0-C test. Overall cost is sum of child costs, pathfinding likely dominant. |

## 9. Causality/stability test coverage

Search covered src/libs/trendlines/tests/; classification is about causal
geometry evidence, not generic temporal or score tests.

| Area | Status | Evidence and boundary |
|---|---|---|
| Prefix replay | not covered | No test constructs repeated prefix checkpoints and compares prior outputs. test_temporal.py:24-65 tests split manifests/frames only. |
| Future-suffix perturbation | not covered | No test mutates suffix while holding prefix fixed and compares pivot/line outputs. |
| Past-output invariance | not covered | No output comparison for prior indices, line coefficients, boundary rays, or signals. |
| Confirmed-pivot availability | not covered | test_signals.py:258 uses signal “confirmed_breakout”; it does not test right-window pivot observability. |
| Checkpoint replay / as_of / known-at | not covered | No matching API parameter or test. TrendlineSnapshotHistory is in-memory rolling storage (boundary/history.py:60-114), not checkpoint persistence. |
| Line geometry drift | not covered | No slope/intercept/start/end comparison across prefix checkpoints. |
| Line turnover | not covered | No line identity/turnover metric test. |
| Support/resistance inversion | not covered for replay | Boundary/quality tests include static geometry cases, but no temporal inversion assertion. |
| Deterministic output hashing | not covered | Data and temporal tests hash/round-trip manifests (test_data_contracts.py, test_temporal.py), not fit/pivot/boundary outputs. |
| Repeated RANSAC execution | not covered | test_ransac_fitter.py:18-29 runs one explicit seed=7; no repeated hash or seed=None test. |
| RDP historical revision | not covered | test_extractors.py:59-80 checks output, short frame, and missing columns only. |
| Walk-forward score stability | partially covered | test_optimization_benchmarks.py:192-220 and optimizer tests cover fold-score metrics. This is not checkpoint geometry stability. |

## 10. Baseline test results

Tracked canonical suite contains 34 test files under
src/libs/trendlines/tests/ (git ls-tree -r --name-only HEAD --
src/libs/trendlines/tests).

| Run | Result |
|---|---|
| Required collection: .venv/bin/python -m pytest --collect-only -q src/libs/trendlines/tests | Shell failure: zsh:1: no such file or directory: .venv/bin/python. No pytest duration emitted. .venv is absent. |
| Fallback collection: PYTHONPATH=src python3 -m pytest --collect-only -q src/libs/trendlines/tests | 15 tests collected; 33 collection errors. Import failures cite missing numpy, pandas, and yaml. No test body ran. |
| Required full run with mandated interpreter | Blocked by same missing .venv/bin/python; no test execution. |
| Equivalent full run: PYTHONPATH=src python3 -m pytest -q src/libs/trendlines/tests | 33 errors in 0.19s; all collection/import/setup failures. Passed 0, failed 0, skipped 0, executed 0. |
| Targeted test_import_boundaries.py fallback | 15 setup errors from missing numpy; AST test did not execute. |

Collection-error modules reported by fallback full run:

~~~
test_boundary_adapters.py
test_boundary_history.py
test_boundary_public_api.py
test_boundary_quality_metrics.py
test_config.py
test_config_resolve.py
test_data_contracts.py
test_data_fetchers.py
test_derive.py
test_drift_monitor_workflow.py
test_end_to_end_pipeline.py
test_ensemble_fitter.py
test_extractors.py
test_facade_equivalence.py
test_integration_pipeline.py
test_least_squares_fitter.py
test_optimization_benchmarks.py
test_optimization_integration.py
test_optimization_models.py
test_optimizer.py
test_pathfinding_fitter.py
test_pipeline_executor.py
test_public_api.py
test_ransac_fitter.py
test_registry.py
test_signal_orchestrator_config.py
test_signals.py
test_state_transitions_derived.py
test_structure_semantics.py
test_temporal.py
test_trendlines_cli.py
test_trendlines_pipeline_workflow.py
test_workflow_contracts.py
~~~

Failure classification:

- Observed collection/import failures: ENVIRONMENT_FAILURE. Root causes are
  absent mandated virtualenv and absent core runtime dependencies. pyproject.toml:10-43
  declares pyyaml, pandas, numpy, optuna, and pytest dependencies; system
  environment reported Python 3.14.6 and pytest 9.0.3, while project config
  requires pytest <9.
- ARCHIVE_DUPLICATE_FAILURE: statically confirmed expected failure mechanism
  for test_shared_boundary_symbols_have_single_canonical_definition, because
  archive files define symbols listed in test_import_boundaries.py:342-350.
  Runtime failure was not observed because test setup could not import NumPy.
- CANONICAL_MODEL_FAILURE: none observed; model tests did not execute.
- MISSING_OPTIONAL_DEPENDENCY: none observed as a distinct test failure.
  Optimizer source guards Optuna, but collection stopped before that boundary.
- UNKNOWN_FAILURE: none; all observed errors have environment/import cause.

No remediation was attempted.

## 11. Network and side-effect map

| Capability | File/symbol | Normal fit-only reachability | Future-study risk |
|---|---|---|---|
| Binance requests | workflows/pipeline/data_fetch.py:_build_default_connector, download_historical_data:15-66; workflows/monitoring/drift_monitor.py:_fetch_futures_klines:52-83 | Not reached by five public fit/fit-signal APIs when caller supplies a DataFrame. | CONFIRMED_FROM_CODE: workflow fetch calls get_futures_klines and sleeps 0.1s; monitor calls UMFutures().klines. Do not execute during frozen audits. |
| Filesystem writes | data/artifacts.py:_write_json_artifact:17-20; workflows/pipeline/workflow.py:215-224; drift_monitor.py:125-141; scripts/run_optimization.py cache/status/output paths | Not reached by fit-only APIs. | Explicit artifact/result/baseline/cache writes can contaminate studies if output roots are not isolated. |
| Configuration mutation | optimization/models.py:311-350; optimization/oscillator.py:...; workflows/pipeline/config_apply.py:65-89 | Not reached by fit-only APIs; optimize_trendlines returns result only. | Explicit YAML writeback changes future config and requires promotion boundary. |
| Optimization-result persistence | TrendlinesOptimizationResult.save() at optimization/models.py:252-266 | Not automatic from optimize_trendlines. | Caller/workflow can write JSON; preserve artifact hashes and config identity. |
| Subprocess creation | rg search over src/libs/trendlines: no subprocess creation call found. | NOT_APPLICABLE in canonical package. | Recheck external CLI wrappers before broad workflow execution. |
| Multiprocessing/threading | No direct multiprocessing, threading, Thread, or ProcessPool import found. Optuna receives n_jobs=config.n_jobs (optimization/optimizer.py:141-146); CLI warns about n_jobs>1 on macOS (scripts/run_optimization.py:756-759). | Not reached by fit-only APIs. | LIKELY_RISK_REQUIRES_DYNAMIC_TEST for trial-order/resource effects when n_jobs>1; keep L0-B/L0-C single-process. |
| Global registry mutation | Decorators assign EXTRACTOR_REGISTRY[name] and FITTER_REGISTRY[name] (pivots/base.py:19-29, fitting/base.py:19-29). | Reached during package import, not fit computation. | Import order/reload isolation and tests must not assume mutable process-global state persists cleanly. |
| Random generation | RansacFitter._fit_side() uses np.random.default_rng(self.seed) (fitting/ransac.py:142); Optuna samplers use seed 42 in optimization/optimizer.py:447-450. | RANSAC reached by explicit fitter/ensemble selection; no network. | seed=None and Optuna parallel trial scheduling can change outputs/order. |

No network request was made during this audit. No workflow, Binance connector,
monitor, optimizer, artifact writer, or config-applier was executed.

## 12. Frozen-data candidates

All candidates below are tracked (git ls-files --stage). CSV row counts are
data rows, excluding header. Read-only schema/timestamp scans found zero missing
cells, zero duplicate timestamps, and strictly increasing timestamps for every
candidate listed. Sizes are approximate byte sizes from stat.

Schema abbreviations: OHLCV6 = timestamp,open,high,low,close,volume;
BINANCE12 = open_time,open,high,low,close,volume,close_time,quote_volume,trades,taker_buy_base,taker_buy_quote,ignore;
TV7 = timestamp,open,high,low,close,volume,datetime;
ART8 = timestamp,open,high,low,close,volume,taker_buy_base,complete.

| Candidate | Tracked | Asset/timeframe | Rows | First -> last timestamp | Columns | Size |
|---|---:|---|---:|---|---|---:|
| src/libs/sr/tests/fixtures/btcusdt_1h_600bars.csv | yes | BTCUSDT / 1h | 600 | 2026-04-06 09:00:00 -> 2026-05-01 08:00:00 | OHLCV6 | ~39K |
| artifacts/trendline_family_candidate_trials/btcusdt_4h_20250801_20251201_candidate_geometry_v2/input/normalized_ohlcv.csv | yes | BTCUSDT / 4h | 732 | 2025-08-01 00:00:00+00:00 -> 2025-11-30 20:00:00+00:00 | ART8 | ~84K |
| artifacts/trendline_family_saturating_quality_trials/btcusdt_4h_20251201_20260401_saturating_quality_v1/input/normalized_ohlcv.csv | yes | BTCUSDT / 4h | 726 | 2025-12-01 00:00:00+00:00 -> 2026-03-31 20:00:00+00:00 | ART8 | ~88K |
| src/libs/trendlines/optimization/results/BTCUSDT_1h_2023-01-01_2026-03-01.csv | yes | BTCUSDT / 1h | 27,721 | 2023-01-01 00:00:00 -> 2026-03-01 00:00:00 | BINANCE12 | ~3.6M |
| src/libs/trendlines/optimization/results/ETHUSDT_1h_2023-01-01_2026-03-01.csv | yes | ETHUSDT / 1h | 27,721 | 2023-01-01 00:00:00 -> 2026-03-01 00:00:00 | BINANCE12 | ~3.6M |
| src/libs/trendlines/optimization/results/SOLUSDT_1h_2023-01-01_2026-03-01.csv | yes | SOLUSDT / 1h | 27,721 | 2023-01-01 00:00:00 -> 2026-03-01 00:00:00 | BINANCE12 | ~3.3M |
| src/libs/trendlines/optimization/results/HYPEUSDT_1h_2022-01-01_2026-03-01.csv | yes | HYPEUSDT / 1h | 6,591 | 2025-05-30 10:00:00 -> 2026-03-01 00:00:00 | BINANCE12 | ~840K |
| src/libs/trendlines/optimization/results/BTCUSDT_1h_2022-01-01_2026-03-01.csv | yes | BTCUSDT / 1h | 36,481 | 2022-01-01 00:00:00 -> 2026-03-01 00:00:00 | BINANCE12 | ~4.7M |
| data/tv_index_4h/CRYPTOCAP_BTC.D_4h_ohlcv.csv | yes | CRYPTOCAP_BTC.D index / 4h | 3,124 | 2025-01-01 00:00 UTC -> 2026-06-05 12:00 UTC | TV7 | ~392K |
| data/tv_index/CRYPTOCAP_BTC.D_1h_ohlcv.csv | yes | CRYPTOCAP_BTC.D index / 1h | 1,573 | 2026-04-01 00:00 UTC -> 2026-06-05 12:00 UTC | TV7 | ~200K |
| data/tv_browser/CRYPTOCAP_BTC.D_1h_ohlcv_browser.csv | yes | CRYPTOCAP_BTC.D index / 1h browser capture | 1,574 | 2026-04-01 00:00 UTC -> 2026-06-05 13:00 UTC | TV7 | ~200K |

The two BTCUSDT 4h artifact manifests independently confirm asset, timeframe,
Binance USD-M Futures market, row count, interval, and normalized-input SHA-256:

- ...candidate_geometry_v2/input/input_manifest.json:
  row_count=732, timeframe=4h, normalized SHA-256
  b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150.
- ...saturating_quality_v1/input/input_manifest.json:
  row_count=726, interval_seconds=14400, normalized SHA-256
  2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42.

research/model_inputs/*_regime_descriptors_2025.csv is derived descriptor data;
its header has no OHLCV fields. *_tv_derivatives_2025.csv has OHLCV plus
derivative fields but is derived study input, not preferred primary OHLCV.
Neither is selected as primary frozen data.

Recommendations for orchestrator approval, not final freeze:

1. Small deterministic fixture: src/libs/sr/tests/fixtures/btcusdt_1h_600bars.csv.
2. Medium real-market input: tracked BTCUSDT 4h normalized artifact
   candidate_geometry_v2 (732 rows), with manifest/hash retained.
3. Longer real-market input: tracked
   BTCUSDT_1h_2022-01-01_2026-03-01.csv (36,481 rows, canonical Binance-style
   OHLCV columns).

Do not normalize, rewrite, copy, or rename these inputs in L0-A.

## 13. Static risk register

| Risk | Static conclusion | Required dynamic follow-up |
|---|---|---|
| R1 Fractal confirmation semantics | core_slice excludes final window_right; pivot at i needs right context through i+R; equal-value plateau keeps middle eligible index (fractal.py:48-68,80-95). CONFIRMED_FROM_CODE. Historical movement/revision result remains unproven. | L0-B prefix replay one candle at a time; record first availability of each pivot; plateau fixtures; compare already-confirmed prior indices/values after suffix extension. |
| R2 RDP historical revision | Complete available close prefix, final endpoint, and complete-prefix mean ATR control RDP path/epsilon (rdp_zigzag.py:44-56,119-156). Adding candles can alter earlier kept points by code mechanism. LIKELY_RISK_REQUIRES_DYNAMIC_TEST; do not call this proven repainting. | L0-B compare each prefix with extensions; perturb future suffix only; report prior pivot additions/removals/value changes and epsilon drift. |
| R3 Pathfinding cost | Nested pivot-pair loops plus intermediate-bar body checks (pathfinding.py:129-149,163-187). Likely O(P^2*B) per side. CONFIRMED_FROM_CODE structure; runtime scaling unmeasured. | L0-E instrumentation: P, candidate segments, bars checked, valid/accepted segments, DP updates, path length, output lines. No L0-A optimization. |
| R4 RANSAC determinism | Default seed 42; seed=None entropy; strict score ties keep first candidate; post-selection OLS refit occurs after cut checks (ransac.py:142-237). CONFIRMED_FROM_CODE. | L0-C repeated fixed-seed output hashes, seed=None variability, equal-score fixture, refit penetration validity, per-side candidate stability. |
| R5 Ensemble exception suppression | Every child exception is caught; only string error metadata remains; partial lines can produce valid result (ensemble.py:110-142). CONFIRMED_FROM_CODE. | L0-C injected child failures; assert deterministic degradation, visible failed-child metadata, and expected line availability. No production change in L0-A. |
| R6 API causal contract | Public signatures expose no as_of, checkpoint timestamp, known-at time, incremental replay, or historical-output persistence. history and context in fit_and_signal are in-memory inputs only (api.py:233-316). CONFIRMED_FROM_CODE. | Keep API design out of L0-A. L0-B/L0-C use explicit external checkpoint harness and approved frozen inputs. |
| Archive ownership | Duplicate boundary symbols under trendlines_old can fail canonical ownership AST test. ARCHIVE_DUPLICATE_FAILURE mechanism statically confirmed. | Resolve environment, run test once, report exact runtime failure; archive remediation outside this audit scope. |
| Import/global state | Registry decorators mutate module-global dictionaries during import. CONFIRMED_FROM_CODE. | Run repeated isolated processes in dynamic phases; do not rely on in-process registry reset. |
| Workflow side effects | Binance, filesystem, YAML mutation, Optuna n_jobs, and result persistence sit outside normal fit-only path. CONFIRMED_FROM_CODE. | Dynamic audits force local frozen CSV, no network, isolated output root, single process/job. |

## 14. Proposed L0-B scope

Prerequisites: restore project .venv with declared dependencies; orchestrator
approve exact frozen input paths and hashes. Keep L0-B read-only for production
files.

1. Use only the approved small fixture and approved BTCUSDT 4h artifact.
2. Fractal tests: construct prefix checkpoints; measure pivot availability,
   right-window delay, prior-pivot invariance, and equal-value plateau behavior.
3. RDP tests: extend prefixes by one or more candles; compare prior pivot
   indices/values; perturb suffix only; record mean ATR/epsilon and changed
   historical pivots.
4. Emit external audit rows containing input hash, prefix length, extractor
   parameters, pivot index/value hashes, and revision deltas. Do not write into
   package or existing artifact directories.
5. Exclude fitters, boundary geometry, signal semantics, optimizer execution,
   network paths, and API redesign. Those belong to L0-C or later.

L0-B must not call a result “repainting” until measured prefix-extension or
suffix-perturbation evidence exists.

## 15. Files changed

Final intended change: this new handoff only:

plans/coder-to-orchestrator-legacy-trendlines-l0a-baseline-audit-v1.md

No files under src/libs/trendlines/**,
src/libs/models/trendlines_old/**, src/app/trendlines/**, tests/**,
scripts/**, pyproject.toml, AGENTS.md, configuration, existing plans, or
artifacts were changed. Temporary .codex/config.toml tool-settings drift was
removed before handoff.

## 16. Git status

After handoff creation and final validation, expected status:

~~~
?? plans/coder-to-orchestrator-legacy-trendlines-l0a-baseline-audit-v1.md
~~~

git diff --check passed. git diff --stat and
git diff -- plans/coder-to-orchestrator-legacy-trendlines-l0a-baseline-audit-v1.md
show no tracked diff because new handoff remains untracked; git status --short is
authoritative for its presence. No commit was created.

## 17. Commands executed

Preflight and provenance:

~~~
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git worktree list --porcelain
git ls-tree -r --name-only HEAD -- src/libs/trendlines
git ls-tree -r --name-only HEAD -- src/libs/models/trendlines_old
git ls-tree -r --name-only HEAD -- src/app/trendlines
rg --files -g AGENTS.md
~~~

Code/docs/tests/data audit:

~~~
./mcp/scripts/mcp-status.sh
codebase-memory get_architecture/search_graph/trace_path/get_code_snippet/search_code
git ls-files --stage -- candidate paths
git ls-tree -r --name-only HEAD -- src/libs/trendlines/tests
rg -n risk, side-effect, coverage, and duplicate-symbol patterns
nl -ba canonical source and test files
sed -n required docs and manifests
head/tail/wc/stat candidate CSV files
~~~

Required validation attempts:

~~~
.venv/bin/python -m pytest --collect-only -q src/libs/trendlines/tests
.venv/bin/python -m pytest -q src/libs/trendlines/tests
PYTHONPATH=src python3 -m pytest --collect-only -q src/libs/trendlines/tests
PYTHONPATH=src python3 -m pytest -q src/libs/trendlines/tests
PYTHONPATH=src python3 -m pytest -q src/libs/trendlines/tests/test_import_boundaries.py
git diff --check
git status --short
git diff --stat
git diff -- plans/coder-to-orchestrator-legacy-trendlines-l0a-baseline-audit-v1.md
~~~

No network request, branch operation, merge, rebase, cherry-pick, commit, or
L0-B dynamic audit was performed.

BLOCKED_TEST_ENVIRONMENT
