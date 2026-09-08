# `ingestion_app` feature map

This map follows each preserved feature from its entry point to its orchestration
owner, durable effect, and regression anchors. The source code and deterministic
tests are authoritative; this document is a navigation aid, not a second
configuration or contract source.

| Feature | Entry point -> owner | Durable effect and preserved branches | Regression anchors |
| --- | --- | --- | --- |
| Process entry | `main.main` -> `bootstrap.create_application` / lifespan | Loads the configured server, composes resources, and contains telemetry/config cleanup when startup or Uvicorn fails. | `tests/ingestion/test_main.py`; `tests/ingestion/test_application_bootstrap.py` |
| Composition/startup | lifespan -> provider/services -> `RuntimeController.start` | DB/schema failure blocks runtime; app-owned providers are shared across generations; publisher, lifecycle, and retention start after controller initialization. | `tests/ingestion/test_application_bootstrap.py` provider/schema/controller failure cases |
| Startup catch-up | `RuntimeSupervisor._prepare_live_connection` | Reads the latest closed boundary, repairs bounded lookback, reconciles latest closed HTFs, repeats if the boundary advances, and opens no websocket early. | `tests/ingestion/runtime/test_supervisor.py`; `tests/ingestion/certification/test_500_lane_scale.py` |
| Live candle | websocket stream -> `RuntimeSupervisor._run_live_cycle` | Filters forming messages, validates lane/time/grid, commits before HTF work, and reaches `LIVE` only after valid work; duplicate, gap, conflict, and overflow policies remain distinct. | `tests/ingestion/runtime/test_websocket.py`; `tests/ingestion/runtime/test_supervisor.py` |
| Durable commit | `CandleIngestionService.commit_candle` -> `CandleRepository.commit_candle` | One SQL transaction covers a new candle and outbox intent; duplicates do not create an intent and conflicts never overwrite. | `tests/ingestion/storage/test_repository.py`; `tests/ingestion/services/test_candle_ingestion.py` |
| HTF materialization | `HTFAggregationService._materialize_bucket` | Complete ordered constituent grids produce Decimal derived candles; incomplete buckets return bounded repair requests and conflicts fail closed. | `tests/ingestion/services/test_htf_aggregation.py` |
| HTF timing modes | live close / latest reconciliation / affected reconciliation -> HTF service | Retains separate `as_of`, latest-closed, close-trigger, and affected-open-bucket rules. | `tests/ingestion/services/test_htf_aggregation.py` timing-mode cases |
| Automatic interruption repair | `RuntimeSupervisor._handle_stream_interruption` -> recovery closure | Closes bounded missing windows, deduplicates follow-ups, honors pause/stop cancellation, preserves reconnect backoff, and keeps typed deadlines fatal. | `tests/ingestion/runtime/test_supervisor.py` interruption, cancellation, and deadline cases |
| Historical repair/fallback | `RecoveryEngine.recover` -> provider attempts | DB-complete pages skip providers; bounded pages, finalization grace, lane serialization, concurrency limits, fallback, retry, and non-fallback fatal errors remain intact. | `tests/ingestion/services/test_recovery_engine.py`; `tests/ingestion/certification/test_failure_matrix.py` |
| Runtime commands | API runtime routes -> `RuntimeController` -> `RuntimeSupervisor` | Pause/resume/reconnect/recover retain guards, desired-vs-observed state, post-stop quarantine checks, offline repair, settings rollback, and reconnect's deliberate no-rollback behavior. | `tests/ingestion/runtime/test_controller.py`; `tests/ingestion/api/test_routes.py` |
| Asset create/patch | API asset routes -> `AssetConfigService` -> `ConfigManager` + controller replacement | Candidate validation precedes YAML write; file/runtime mutation rolls back on failure or cancellation; lifecycle dirty state follows success only. | `tests/ingestion/services/test_config_reconciliation.py`; `tests/ingestion/integration/test_api_config_reconciliation.py` |
| Candle delivery | bootstrap publisher loop -> `OutboxPublisher` | Pending intents publish in order and bounded batches; `XADD` precedes marking; failures permit redelivery and never claim exactly-once delivery. | `tests/ingestion/publication/test_outbox.py`; publisher idle/reconnect tests |
| Asset lifecycle | `AssetLifecycleReconciler` -> lifecycle service/manifest store | Current owned settings project to manifests; provider symbols, semantic event IDs, takeover rules, retained-event repair, and cancellation-aware dirty retries remain separate from candle SQL outbox. | `tests/ingestion/services/test_asset_lifecycle.py`; manifest compatibility tests |
| Retention | `RetentionJanitor.run` / `cleanup_once` | Deletes only published outbox rows in bounded batches and drops old chunks; pending intents and canonical readiness are protected. | `tests/ingestion/services/test_retention.py`; `tests/ingestion/storage/test_retention_repository.py` |
| Health/observability | health/runtime routes + `IngestionObservability` | Keeps liveness/readiness/runtime response shapes, metric identities/labels, and retired-lane pruning; readiness is not a LIVE-only assertion. | `tests/ingestion/api/test_routes.py`; controller observability tests |
| Shutdown/deadline | lifespan -> controller close -> publisher/providers/DB | Preserves cleanup ordering, stream close-before-STOPPED publication, retained ownership until actual completion, and sticky transport quarantine without a hard-kill claim. | `tests/ingestion/test_application_bootstrap.py`; provider/websocket lifecycle and certification tests |

## Runtime transition trace

`RuntimeController` records the four-value `_RuntimeCheckpoint` before settings
replacement or manual recovery. `_stop_for_transition(operation)` drains the old
generation, synchronizes quarantine, checks it before detaching, and does not build,
install, or restore a supervisor. Reconnect and settings replacement build before
the stop; recovery builds its offline supervisor after the stop and its live
replacement after repair. Only settings replacement and recovery restore a
checkpoint on caller cancellation. Reconnect intentionally has no rollback.

`RuntimeSupervisor._run_live_or_interruption_cycle` converts only the live stream
interruption into bounded repair. One surrounding run-loop exception block then
keeps control cancellation, external cancellation, typed transport deadlines, and
ordinary fatal errors on their existing paths.

Lane identity is resolved by the same-file pure
`_resolve_lane_contexts(settings, live_provider)` helper; it returns lane contexts
and owns no runtime lifecycle state. The supervisor constructor derives its
subscriptions from those contexts.
