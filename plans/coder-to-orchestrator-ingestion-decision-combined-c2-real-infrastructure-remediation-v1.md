---
goal: C2 real infrastructure certification remediation
stage: coder-to-orchestrator
date_created: 2026-08-18
last_updated: 2026-08-18
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, ingestion, decision-app, combined-certification, c2, remediation]
source_base: 4647a04dc53a7ffd3de85a2f84b10bae4be9cefa
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c2
---

# C2R — Real infrastructure certification remediation handoff

## Scope

Continued in the existing isolated C2 worktree from
`4647a04dc53a7ffd3de85a2f84b10bae4be9cefa`.

No commit, merge, push, production Compose/config activation, Decision
container, fault injection, provider network call, or C3/C4/D11 work was done.

## Import-cycle repair

Changed only `src/apps/ingestion_app/publication/__init__.py`.
`OutboxPublisher` is now a narrow lazy package export; stable outbox and
stream-key exports remain eager. The package API is preserved while fresh
storage imports no longer depend on publisher import order.

Fresh-process imports passed for storage bootstrap/repository, publication
outbox/publisher/package exports, `apps.ingestion_app.bootstrap`, and
`apps.ingestion_app.main`. Package-level and direct `OutboxPublisher` objects
are the same class. Direct bootstrap and repository tests are green.

## Certification artifact

Artifact: `artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json`

Final SHA-256:
`9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67`

The complete two-trial generator was run twice and produced byte-identical
artifacts. The artifact status is
`INGESTION_DECISION_C2_REAL_INFRASTRUCTURE_READY_FOR_RESILIENCE`.

Separate digests are:

```text
identity_digest = 39c66933da63d43e2edc256d946e981c2f5e4c39eef75912b36f6090c5a57a3f
evidence_digest = d490b69c0735d612a161e2ebe20a20fe7ebad5f82e9db532e0762e96432fedb9
```

All 16 recomputed gates are true.

## Evidence closed by C2R

The disposable stack used only TimescaleDB and Valkey, with dynamic localhost
ports and a unique Compose project per trial. Evidence gates the production DB
and broker images, Valkey `noeviction`, isolated ownership, and an empty
pre-run state.

The initial live phase is captured immediately after the first
`runtime.poll_once()`, before duplicate/recovery work. All three semantic
cutoffs equal their live lane trigger cutoffs. Measured live counts are:

```text
base inserted = 480
BTCUSDT/1h derived = 4
BTCUSDT/4h derived = 1
ETHUSDT/4h derived = 1
outbox published = 486
DB outbox total/pending = 486 / 0
producer stream total = 486
Decision inputs inserted = 6
```

The artifact contains exactly six explicit DB-to-stream-to-Decision parity
records with route multiplicity 4/1/1. DB/stream, stream/Decision, geometry,
and provenance comparisons are all true.

Recovery compares the normalized candle against the C1 uninterrupted reference
and compares complete RSI, MACD, Momentum, cutoff, and lane-result payloads
against the C1 `08:00` next-bucket reference. All are equal.

Restart compares continuous and fresh watermark maps, input cursor maps, and
per-route feature/Momentum semantic maps directly. Fresh startup is ready,
performs zero transactions, publishes no stale signal, and has zero fresh
stateful bindings and replay steps.

Recorded signal entries are revalidated using the production
`signal_idempotency_key`, exact market-time stream ID, metadata revision,
certified M4 identity, finite price/conviction, and direction rules. The
duplicate event remains a no-op with `ALREADY_IDENTICAL` retry behavior.

## Fail-closed tamper coverage

The focused C2 test loads the generated artifact and mutates measured evidence
without changing stored gate fields. It rejects infrastructure noeviction,
isolation and empty-state evidence; pending outbox; live cutoff; a parity
record; recovery MACD and lane finalization; restart cursor and semantic
evidence; signal stream ID and idempotency; trial equality; and cleanup.

The evaluator recomputes live cutoff and signal identity facts instead of
trusting stored booleans.

## Validation

Focused and compatibility results: fresh import/storage 27 passed; C2 pure
tamper 3 passed; guarded real C2 4 passed; complete combined 10 passed and 1
skipped; complete Decision 406 passed; Momentum 55 passed; M3/M4 45 passed;
MI0/config 16 passed; C1 7 passed; and ingestion service/publication/config/
domain/storage 312 passed.

Ruff check, Ruff format check, compileall, and `git diff --check` passed.
Protected M3/M4/D10/C1 hashes are unchanged. Production Compose is unchanged,
Decision asset YAML is empty, C2 containers/volumes/networks are absent, and
repo-local caches were removed.

No worktree `.env` or copied credentials were needed; the disposable stack was
self-contained and shared developer infrastructure was not touched.

## Two-pass self-review

Pass 1 — runtime/evidence correctness passed: imports are order-independent;
live and recovery phases are separate; recovery uses the correct C1 reference;
restart compares same-cutoff state; pending outbox is gated; six parity records
are explicit; signal identity is recomputed; and gates derive from evidence.

Pass 2 — architecture/scope passed: the production change is one owner-local
lazy export. No generic lazy-import framework, schema/repository/publisher/
recovery algorithm change, production activation, fault injection, or future
phase work was added. Protected evidence is unchanged.

Residual risk is limited to C3 resilience matrices: broker/DB interruption,
XADD/mark split behavior, provider failure, and related recovery faults remain
intentionally unstarted.

INGESTION_DECISION_C2_REAL_INFRASTRUCTURE_REMEDIATION_READY_FOR_REVIEW
