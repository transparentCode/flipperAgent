---
goal: Independently certify the Pre-D9D decision_app architecture hardening before PriceRelay/D9D
stage: orchestrator-decision
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision-app, pre-d9d, architecture, hardening, approved]
---

# Orchestrator decision — Pre-D9D architecture hardening

## Decision

`DECISION_APP_PRE_D9D_ARCHITECTURE_HARDENING_APPROVED`

The hardening restores the original D0 failure-isolation invariant without introducing a lane recovery framework, removes model-specific startup branching and proven compatibility/dead API surface, makes service wake control event-driven, keeps production generation/transport construction explicit, and adds bounded architecture guardrails.

## Independent findings

- Lane/input isolation is restored: `RECONSTRUCTION_REQUIRED` no longer queues a causal whole-generation rebuild. The affected lane/input remains fail-closed while the same generation can continue healthy unrelated progress.
- Generic orchestration (`startup.py`, `live_runtime.py`, `model_runtime.py`, `service.py`, `planner.py`, `data.py`) has no `libs.models.*` import and no plugin-name special case.
- Existing SR-specific initialization metadata is confined to the explicit composition seam; no new model/plugin was added.
- Production construction requires one exact async Valkey surface and always constructs the real signal publisher/checkpoint path. Signature guessing and alternate sync/async transport fallbacks are absent.
- Retired compatibility aliases/wrappers are absent from production.
- `DecisionService` has event-driven wake behavior with no 50 ms polling fallback.
- Structural inventory remains bounded: 37 Python files, 14,328 source LOC, 126 internal decision import edges, zero import cycles, and two long-lived `create_task` sites.
- No PriceRelay/D9D runtime, production decision asset YAML, main entrypoint, port, Compose service, PEL, model discovery, or legacy runtime dependency was introduced.

## Independent validation

```text
focused D9C + architecture guardrails      36 passed
complete tests/decision                   319 passed
non-research SR compatibility             431 passed
ingestion lifecycle/outbox/HTF slice      147 passed, 1 skipped
commons/risk/signals broad run            319 passed, 1 transient legacy signal failure
isolated rerun of that legacy test         1 passed
Ruff check                                passed
Ruff format --check                       passed
git diff --check                          passed
no-network decision import smoke          passed
internal import cycles                    0
forbidden surface scan                    clean
repo-local decision/test caches           clean
```

The transient `signal_app` failure occurred in an untouched legacy snapshot-feature test and passed immediately when rerun in isolation. It is not attributed to this hardening.

## Residual non-blocking notes

The permanent guard suite meets the architect-to-coder contract minimum. In a future guard-only maintenance pass it may be broadened to protect additional generic modules and all retired alias names, but current production source is clean and this is not a blocker.

Local Timescale/Valkey certification remains environment-gated by the missing worktree `.env`. No external/shared state was mutated.

## Carry-forward

No model/plugin refactoring or integration should be added until the separately planned final model-refactor stage. PriceRelay/D9D may now be architected on this hardened baseline.
