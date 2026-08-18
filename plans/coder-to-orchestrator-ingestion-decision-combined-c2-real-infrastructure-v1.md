---
goal: Certify the approved ingestion to Decision/Momentum path on isolated real TimescaleDB and Valkey infrastructure
stage: coder-to-orchestrator
date_created: 2026-08-18
last_updated: 2026-08-18
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, ingestion, decision-app, momentum, combined-certification, c2, timescale, valkey]
source_base: 4647a04dc53a7ffd3de85a2f84b10bae4be9cefa
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c2
---

# Coder handoff — C2 real infrastructure certification

## Result

C2 completed the approved healthy-path ingestion -> Decision/Momentum stitch on
two fresh disposable TimescaleDB/Valkey Compose projects.

~~~
INGESTION_DECISION_C2_REAL_INFRASTRUCTURE_READY_FOR_RESILIENCE
~~~

No production application code, production Compose file, Decision asset YAML,
provider/network adapter, outage injection, Decision container, C3/C4 work, or
D11 work was added. C2 was not committed, merged, or pushed.

## C1 integration preflight

The approved C1/C1R worktree was verified before C2:

~~~
integration commit:
4647a04dc53a7ffd3de85a2f84b10bae4be9cefa
message:
test(combined): certify ingestion decision stitch
post-C1 local main SHA:
4647a04dc53a7ffd3de85a2f84b10bae4be9cefa
push:
not performed
C2 worktree:
/Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c2
~~~

Only approved C1/C1R surfaces were staged for that commit. Unrelated primary
checkout plans and .worktrees were preserved.

## Protected evidence

The protected artifact hashes were checked before and during both C2 trials:

~~~
M3       6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c
M4 func  3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792
M4 res   e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4
D10      2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
C1       386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4
~~~

## C2 files changed

- tests/combined/fixtures/c2/docker-compose.yml
- tests/combined/c2_harness.py
- tests/combined/integration/__init__.py
- tests/combined/integration/test_ingestion_decision_real_infrastructure_c2.py
- scripts/certify_ingestion_decision_real_infrastructure_c2.py
- artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json
- this coder-to-orchestrator handoff

The harness uses existing production adapters with real asyncpg and async Valkey
clients. No production runtime code changed.

## Disposable infrastructure

The test-owned Compose fixture contains exactly:

~~~
db       timescale/timescaledb:latest-pg15
broker   valkey/valkey:latest
~~~

It uses test-only credentials, project-owned disposable volumes, Valkey
noeviction, health checks, and dynamically selected localhost ports. Each trial
uses --env-file /dev/null and COMPOSE_DISABLE_ENV_FILE=1; no worktree .env or
developer DB/broker state is used. Each trial is removed with:

~~~
docker compose down -v --remove-orphans
~~~

Both trials left no C2 containers, volumes, or networks. Production
docker-compose.yml stayed unchanged, no production Decision asset YAML was
present, and no Decision container was started.

## Schema and startup

Real apply_ingestion_schema and ensure_checkpoint_schema each ran twice.
Idempotence, Timescale extension, candles hypertable, ingestion outbox,
decision checkpoint table, and Valkey PING all passed. The disposable DB and
broker were empty before seeding.

| route | startup rows | fetch limit | retained capacity | status |
|---|---:|---:|---:|---|
| BTCUSDT / 1h | 544 | 544 | 544 | STARTUP_READY |
| BTCUSDT / 4h | 544 | 544 | 544 | STARTUP_READY |
| ETHUSDT / 4h | 544 | 544 | 544 | STARTUP_READY |

Startup had zero stateful bindings, zero replay steps, and zero signals. Seeded
rows used source_type=derived, source_provider=None, source_timeframe=1m.

## Real producer -> Decision path

The real CandleRepository, CandleIngestionService, HTFAggregationService, and
OutboxPublisher processed 240 BTC and 240 ETH 1m provider candles without
provider network calls:

~~~
base 1m inserted                  480
BTCUSDT/1h derived                  4
BTCUSDT/4h derived                  1
ETHUSDT/4h derived                  1
live outbox published             486
pending outbox                      0
derived Decision inputs             6
input dispositions                  6 x INSERTED
~~~

Producer streams contained 240 BTC 1m, 4 BTC 1h, 1 BTC 4h, 240 ETH 1m, and
1 ETH 4h entries, totalling 486. All three lanes reached LIVE with
SIGNAL -> PUBLISHED -> COMMITTED; RSI/MACD and Momentum parity were true for
all routes; no base 1m signal was produced.

DB rows, producer stream payloads, and Decision events matched for every live
derived event, including UTC geometry, OHLCV, taker volume, and provenance.
The parity gates were db_stream_decision=true, derived_provenance=true, and
forward_stream_order=true.

## Duplicate and signal identity

Re-XADD of one actual producer event with identical fields and a later broker
stream ID returned DUPLICATE, created no second policy transaction, and kept
signal count at 5 before and after. Retrying the produced signal envelope
through the real ValkeySignalPublisher returned ALREADY_IDENTICAL.

The six decoded TradeSignals passed route identity, epoch-seconds timestamp,
explicit stream ID equal to market time milliseconds plus -0, decision metadata
and revision, risk model identity, direction/conviction, and idempotency checks.

## Healthy RecoveryEngine baseline

A subsequent ETH 4h bucket was populated with 239 of 240 1m constituents. The
real HTF service emitted no premature derived candle. One deterministic test
provider call supplied the missing closed candle through the real RecoveryEngine:

~~~
recovery requests       1
provider calls          1
premature derived rows  0
recovered base rows     1
recovered derived rows  1
follow-up requests      0
recovered close         178.3
C1 reference close      178.3
recovery outbox publish 2
~~~

Decision consumed the recovered event once and the ETH lane committed a
published signal. Recovered semantic evidence matched the C1 RSI/MACD/Momentum
reference at the tested boundary.

## Fresh reconstruction and deterministic artifact

A fresh Decision startup/runtime using the unchanged real DB/broker returned
STARTUP_READY, produced zero fresh transactions and zero fresh signals, had
three cursors, and matched continuous watermarks. Two normalized fresh
infrastructure trials were equal.

~~~
artifact:
artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json

SHA-256:
2799e6e40421a49c872321cb74c3a8f7fb7899840b16d8dc0d61919f9a02f667

identity_digest:
e6f5e3940588aae63234d34cb03c2c896d4583b29c92bc2e989ac6ea82056bb7

evidence_digest:
91928033d5e1ffc9780bb0bfa5557f37f00a56cde78ab5ebc911c2fc48cd2b26
~~~

The complete two-trial generator was run twice and produced identical artifact
bytes. All 14 evidence-derived gates were true:
cleanup, db_stream_decision_parity, duplicate_noop, healthy_recovery,
live_producer_counts, no_base_signal, production_scope, protected_hashes,
restart_reconstruction, route_parity, schema_contract, signal_contract,
startup_exact, and two_trial_determinism.

Identity and evidence digests cover separate payload scopes.

## Validation

~~~
C2 pure/guarded module             3 passed, 1 skipped
C2 full tests/combined            10 passed, 1 skipped
C2 real infrastructure test        4 passed
tests/decision                   406 passed
M3 + M4 certification              31 passed
tests/models/momentum              55 passed
MI0 import + config alignment      16 passed
ingestion domain/pub/service/config 277 passed
ingestion storage repository       40 passed
ingestion healthy integration       4 skipped
~~~

The real C2 script completed two fresh trials twice, and the guarded
infrastructure test was run with INGESTION_DECISION_RUN_C2_INFRASTRUCTURE=1.

Static/boundary checks passed: Ruff check --no-cache, Ruff format check,
compileall, git diff check, fresh-process Momentum isolation, plain libs.models
side-effect probe, exact-order/repeat-safe legacy bootstrap, C2 Compose config
without .env, root Compose unchanged, no production Decision asset YAML, no C2
Docker leftovers, and cache cleanup.

The four existing ingestion integration tests were environment-gated and
skipped without normal infrastructure configuration. A direct run of
tests/ingestion/storage/test_bootstrap.py has a pre-existing package import
circularity in the post-C1 baseline (storage.__init__ -> repository ->
publication.__init__ -> publisher -> repository); the same collection error
reproduces in primary and was not changed in C2. Real schema bootstrap and
idempotence passed through the C2 production adapter path.

## Two-pass self-review

Pass 1 confirmed closed UTC/grid-aligned bars, exact 544x3 startup history,
complete HTF constituents, DB/stream/Decision equality, derived provenance,
duplicate no-op, healthy recovery parity, no stale restart publication,
explicit signal IDs, and exact two-trial evidence reproduction.

Pass 2 confirmed only two-service disposable Compose, untouched production
Compose/config, no Decision asset activation, no fault injection, no provider
network, no model/feature/schema redesign, no C3/C4/D11 leakage, no extra
runtime task/framework, and cleanup after every trial.

## Residual risk and next gate

C2 certifies the healthy real persistence/broker path only. Broker/DB
interruption, outbox split failure, restart during backlog, retention gaps,
late/conflicting events, provider failure/fallback, and repeated-fault cleanup
remain C3 work. Decision container/shadow soak remains C4 work. The existing
storage bootstrap import-cycle baseline should be addressed in its owning
ingestion package before broad standalone ingestion test certification; it did
not prevent the real C2 schema path from passing.

No C2 commit, merge, or push was performed.

INGESTION_DECISION_C2_REAL_INFRASTRUCTURE_READY_FOR_RESILIENCE
