---
goal: Independently audit the merged ingestion-to-Decision pipeline and observability integration
stage: orchestrator-decision
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Needs Revision
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, audit, ingestion, decision, observability]
---

# Independent post-merge ingestion -> Decision audit

## Decision

The merged local state is **not ready to push** because one HIGH-severity observability-isolation defect is verified. No BLOCKER or HIGH defect was verified in the canonical ingestion -> Decision data/restart pipeline itself.

Local integration state reviewed:

- `main`: `c9dca43e721321f51d0cc8b51f2e78f363e07b73`
- `origin/main`: `444c480aa65634fcb6c736dab6c449076a08f871`
- local main ahead by 2 commits
- checkout clean
- nothing pushed

## Independent-review method

A separate local Codex CLI (`codex-cli 0.148.0`, GPT-5.6 Luna) was invoked as an independent read-only Quant Orchestrator. Broad autonomous runs were not accepted as evidence when they exceeded the local execution cap or crashed while attempting pytest under Codex's sandbox/watchdog environment. Two bounded, line-numbered source-packet reviews were then completed without repository writes:

1. core Ingestion -> Decision pipeline audit;
2. Decision observability/alert/Grafana/D12 integrity audit.

Every material Codex finding was independently checked against the live merged repository and tests before acceptance or rejection.

## Verified HIGH defect

### H1 — Decision observability is not actually non-authoritative

Affected boundaries include:

- `src/apps/decision_app/runtime/live.py::poll_once()` after `DirectCursorInput.accept()`
- `src/apps/decision_app/runtime/live.py::_attempt_lane()` after policy evaluation and publication acknowledgement
- `src/apps/decision_app/runtime/service.py::_sync_observability()`
- `src/apps/decision_app/runtime/service.py::_market_loop()` poll-duration `finally` hook
- `src/apps/decision_app/runtime/service.py::_rebuild_locked()` rebuild telemetry

The runtime calls `DecisionObservability` synchronously without a best-effort exception boundary. Telemetry methods are strict and may raise. Therefore a telemetry failure can change authoritative execution.

Direct counterexample reproduced on merged `main`:

```text
RuntimeError synthetic telemetry failure
signal_entries 0
cursor 3-0
```

The test injected a failure in `record_lane_evaluation()` after a valid canonical input was accepted. `DirectCursorInput` had already advanced to stream ID `3-0`, but the telemetry exception aborted the poll before the signal was published. This violates the frozen design requirement that telemetry be non-authoritative.

This is stronger than a cosmetic monitoring failure: observability can interrupt the causal Decision transaction after input-state mutation.

Smallest remediation:

- keep `DecisionObservability` itself strict/testable;
- make every production integration call best-effort and exception-isolated;
- telemetry failures may log warnings, but must never alter input acceptance, lane evaluation/publication/finalization, service state, rebuild outcome, or original exception propagation;
- make production creation/wiring best-effort as well if constructing the observability surface can fail;
- add deterministic fault-injection tests at the real D9B/D9C hook boundaries.

## Codex findings rejected after verification

### R1 — "Direct-XREAD restart replay is treated as malformed" — rejected

Codex assumed consumer-group/PEL redelivery semantics. Decision deliberately uses direct `XREAD`:

- `DirectCursorInput.read_once()` requests entries strictly after the current cursor;
- no PEL or server-side redelivery exists;
- startup first captures the current stream tail, then reads durable canonical DB history;
- DB-ahead history reconstructs state while the transport cursor remains at the captured tail;
- later stream entries newer than that captured tail but already represented in DB are exact-checked and classified `ALREADY_REPRESENTED`.

Relevant permanent regressions include:

- `test_startup_captures_tail_before_db_ahead_warmup_and_reconstructs`
- `test_db_ahead_event_is_represented_without_re_evaluation`
- `test_retained_reconciled_context_accepts_exact_delayed_stream_duplicates`
- checkpoint/restart catch-up tests in D9A/D9B.

The non-forward guard protects against an invalid XREAD response/order; it is not the restart-replay mechanism.

### R2 — "DEGRADED HTTP 200 means readiness is fail-open" — rejected as a defect

The repository intentionally separates process/service availability from operator health:

- Decision `/health/ready` returns HTTP 200 with body `status=degraded` when desired state remains RUNNING;
- this behavior is explicitly regression-tested;
- the alert reconciler requires body status `ready`, so `degraded` still produces an operator health breach;
- Docker uses HTTP success to avoid restart-looping a recoverable/degraded process;
- downstream Risk/Execution do not use Decision health as a Compose startup dependency; they consume durable streams independently.

This is an intentional health split, not an unnoticed green-health condition. Do not change it in the telemetry-isolation remediation.

## Bounded hardening, not blocking defects

### HN1 — Publication outcome label validation

`DecisionObservability.record_publication()` accepts any non-empty string, but every current production caller passes typed finite outcomes from `SignalPublicationAck` / `ShadowPublicationAck`:

`PUBLISHED | ALREADY_IDENTICAL | CONFLICT | FAILED`.

No current unbounded-cardinality path was verified. Still, enforcing the same finite set inside observability is low-cost defensive hardening and better preserves the bounded-label contract.

### HN2 — Direct-XREAD retention exhaustion

If a live Decision process falls behind long enough for bounded Valkey retention to trim required events, the next forward event will expose a canonical market gap and fail closed with `RECONSTRUCTION_REQUIRED`. Recovery requires an explicit rebuild/reconnect rather than silently inferring missing transport history. This is an availability/operator-recovery risk, not a correctness leak.

### HN3 — Durable outbox duplicate window

Ingestion intentionally does `XADD` before marking the durable outbox row published, yielding at-least-once publication across the crash window. Decision has DB-provenance/duplicate handling and startup reconstruction. No corruption path was verified; retain this design and its restart tests.

## Architecture verdict

**Sound with one integration defect.** Canonical DB + durable outbox, direct-cursor Decision input, DB-ahead startup reconstruction, causal lane execution, explicit effect progress, and historical D12 certification remain coherent. The observability layer currently violates its own non-authoritative boundary and must be isolated.

## Pipeline verdict

**No verified BLOCKER/HIGH defect in the Ingestion -> Decision data path itself.** Restart, duplicate, DB/stream divergence, and gap semantics remain fail-closed and intentionally recovery-oriented.

## Observability verdict

**REMEDIATE before push.** Metric semantics, dynamic Grafana queries, alert identity, closed-interval lag, generation replacement, and D12B historical graduation are otherwise acceptable. Runtime telemetry calls must become best-effort.

## Top residual risks

1. telemetry exception can currently interrupt an authoritative Decision transaction — HIGH, must fix;
2. prolonged direct-XREAD lag beyond bounded stream retention requires operator-triggered reconstruction — bounded availability risk;
3. full alert-worker process integration remains less strongly certified than the nine-service metrics path because existing broader alert test environment issues are baseline-gated.

## Integration disposition

Keep the already-merged local commits on `main`; do not revert them. Do not push `main` until H1 is remediated and independently revalidated.

Terminal:

`DECISION_INGESTION_PIPELINE_INDEPENDENT_AUDIT_REMEDIATION_REQUIRED`
