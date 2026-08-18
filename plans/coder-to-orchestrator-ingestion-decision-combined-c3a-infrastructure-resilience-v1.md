---
goal: Certify ingestion to Decision resilience across isolated real TimescaleDB and Valkey fault scenarios
stage: coder-to-orchestrator
date_created: 2026-08-18
last_updated: 2026-08-18
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
source_base: 1851753807e929b4a0c60bfb08e491fe68609aeb
---

# C3A coder handoff

## Result

`INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_READY_FOR_DATA_FAULTS`

Implemented in the fresh detached worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c3a`

Starting/post-C2 SHA:

`1851753807e929b4a0c60bfb08e491fe68609aeb`

C2 integration commit in that base:

`1851753 test(combined): certify real ingestion decision infrastructure`

The C3A worktree remains uncommitted and unmerged. No push was performed.

## Scope

C3A added only:

- `tests/combined/c3a_harness.py`
- `tests/combined/integration/test_ingestion_decision_infrastructure_resilience_c3a.py`
- `scripts/certify_ingestion_decision_infrastructure_resilience_c3a.py`
- `artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json`
- this handoff

The harness reuses the approved C2 two-service fixture and production
repository, outbox, startup, live-input, publication, and Decision runtime
adapters. It adds no production code, schema, Compose, asset configuration,
provider network call, Decision container, task, retry framework, or recovery
algorithm.

## Protected evidence

All protected hashes remained unchanged:

| Evidence | SHA-256 |
|---|---|
| M3 | `6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c` |
| M4 functional | `3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792` |
| M4 resource | `e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4` |
| D10 | `2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459` |
| C1 | `386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4` |
| C2 | `9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67` |

## Infrastructure and baseline

Each scenario used a fresh Compose project with the existing C2 fixture:

- TimescaleDB `timescale/timescaledb:latest-pg15`;
- Valkey `valkey/valkey:latest` with `noeviction`;
- dynamic localhost ports, test-only credentials, and no worktree `.env`;
- no production Compose project or shared broker/database state.

Every scenario ran `down -v --remove-orphans` in cleanup and verified the
project-labelled containers, volumes, and networks were absent. The common
baseline applied both schemas twice, verified empty DB/outbox state, seeded
exactly 544 canonical derived bars for BTCUSDT/1h, BTCUSDT/4h, and ETHUSDT/4h,
reached `STARTUP_READY` for all lanes, and published zero startup signals.

## Scenario evidence

### A — Valkey outage

The real ingestion path committed one complete ETH 4h bucket while Valkey was
stopped: 240 provider 1m candles plus one derived 4h candle were durable and
241 outbox rows remained pending. Publication failed while the broker was down.
After restart, exactly 241 publications drained; Decision received one
relevant `INSERTED` event and committed one ETH transaction; pending became
zero; BTC watermarks and route state were unchanged.

### B — TimescaleDB outage

With only TimescaleDB stopped, a real ETH provider commit failed with
`InterfaceError` and fresh Decision startup failed closed with
`ConnectionRefusedError`. No broker event was created. After restore, the failed
1m row count was zero; a complete 240 + 1 ETH bucket committed and published;
Decision committed one ETH transition with no duplicate effect; pending became
zero.

### C — XADD/mark split

A canonical derived ETH 4h candle was inserted with provenance
`derived / None / 1m`. The first real publisher performed XADD, then the
test-owned mark delegate failed with `DataIngestionError`; one row remained
pending and one broker entry existed. The retry added a second entry with the
same event identity, marked the row, and left zero pending. Decision classified
the entries as `INSERTED`, `DUPLICATE`, produced one logical signal, and an
exact signal retry returned `ALREADY_IDENTICAL`; the lane remained `LIVE`.

### D — restart with canonical backlog

The producer created the next complete BTC and ETH bucket and drained its
outbox without polling the original Decision runtime. The backlog contained six
derived events across BTCUSDT/1h, BTCUSDT/4h, and ETHUSDT/4h. The original
watermarks/cursors stayed at baseline. Fresh startup reached `STARTUP_READY`,
captured the current boundary, published no stale signal, and performed zero
transactions. The original runtime consumed three transactions. Fresh and
continuous watermarks, cursors, and RSI/MACD/Momentum semantic maps matched;
fresh idle polling produced zero transactions and zero signal delta.

## Artifact

Path:

`artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json`

SHA-256:

`1194d13ff5088721fceaf9ac68f06c0a6fe7d63f9d62b8d8725173559b664e5a`

Identity digest:

`b0971d57f9b710b7988018276a69a6af92e0b72ef58a9eaf0b2867c98e6a83d2`

Evidence digest:

`d643b0b8da2fee6644a149367fc89e7adcff78c517f59f05b3fa33d59ea550c1`

Identity and measured-evidence scopes are separate. The two complete trial
normalizations are equal. Dynamic ports, Compose identifiers, durations, and
random outbox UUID values are excluded from normalized equality while event
identity relationships remain measured.

All artifact gates are true:

```text
protected_hashes
infrastructure_contract
baseline_startup_exact
broker_outage_backlog_recovery
db_outage_fail_closed_recovery
xadd_mark_split_exactly_once
decision_backlog_restart_reconstruction
no_cross_route_contamination
signal_idempotency
matrix_determinism
cleanup_all_scenarios
production_scope
```

The pure evaluator recomputes gates from measured evidence. Tests mutate outage
pending/recovery counts, DB partial rows/startup failure, event identity,
disposition order, logical signal count, restart maps/semantics, cleanup, and
trial equality; each corresponding gate fails closed.

## Validation

| Surface | Result |
|---|---:|
| C3A/C2/C1 focused | `14 passed, 2 skipped` |
| complete `tests/decision` | `406 passed` |
| `tests/models/momentum` | `55 passed` |
| MI0 import isolation + config alignment | `16 passed` |
| ingestion storage/candle/HTF/outbox/recovery slice | `148 passed, 1 skipped` |
| M3/M4 integration/certification + retention | `45 passed` |
| real C3A matrix | two complete trial runs passed |
| Ruff check | passed |
| Ruff format check | passed |
| compileall | passed |
| `git diff --check` | passed |
| fresh Momentum import isolation | passed |
| fresh ingestion storage/publication imports | passed |
| protected hashes | passed |
| production Decision assets | empty |
| production Compose | unchanged |
| C3A Docker cleanup | passed |

The guarded C2 test remains environment-controlled and was not run against
shared developer infrastructure. C3A itself used only fresh disposable
projects.

## Two-pass self-review

### Pass 1 — runtime and quantitative correctness

- closed UTC canonical bars and exact derived provenance were preserved;
- DB remained authoritative during broker outage;
- DB outage produced no half-write, outbox, or signal;
- XADD/mark ambiguity retained one event identity;
- redelivery was `INSERTED` then `DUPLICATE`;
- each recovery path produced one logical transaction;
- restart captured backlog without stale startup publication;
- fresh and continuous causal semantics matched;
- BTC remained unchanged during ETH-only recovery;
- no C3B data-fault injection was added.

### Pass 2 — architecture and scope

- no production code changed;
- no SQL, repository, outbox, recovery, Decision, or Momentum algorithm changed;
- no generic chaos/proxy framework was introduced;
- no production Compose or Decision asset was added;
- no provider calls, C3B, C4, or D11 work was started;
- all disposable resources were removed;
- prior artifacts remain byte-for-byte unchanged.

## Residual gates

C3B data-integrity/recovery faults remain intentionally unstarted, including
retention/history gaps, late events, conflicts, overlaps, malformed payloads,
provider fallback/disagreement, and duplicate storms. C4 container/shadow soak
and D11 authoritative cutover remain separately blocked.

INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_READY_FOR_DATA_FAULTS
