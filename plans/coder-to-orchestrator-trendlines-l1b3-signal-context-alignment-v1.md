# L1-B3 Signal Context and Bar-Availability Alignment

## 1. Disposition

Implemented typed signal-input validation, causal history selection, Binance
close-time propagation, and RegimeV2 availability-time integration. No model
formula, signal threshold, pivot algorithm, fitter, YAML hyperparameter, or
Trendline V2 code changed.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
starting HEAD: 34aa761a59d93a295d2f395acb7c011117f7e0ec
starting subject: feat: add revision-aware trendline history
```

## 3. Worktree/environment proof

Worktree was clean at start. Validation used:

```text
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
RUFF=/Users/aloobhujia/.local/bin/ruff
PYTHONPATH=$PWD/src:$PWD
```

No provider or network calls were made. No commit was created.

## 4. Baseline future-history reproduction

The pre-L1-B3 HEAD accepted raw future history through the old orchestrator
surface:

```text
future_history_accepted True
history_order_consumed ['2026-01-01T03:00:00+00:00', '2026-01-01T01:00:00+00:00']
history_has_known_at [False, False]
mismatched_context_accepted True
```

The old `fit_and_signal` signature also accepted raw `history` and `context`
arguments. No event ordering, revision identity, or knowledge-time validation
existed.

## 5. Baseline context-mismatch reproduction

Old signal execution accepted OHLCV context ending at `01:00` while current
boundary event time was `02:00`. Fakeout received the unrelated raw context
dictionary without horizon validation.

## 6. Baseline Binance open/close-time reproduction

Pre-change normalization produced:

```text
binance_index 2023-11-14T22:13:20+00:00
binance_columns ['open', 'high', 'low', 'close', 'volume']
```

The index represented Binance candle `open_time`, but no `bar_available_at`
or `close_time` provenance existed. The default native adapter had no opt-in
close-time column.

## 7. Typed signal contracts

Added `signals/context.py` with frozen contracts:

```text
BarTimestampSemantics: OPEN_TIME, CLOSE_TIME
BarAvailabilitySource: EXCHANGE_CLOSE_TIME, FIXED_INTERVAL_DERIVED, CLOSE_TIME_INDEX
TrendlineSignalContext
TrendlineSignalInputs
ValidatedTrendlineSignalInputs
SignalContextContractError
SignalHistoryContractError
SignalAvailabilityError
```

`fit_and_signal()` now requires `signal_inputs`; raw public `history` and
`context` arguments were removed. Existing extractors still receive an
internal unwrapped view after one central validation pass.

## 8. Current-frame validation

Validation checks exact fit-frame identity and horizon:

```text
non-empty timezone-aware DatetimeIndex
monotonic and unique event index
availability length, timezone, order, and uniqueness
availability >= event time
OPEN_TIME availability strictly > event time
CLOSE_TIME availability == event time
all availability <= query known_at
final event == boundary timestamp/checkpoint as_of
```

Caller frames are not truncated or reordered by signal validation.

## 9. History validation

Signal history must contain boundary-stage `TrendlineSnapshot` revisions. The
validator rejects raw boundaries, missing identity, scope mismatch, identity
horizon mismatch, future events, future-known revisions, duplicate logical
snapshots, duplicate event timestamps, and non-increasing event order. Valid
history is unwrapped only after validation.

## 10. `snapshots_before` implementation

`TrendlineSnapshotHistory.snapshots_before()` now exposes the same causal
revision selection as `history_before()` while retaining snapshot/revision IDs
and `known_at`. `history_before()` delegates to it, so selection logic is not
duplicated. RegimeV2 queries event cutoff at current candle open time and
knowledge cutoff at current candle availability time.

## 11. Public facade migration

`fit_and_signal()` requires one `TrendlineSignalInputs` envelope. The exact
DataFrame passed to the facade is forwarded to validation and the internal
orchestrator. No second OHLCV context frame or caller-supplied ATR is accepted.

## 12. Signal orchestrator migration

`TrendlineSignalOrchestrator.run()` accepts typed inputs plus the exact frame,
validates once, then supplies extractors with the existing internal
`history`/`context` shape. Fakeout receives boundary-owned ATR and the exact
fit frame; caller ATR cannot override it.

## 13. Signal input identity

`signal_input_id` uses deterministic canonical hashing over:

```text
current checkpoint_id and source_id
timestamp semantics
query known_at
final current-bar availability
volume-trust declaration
selected history snapshot IDs
selected history revision IDs
selected history known_at values
```

Metadata includes `signal_input_id`, `signal_query_known_at`,
`signal_available_at`, selected history IDs, timestamp semantics, and
availability source. `signal_available_at` is the maximum of current-bar
availability and selected revision knowledge times.

## 14. Binance adapter availability

`BinanceNativeAdapter.get_historical_ohlcv(..., include_close_time=False)`
preserves default columns exactly. With `include_close_time=True`, numeric raw
`close_time` is retained. No BaseExchangeAdapter, Timescale writer, or CCXT
contract changed.

## 15. RegimeV2 integration

`compare_binance_native.fetch_binance_native_ohlcv()` opts into close time.
Normalization preserves open-time index and adds UTC `bar_available_at`.

```text
exchange close_time -> EXCHANGE_CLOSE_TIME
missing close_time + valid timeframe -> FIXED_INTERVAL_DERIVED
missing close_time + invalid/missing timeframe -> fail closed
```

`TrendlineFeatureConfig` defaults to typed `OPEN_TIME` semantics. RegimeV2
builds typed context from `bar_available_at` or strict timeframe derivation,
queries history with current open time plus close-time knowledge cutoff, and
records current snapshots with `known_at=current_bar_available_at`.

Observed replay evidence:

```text
current event:       2026-01-05T03:00:00+00:00
current available:   2026-01-05T04:00:00+00:00
query known_at:       2026-01-05T04:00:00+00:00
selected prior event: 2026-01-04T07:00:00
selected known_at:    2026-01-04T07:30:00+00:00
selected snapshot_id: 8db72203f6e46e9d315c9ac5951d92055b6609d9f2fc456d559f32f3f1f4c488
selected revision_id: 106928866e023de37ef0007c19879680b6d70bc6511be32eef4b699abcee5851
late revision id:     89c7dbc6ff4f9f0984f24c759bf8d00adbc2faccd76cbb4ce378f92fdbedf4d3
```

Late revision remained excluded because its `known_at` was after the current
bar availability.

## 16. Dedicated canonical tests

Added exactly 18 non-parametrized tests in
`test_signal_context_alignment.py`:

```text
18 collected
18 passed
```

Coverage includes timestamp validation, availability failures, scope/order
checks, raw-history rejection, future-known rejection, stable input identity,
and changed-history revision identity.

## 17. Binance/consumer tests

Added six external tests across existing suites:

```text
2 native adapter column/close-time tests
2 Binance normalizer source/fallback tests
2 RegimeV2 availability/revision-causality tests
```

Consumer matrix:

```text
tests/test_regime_v2_trendline_feature_producer.py  12 collected
tests/test_regime_v2_shadow_binance_collector.py     8 collected
tests/test_regime_v2.py                             44 collected
tests/ingestion/test_adapters.py                     5 collected
---------------------------------------------------
69 passed
```

## 18. Causal replay evidence

```text
future event history: rejected
future-known revision: rejected
unordered history: rejected
duplicate logical history: rejected
wrong asset/timeframe: rejected
OHLCV final timestamp mismatch: rejected
raw BoundaryResult history: rejected
```

Changing selected history revision changed both `signal_input_id` and the
signal-stage `revision_id`. Identical selected inputs produced stable IDs.

## 19. Performance baseline

Pre-L1-B3 HEAD, provided `TrendlineSourceRef`, Fractal + least-squares,
BTCUSDT/1h, deterministic seed 42, three timed repetitions after one warmup:

```text
fixture hash (all sizes derived from same generator):
1k   3aab9617cfef1a087407beb733b3e32f01840344f86470d8b7ce3dfd5a3b7917
10k  00d95c98f2ce99da47fb21c04704b3a3aba8619e2adc7b966d3dfcaad7ecbf26
100k 1f1b4e44d010956d3faa352aec9f006240f76920271b96335fb2a99415111172

1k:   9.680 ms median
10k: 10.762 ms median
100k: 21.733 ms median
```

## 20. Performance post-change

Same fixtures, repetitions, provided-source path, and model configuration:

```text
1k:    8.892 ms median; delta -0.788 ms (-8.14%)
10k:  11.419 ms median; delta +0.657 ms (+6.10%)
100k: 19.756 ms median; delta -1.977 ms (-9.10%)
```

No additional source-frame hash pass was introduced. Timestamp validation is
vectorized; history validation is bounded by selected history length. Binance
100k-row close-time normalization measured:

```text
fixture hash: a42b353958113a9f6521e4518ec160f051d7b79e4e049541121992d81942061e
3 repetitions: [10.296, 11.529, 16.633] ms
median: 11.529 ms
```

100k full-pipeline delta stayed within the 5 ms timestamp-validation budget;
no asymptotic model-path change observed.

## 21. Canonical regression

```text
src/libs/models/trendlines/tests: 362 passed
```

Canonical collection is exactly 362 tests.

## 22. Consumer regression

```text
RegimeV2/trendline/collector plus ingestion adapter: 69 passed
```

No RegimeV2 feature-value contract changes were introduced.

## 23. Offline regression

```text
test_optimizer.py
test_optimization_integration.py
test_trendlines_pipeline_workflow.py
20 passed
```

## 24. Static validation

```text
compileall: passed
targeted Ruff over every changed/new Python file: passed
git diff --check: passed
```

Generated repository-local Python caches were removed after validation.

## 25. Files changed

```text
src/apps/ingestion_app/adapters/binance_native.py
src/libs/models/regime_v2/adapters/trendline_feature_producer.py
src/libs/models/regime_v2/scripts/compare_binance_native.py
src/libs/models/trendlines/__init__.py
src/libs/models/trendlines/api.py
src/libs/models/trendlines/boundary/history.py
src/libs/models/trendlines/docs/architecture.md
src/libs/models/trendlines/docs/boundary.md
src/libs/models/trendlines/docs/pipeline.md
src/libs/models/trendlines/docs/signals.md
src/libs/models/trendlines/signals/__init__.py
src/libs/models/trendlines/signals/context.py
src/libs/models/trendlines/signals/orchestrator.py
src/libs/models/trendlines/tests/test_end_to_end_pipeline.py
src/libs/models/trendlines/tests/test_import_boundaries.py
src/libs/models/trendlines/tests/test_integration_pipeline.py
src/libs/models/trendlines/tests/test_signal_context_alignment.py
src/libs/models/trendlines/tests/test_signal_orchestrator_config.py
src/libs/models/trendlines/tests/test_signals.py
src/libs/models/trendlines/tests/test_snapshot_identity.py
tests/ingestion/test_adapters.py
tests/test_regime_v2.py
tests/test_regime_v2_trendline_feature_producer.py
```

## 26. Git status

Expected after this handoff is created: listed implementation/test/docs files
modified, plus this untracked handoff. No unrelated path is present.

## 27. Commands executed

```text
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
git status --short --untracked-files=all
pytest --collect-only/-q src/libs/models/trendlines/tests
pytest -q src/libs/models/trendlines/tests
pytest -q tests/test_regime_v2_trendline_feature_producer.py tests/test_regime_v2_shadow_binance_collector.py tests/test_regime_v2.py tests/ingestion/test_adapters.py
pytest -q test_optimizer.py test_optimization_integration.py test_trendlines_pipeline_workflow.py
python -m compileall -q ...
ruff check <all changed/new Python files>
git diff --check
ephemeral baseline/post-performance and replay commands
```

## 28. Residual risks

```text
Binance close-time support is opt-in at adapter level; other exchange adapters
still require their own availability semantics.
RegimeV2 plain caller frames without close_time use strict fixed-interval
derivation, which represents availability conservatively but not exchange-
reported latency.
Existing lower-level signal extractors retain internal dictionary context after
typed boundary validation; public callers cannot bypass the typed envelope.
Signal extractor partial-failure status remains a later failure-contract phase.
```

## 29. Recommended next phase

```text
L2-A — Canonical research-support and causal replay APIs
```

Required conclusion:

```text
Native trendline signals consume only exact fit-frame OHLCV.
Completed candle data cannot be used before declared availability.
Signal history is ordered, same-scope, revision-aware and knowledge-time causal.
Changing selected history revision changes signal-input and signal-revision IDs.
No model algorithm, numerical signal parameter, or YAML hyperparameter changed.
```
