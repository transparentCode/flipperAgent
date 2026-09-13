# `ingestion_app` feature map

This map follows each preserved feature from its entry point to its orchestration
owner, durable effect, and regression anchors. The source code and deterministic
tests are authoritative; this document is a navigation aid, not a second
configuration or contract source.

Phase 0 freezes the current Decision-era topology and records known gaps. P1A now
implements the immutable compiled-plan boundary, P1C moves recovery-closure
ownership into `RecoveryEngine`, P1D fences fresh generations on historical-
provider quiescence, P1E adds causal per-lane websocket silence detection, and
Phase 2 makes `RuntimeController` the sole desired-state owner while each
`RuntimeSupervisor` runs one observed generation. Phase 3 consolidates neutral
owned transport mechanics, Phase 4 decomposes websocket session lifecycle,
bounded callback bridging, and sequence/liveness tracking behind the existing
facade, and Phase 5 centralizes only bootstrap cleanup ownership in a private
lifespan ledger; G6/G7 remain explicitly deferred.

| Feature | Entry point -> owner | Durable effect and preserved branches | Regression anchors |
| --- | --- | --- | --- |
| Process entry | `main.main` -> `bootstrap.create_application` / lifespan | Loads the configured server, composes resources explicitly, records lifespan ownership in `_LifespanResources`, and contains telemetry/config cleanup when startup or Uvicorn fails. | `tests/ingestion/test_main.py`; `tests/ingestion/test_application_bootstrap.py` |
| Composition/startup | lifespan -> provider/services -> `compile_ingestion_plan` -> `RuntimeController.start` | DB/schema failure blocks runtime; app-owned providers are shared across generations; bootstrap supplies composed provider ownership to the pure plan compiler; an empty plan creates no supervisor; retention starts after controller initialization; the cleanup ledger records tasks only after controller startup; on a successful broker connection the loop binds the manifest store, runs `reconcile_all`, starts the lifecycle reconciler, then starts `OutboxPublisher`. | `tests/ingestion/test_application_bootstrap.py`; `tests/ingestion/runtime/test_planning.py`; controller composition cases |
| Startup catch-up | `RuntimeSupervisor._prepare_live_connection` | Reads the latest closed boundary, repairs bounded lookback, reconciles latest closed HTFs, repeats if the boundary advances, and opens no websocket early. | `tests/ingestion/runtime/test_supervisor.py`; `tests/ingestion/certification/test_500_lane_scale.py` |
| Live candle | websocket stream -> `RuntimeSupervisor._run_live_cycle` | Filters forming messages, validates lane/time/grid, commits before HTF work, and reaches `LIVE` only after valid work; duplicate, gap, conflict, and overflow policies remain distinct. | `tests/ingestion/runtime/test_websocket.py`; `tests/ingestion/runtime/test_supervisor.py` |
| Websocket liveness | `BinanceWebSocketManager._stream_closed_candles` -> `websocket_session` / `websocket_bridge` / `websocket_sequence` | One multiplexed consumer tracks the earliest causal deadline across lanes; accepted finalized progress advances only that lane after the generator yield resumes, while forming/duplicate traffic does not. The session owns one SDK lifecycle, the bridge bounds callback admission, and the tracker classifies sequence/recovery/liveness without per-lane tasks or a new setting. A boundary check raises `websocket_silence_detected` through the existing recovery path. | `tests/ingestion/runtime/test_websocket.py`; `tests/ingestion/runtime/test_websocket_components.py`; `tests/ingestion/certification/test_500_lane_scale.py` |
| Durable commit | `CandleIngestionService.commit_candle` -> `CandleRepository.commit_candle` | One SQL transaction covers a new candle and outbox intent; duplicates do not create an intent and conflicts never overwrite. | `tests/ingestion/storage/test_repository.py`; `tests/ingestion/services/test_candle_ingestion.py` |
| HTF materialization | `HTFAggregationService._materialize_bucket` | Complete ordered constituent grids produce Decimal derived candles; incomplete buckets return bounded repair requests and conflicts fail closed. | `tests/ingestion/services/test_htf_aggregation.py` |
| HTF timing modes | live close / latest reconciliation / affected reconciliation -> HTF service | Retains separate `as_of`, latest-closed, close-trigger, and affected-open-bucket rules. | `tests/ingestion/services/test_htf_aggregation.py` timing-mode cases |
| Automatic interruption repair | `RuntimeSupervisor._handle_stream_interruption` -> `RecoveryEngine.recover_closure` | Closes bounded missing windows, performs global identity deduplication and breadth-first follow-ups in deterministic chunks, honors generation-stop cancellation, preserves reconnect backoff, and keeps typed deadlines fatal. | `tests/ingestion/runtime/test_supervisor.py` interruption, cancellation, and deadline cases; `tests/ingestion/services/test_recovery_engine.py` closure cases |
| Historical repair/fallback | `RecoveryEngine.recover_closure` -> `RecoveryEngine.recover` -> provider attempts | DB-complete pages skip providers; bounded pages, finalization grace, lane serialization, deterministic chunk dispatch, semaphore/provider limits, fallback, retry, and non-fallback fatal errors remain intact. | `tests/ingestion/services/test_recovery_engine.py`; `tests/ingestion/certification/test_failure_matrix.py` |
| Runtime commands | API runtime routes -> `RuntimeController` -> one-generation `RuntimeSupervisor` | The controller owns desired `RUNNING`/`PAUSED` and composes the public snapshot. Pause signals generation stop without waiting for quiescence; the predecessor's observed state remains truthful until cleanup. Resume, reconnect, settings replacement, and both manual-recovery generation boundaries await the composed historical-provider idle barrier before fresh admission. Quiescence deadlines are sticky typed transport failures; post-stop quarantine checks, offline repair, settings rollback, and reconnect's deliberate no-rollback behavior remain. | `tests/ingestion/runtime/test_controller.py`; `tests/ingestion/api/test_routes.py`; provider lifecycle tests |
| Asset create/patch | API asset routes -> `AssetConfigService` -> `ConfigManager` + controller replacement | Candidate validation precedes YAML write; file/runtime mutation rolls back on failure or cancellation; lifecycle dirty state follows success only when the registered directory is writable. Production Compose keeps the root and broad `/app/configs` mount read-only while over-mounting only `/app/configs/ingestion/assets` read-write, so the existing atomic persistence path is deployable without a second authority; G1 is closed by P1B. | `tests/ingestion/services/test_config_reconciliation.py`; `tests/ingestion/integration/test_api_config_reconciliation.py`; `tests/ingestion/test_deployment_contract.py` |
| Candle delivery | bootstrap publisher loop -> `OutboxPublisher` | Pending intents publish in order and bounded batches; `XADD` precedes marking; failures permit redelivery and never claim exactly-once delivery. | `tests/ingestion/publication/test_outbox.py`; publisher idle/reconnect tests |
| Asset lifecycle | `AssetLifecycleReconciler` -> lifecycle service/manifest store | Current owned settings project to manifests; provider symbols, semantic event IDs, takeover rules, retained-event repair, and cancellation-aware dirty retries remain separate from candle SQL outbox. Decision, Alert, and Risk consume the shared manifest/lifecycle boundary. | `tests/ingestion/services/test_asset_lifecycle.py`; `tests/decision/test_d9a_ingestion_manifest_compatibility.py`; manifest compatibility tests |
| Retention | `RetentionJanitor.run` / `cleanup_once` | Deletes only published outbox rows in bounded batches and drops old chunks; pending intents and canonical readiness are protected. | `tests/ingestion/services/test_retention.py`; `tests/ingestion/storage/test_retention_repository.py` |
| Health/observability | health/runtime routes + `IngestionObservability` | Keeps liveness/readiness/runtime response shapes, metric identities/labels, and retired-lane pruning; readiness is not a LIVE-only assertion. | `tests/ingestion/api/test_routes.py`; controller observability tests |
| Shutdown/deadline | lifespan -> `_LifespanResources.aclose` | Preserves controller-first cleanup, retention stop/task reap, publisher task reap, reverse provider close, DB-pool close, final ConfigManager shutdown, stream close-before-STOPPED publication, retained ownership until actual completion, and sticky transport quarantine without a hard-kill claim. | `tests/ingestion/test_application_bootstrap.py`; provider/websocket lifecycle and certification tests |

## Runtime transition trace

`RuntimeController` records the five-value `_RuntimeCheckpoint` (settings, plan,
desired state, started state, and error) before settings replacement or manual
recovery. `_stop_for_transition(operation)` drains the old generation, awaits the
historical-provider idle barrier, synchronizes quarantine, checks it before
detaching, and does not build, install, or restore a supervisor. Reconnect and
settings replacement build before the stop; recovery builds its offline supervisor
after the stop, fences again after repair, and then builds its live replacement.
Only settings replacement and recovery restore a checkpoint on caller cancellation;
restoration reuses the barrier before installing the exact checkpoint plan.
Reconnect intentionally has no rollback.

`RuntimeSupervisor._run_live_or_interruption_cycle` converts only the live stream
interruption into bounded repair. The controller signals `stop()` for an intentional
generation retirement; the supervisor returns normally after cleanup. An unrelated
outer cancellation remains `CancelledError`. One surrounding run-loop exception
block then keeps typed transport deadlines and ordinary fatal errors on their
existing paths.

The broker-bound projection loop in `bootstrap.py` preserves this startup order:
connect broker -> bind `AssetManifestStore` -> initial lifecycle `reconcile_all`
-> start `AssetLifecycleReconciler` -> start `OutboxPublisher`. This ordering is
part of the current causal integration boundary.

The lifespan resource ledger is intentionally narrower than the composition
function. `create_application()` still constructs each repository, service,
controller, provider, and background loop explicitly. `_LifespanResources` only
records cleanup ownership and closes it in this order:

```text
controller
  -> retention janitor + task
  -> publisher task
  -> historical providers (reverse resource order)
  -> DB pools
  -> ConfigManager
```

The DB cleanup flag is set before DB initialization, and provider-factory partial
construction remains self-cleaning. This preserves cleanup on partial startup
without creating a service registry or a second configuration authority.

Lane identity and effective runtime values are resolved by the pure
`compile_ingestion_plan(settings, live_provider_ids, historical_provider_ids)`
compiler in `planning.py`; it returns immutable `IngestionPlan`/`LanePlan` values
and owns no runtime lifecycle state. The supervisor consumes those values to derive
its subscriptions.
