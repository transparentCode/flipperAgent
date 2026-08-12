# Coder-to-Orchestrator Handoff — Canonical Ingestion Identity Migration

Status: `READY_FOR_REVIEW`

Final programme status: `INGESTION_PROGRAM_FINAL_CERTIFICATION_READY_FOR_REVIEW`

## 1. Starting state

- Starting SHA: `ca4cf860086b916323adefc4b71b1fa7c43f5231`.
- Branch: `main`.
- The checkout was cumulative and dirty. Unrelated work was preserved.
- No commit, merge, push, branch switch, reset, or restore was performed.

## 2. Evidence archive

Before active-repository cleanup, 37 historical ingestion plans/artifacts were copied to the external immutable archive:

`/Users/kajukatli/ingestion-canonical-identity-archive-20260812-r1`

Source and archive SHA-256 manifests matched byte-for-byte. The archive is outside the repository and is excluded from the active zero-identity gate. The current final artifact was included before active historical copies were removed.

## 3. Database migration

Pre-migration conditions included zero pending outbox rows and 193,832 canonical candle/outbox rows under the former schema. The migration renamed the schema in place, renamed the two outbox indexes, and updated only persisted producer values. It did not copy, delete, regenerate, or re-ingest candle data and did not regenerate event IDs.

Migration parity:

- candle count: `193,832 → 193,832`;
- outbox count: `193,832 → 193,832`;
- pending outbox: `0 → 0`;
- first/last lane timestamps and all 54 lane counts: unchanged;
- producer inventory after migration: `ingestion=193,832`;
- canonical hypertable retained with 6 chunks;
- indexes: `ingestion_outbox_pending_idx`, `ingestion_outbox_published_idx`.

Current post-certification state is larger only because normal live/certification activity continued the system: `195,380` candles, `195,380` outbox rows, `0` pending, all producer values `ingestion`.

The only remaining relations are `ingestion.candles` and `ingestion.outbox`; the retired public relations and unused provider-candle relation are absent, with no dependent views or foreign keys.

## 4. Canonical repository/runtime surfaces

- Python package: `apps.ingestion_app` only.
- Tests: `tests/ingestion` only.
- Configuration: `configs/ingestion/` with root namespace `ingestion`.
- Settings: `IngestionSettings` and `load_ingestion_settings()`.
- Timescale: `ingestion.candles`, `ingestion.outbox`.
- Source, manifest, requested-by, producer, and signal origin: `ingestion`.
- Derived-provider fallback: `ingestion_derived`.
- OHLCV stream: `stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}`.
- Compose service: `ingestion`.
- CLI: `flipper-ingestion`.
- Log: `/app/logs/ingestion.log`.
- OTEL service and metric/trace identity: `ingestion`.
- Grafana file: `ingestion.json`; UID: `flipper-ingestion`.
- Operations document: `docs/ingestion_operations.md`.
- Event type and schema version remain `candle.committed` and `1`.

No dual loader, source value, stream namespace, Compose service, CLI, or compatibility alias remains active.

## 5. Valkey migration and protection

The migration used targeted key deletion only. No DB0 `FLUSHDB` or `FLUSHALL` was issued, and no historical published-outbox replay was performed.

The six canonical weekly lane keys were provisioned as empty canonical stream keys because they are part of the current configured 54-lane inventory. They contain no historical entries and no retained consumer groups; normal future publication owns their contents.

A typed DB0 scan during the final run found six recomputable feature keys with stale migration metadata. Only those six feature keys were removed and rebuilt by the normal signal worker. Input streams, manifests, lifecycle state, signal groups, database rows, and protected hot state were not flushed or reset.

Final independent DB0 verification, using a resolved logical database index of `0`, reported:

- retired key/value identity findings: `0`;
- canonical manifests: `6`, all source `ingestion`, enabled and LIVE;
- canonical OHLCV streams: `54`;
- signal input groups: `8`;
- lifecycle stream: present, length `6`;
- all PEL values: `0`;
- all lag values: `0`;
- `production_db0_flush_issued=false`;
- `valkey_flush_commands_issued=false`.

The independent verifier returned `READY_FOR_REVIEW` with the protected state intact.

## 6. Architecture and generated assets

Six affected D2 sources were validated and regenerated with the repository renderer:

- `docs/architecture/ingestion_app/overview.d2`;
- `docs/architecture/ingestion_app/io.d2`;
- `docs/architecture/ingestion_app/lifecycle_sequence.d2`;
- `docs/architecture/signal_app/overview.d2`;
- `docs/architecture/signal_app/io.d2`;
- `docs/architecture/alert_app/overview.d2`.

Each generated SVG exists, is non-empty and valid XML/SVG, and contains the canonical labels.

## 7. Standalone certification evidence

- N1C operations: `READY_FOR_REVIEW`.
- L2B2 database resilience: return code `0`, including failed-closed outage, atomicity, reconnect, and cleanup checks.
- N1D observability: `READY_FOR_REVIEW`, including canonical metrics, traces, logs, dashboard provisioning, exporter degradation, and shutdown.
- N2C retention/recovery: `READY_FOR_REVIEW`, including 90-day candle policy, 7-day published-outbox policy, pending-row safety, DB15 isolation, manifest rebuild, Timescale priming, and no historical stream replay.
- N3B pre/post verification: return code `0`, verification-only, DB0 resolved index `0`.

DB15 recovery used only logical database `15`; DB0 remained untouched.

## 8. Fresh whole-programme certification

Fresh artifact:

`artifacts/ingestion_final/final_certification.json`

SHA-256:

`3a0a8b909e47a978e8e534debb0b22cb2147f53b0aab00b8107552f57da9e2dc`

The single coherent run contains, in order:

`N3B-pre → N1C → L2B2 → N1D → N2C → post-N2C signal drain → N3B-post → steady_state → resource_restore`

It records:

- all 11 required production image builds with return code `0`;
- six-asset runtime LIVE and enabled count `6`;
- fresh progression and semantic checks for all six 1m lanes;
- all eight signal pairs LIVE;
- all eight feature and price bootstrap outputs;
- eight current signal consumers with PEL/lag `0`;
- pending outbox `0`;
- six canonical manifests;
- canonical package import inside the container;
- final quiescence proven before shutdown.

The recorded shutdown order is:

`signal-worker → runtime_pause → pending_outbox_zero → ingestion → broker`

## 9. Regression and static validation

Latest focused results:

- `tests/ingestion`: `500 passed, 14 skipped, 2 warnings`;
- focused namespace/final tests: `15 passed`;
- signals, integration signals, commons, market-data and runtime-scale set: `176 passed, 1 warning`;
- strategy/risk focused set: `195 passed, 3 warnings`;
- Ruff format was run only on `src/apps/signal_app/ohlcv_source.py`, `src/libs/common/config_validator.py`, and `tests/signals/test_ohlcv_source.py`;
- the three formatter diffs were limited to wrapping/parenthesis layout, pre/post ASTs were identical, and no logic, contract, constant, or assertion changed;
- complete canonical-ingestion scope Ruff check: passed;
- complete canonical-ingestion scope Ruff format check: passed (`104 files already formatted` after the three-file remediation);
- compileall: passed;
- `git diff --check`: passed;
- `docker compose config`: passed;
- `docker compose --profile prod config`: passed.

The repository-wide Ruff command remains non-gating because it reports unrelated existing debt outside the migration scope. The focused canonical ingestion and certification surfaces are clean.

Focused alert/scraper validation recorded 61 passing tests and four alert-container errors because the alert API was intentionally stopped during that smoke. A separate scraper-service collection path is blocked by the environment's unavailable `httpx2` package. Neither is an ingestion contract failure; no dependency was installed and no unrelated defect was repaired.

## 10. Final infrastructure

- Timescale: running and healthy.
- Broker: stopped, exit `0`.
- Ingestion: stopped, exit `0`, `OOMKilled=false`.
- Signal worker: stopped, exit `0`, `OOMKilled=false`.
- Observability services: restored/stopped.
- Trading services: stopped.
- MCP proxy: stopped.
- Final pending outbox: `0`.

## 11. Residual risk and scope boundary

The external archive is the historical record for pre-migration evidence. The active repository, current database catalog, DB0 key/value scan, effective Compose configuration, generated dashboards, and final artifact are canonical-only.

No trendline, regime, SR research, or unrelated model version identity was changed. No production remediation was performed after the fresh final run. No further ingestion implementation phase is authorized by this handoff.
