---
goal: Harden C3A infrastructure-resilience certification evidence and prove a real database outage commit
stage: coder-to-orchestrator
date_created: 2026-08-18
last_updated: 2026-08-18
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, ingestion, decision-app, combined-certification, c3a, remediation]
source_base: 1851753807e929b4a0c60bfb08e491fe68609aeb
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-ingestion-decision-combined-c3a
---

# C3A remediation handoff

## Result

The C3A certification harness now returns:

```text
INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_REMEDIATION_READY_FOR_REVIEW
```

No production code, schema, Compose, Decision asset, C3B, C4, or D11 surface was changed. No commit, merge, or push was performed.

## Changed files

```text
tests/combined/c3a_harness.py
tests/combined/integration/test_ingestion_decision_infrastructure_resilience_c3a.py
scripts/certify_ingestion_decision_infrastructure_resilience_c3a.py
artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json
plans/coder-to-orchestrator-ingestion-decision-combined-c3a-infrastructure-resilience-remediation-v1.md
```

## Real DB outage evidence

Scenario B now stops Timescale before attempting the canonical observation commit through the still-open baseline asyncpg pool. The final artifact records `commit_pool_was_open=true`, `db_unreachable=true`, `db_unreachable_class=ConnectionRefusedError`, `failed_commit_class=ConnectionRefusedError`, and `failed_startup_class=ConnectionRefusedError`. After restoration, the attempted candle and matching outbox row counts are both zero, while failed-phase signal, watermark, cursor, and producer-stream state remain unchanged.

## Evidence hardening

- Scenario A/B ETH RSI, full MACD, Momentum, cutoff, lane result, and finalization directly equal the approved C2 `04:00` reference.
- ETH-only Scenario A/B/C carry direct BTC 1h/4h watermark, cursor, semantic, and quiet-lane snapshots; each before/after snapshot is equal.
- Scenario D directly compares fresh and continuous watermark maps, cursor maps, semantic maps, route multiplicity, and semantic cutoff-to-watermark alignment.
- Baseline gates require all six schema booleans, exact `544/544/544` route counts, the three certified lanes, all `STARTUP_READY`, zero startup signals, and zero pending outbox rows.
- Per-scenario infrastructure evidence covers approved images, Valkey `noeviction`, isolated fixture ownership, empty initial state, and no worktree `.env` dependency.
- Signal evidence validates exact stream, entry ID, epoch-second timestamp, decision-derived idempotency key, revision/model identity, finite values, and nonzero direction.
- Protected hashes are compared with both the approved mapping and current file hashes.
- Trial A and trial B measured payloads are compared directly; all eight scenario cleanup records are inspected.
- The evidence digest includes measured evidence, gates, and terminal status; identity digest remains stable programme identity only.

## Artifact

```text
path: artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json
sha256: 34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b
identity_digest: b0971d57f9b710b7988018276a69a6af92e0b72ef58a9eaf0b2867c98e6a83d2
evidence_digest: 705486f46f5d3409ea11a3dcf2c930116c89b117088c2bdfc057afa995c99060
```

The artifact has 13/13 gates true and two normalized trial payloads equal byte-for-byte.

Protected hashes remain: M3 `6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c`, M4 functional `3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792`, M4 resource `e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4`, D10 `2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459`, C1 `386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4`, and C2 `9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67`.

## Validation

Focused C3A synthetic/tamper validation passed `5 passed, 1 skipped`. The guarded real C3A matrix passed `6 passed`. The compatibility results were: `tests/decision` `406 passed`; Momentum/MI0/config `71 passed`; `tests/combined` `15 passed, 2 skipped`; affected ingestion `242 passed`; risk `164 passed`; signals `86 passed` with one existing warning; commons `78 passed`; execution `60 passed`.

Ruff check, Ruff format check, compileall, and `git diff --check` passed. Fresh Momentum and ingestion storage import-isolation probes passed. Protected-artifact, production-scope, cache-cleanup, and C3A Docker-resource checks passed.

## Self-review and residuals

Pass 1 confirmed the live-pool outage ordering, C2 semantic parity, ETH-only BTC isolation, split event/signal identity, direct restart maps, cutoff alignment, and evidence-derived gates. Pass 2 confirmed no production runtime, SQL/schema, provider, Compose, Decision asset, C3B, C4, or D11 leakage.

C3B late-data/gap/provider-fallback faults and C4 container/shadow behavior remain future gates. They were not started.

INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_REMEDIATION_READY_FOR_REVIEW
