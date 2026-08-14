---
goal: Remediate D9C service-state precedence, lifecycle rebuild-source isolation, teardown reliability, and complete the originally required D9C service acceptance proofs without changing approved D9A/D9B decision semantics
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9c, remediation, lifecycle, service-state, cleanup, fastapi]
---

# Architect-to-coder — `decision_app` D9C service-state / lifecycle / cleanup remediation

## 1. Starting point

Continue only in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved before D9C review:

```text
D0-D8
D7A
D9A
D9B
```

D9C implementation is structurally sound and must be remediated in place. Do not redesign D9A, D9B, D8 publication/finalization, checkpoints, model plugins, market input, or signal transport.

The following submitted D9C design choices remain approved/frozen:

```text
one DecisionService
one market task
one lifecycle notification task
one transition lock
D9B poll_once() is the only live market transaction primitive
generation rebuild instead of hot graph mutation
direct XREAD lifecycle notifications
manifests remain lifecycle authority
explicit SR-only production composition
no PriceRelay
no main.py / port / Compose registration
no production decision asset YAML invention
```

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

Do not start D9D automatically.

---

# 2. Independent review baseline

Current implementation independently reproduces:

```text
D9C focused                         15 passed
complete tests/decision            298 passed
```

The defects below are adversarial service-shell gaps, not broad D9A/D9B instability.

---

# 3. Blocker A — control-state precedence / false readiness

## 3.1 Confirmed defect

`DecisionService._lifecycle_loop()` currently writes:

```text
service_state = DEGRADED
```

on lifecycle transport failure regardless of current control state.

`DecisionServiceSnapshot.ready` currently requires only:

```text
generation exists
AND service_state in {RUNNING, DEGRADED}
```

It does not require:

```text
desired_state == RUNNING
```

Independent reproduction:

```text
pause service

before lifecycle error:
  service_state = PAUSED
  desired_state = PAUSED
  ready = False

lifecycle reader raises

current result:
  service_state = DEGRADED
  desired_state = PAUSED
  ready = True
```

The actual `/health/ready` route consequently returns HTTP 200/degraded for a globally paused service whose market loop is intentionally disabled.

This violates the frozen D9C readiness contract:

```text
PAUSED -> not ready / 503
REBUILDING -> not ready / 503
STOPPING -> not ready / 503
STOPPED -> not ready / 503
ERROR -> not ready / 503
```

and violates the control-state meaning of `PAUSED`.

## 3.2 Required correction

Control/terminal service states must dominate background degradation evidence.

At minimum:

```text
DecisionServiceSnapshot.ready
    requires desired_state == RUNNING
    AND installed generation
    AND service_state in {RUNNING, DEGRADED}
```

Also prevent background market/lifecycle result classification from overwriting a transition state that is already authoritative, including at least:

```text
PAUSED
REBUILDING
STOPPING
STOPPED
ERROR
```

It is acceptable and desirable to still record bounded `last_error` evidence while preserving the controlling service state.

Keep the design small. A tiny internal helper such as a control-state-aware degradation recorder is acceptable; do not build a generic state-machine framework.

## 3.3 Important transition cases

Prove:

```text
PAUSED + lifecycle transport error
  -> service_state remains PAUSED
  -> desired_state remains PAUSED
  -> last_error records lifecycle fault
  -> health/ready remains 503

REBUILDING + background lifecycle/old-poll error
  -> service_state remains REBUILDING until rebuild succeeds/fails
  -> old generation is never advertised ready during rebuild

STOPPING + completion/error from the current bounded poll
  -> service does not become RUNNING/DEGRADED again
  -> health/ready remains 503
```

Do not discard already-committed same-poll transaction evidence; only preserve the controlling process state.

---

# 4. Blocker B — lifecycle reconciliation incorrectly consumes the one-shot causal rebuild budget

## 4.1 Confirmed defect

Current D9C has one boolean:

```text
_auto_rebuild_attempted
```

and every queued rebuild processed by the market loop calls:

```text
_rebuild_locked(..., automatic=True)
```

This includes both:

```text
D9B causal RECONSTRUCTION_REQUIRED
and
asset:lifecycle current-manifest reconciliation
```

Current guard:

```text
if automatic and _auto_rebuild_attempted:
    reject rebuild
```

Therefore a genuine configured lifecycle change can be discarded merely because a causal reconstruction rebuild was already attempted.

Independent direct proof:

```text
current generation = 1
_auto_rebuild_attempted = True
rebuild request reason = configured asset lifecycle changed

current result:
  no generation_factory call
  generation remains 1
  service_state = DEGRADED
  last_error = automatic reconstruction rebuild already attempted
```

This violates the frozen lifecycle authority rule:

```text
configured LIVE / RESUMED / PAUSED / STOPPED / REMOVING notification
    -> current-manifest generation reconciliation
```

The one-shot guard was specified only for repeated **causal reconstruction** loops.

## 4.2 Required correction

Distinguish rebuild source/cause with the smallest bounded representation necessary, conceptually:

```text
CAUSAL_RECONSTRUCTION
LIFECYCLE_RECONCILIATION
```

Manual `resume()` / `reconnect()` already use their direct manual path and need not become queued rebuild kinds unless that makes the implementation simpler.

Rules:

```text
CAUSAL_RECONSTRUCTION
  -> consumes/checks one-shot causal automatic rebuild budget

LIFECYCLE_RECONCILIATION
  -> does NOT consume or get rejected by causal automatic budget
  -> one rebuild per coalesced lifecycle read result
  -> failure -> ERROR/DEGRADED according to existing fail-closed rebuild behavior
  -> no infinite loop because lifecycle cursor already advances

manual resume/reconnect
  -> always explicit rebuild attempt
```

A lifecycle reconciliation that arrives while a hard D9B fault is also visible must remain preserved, because the lifecycle request is an independent current-manifest authority change.

Do not create a general event/rebuild framework.

## 4.3 Required adversarial proof

At minimum:

```text
generation 1
  -> causal RECONSTRUCTION_REQUIRED
  -> automatic rebuild generation 2
  -> causal auto budget is now consumed

before a clean reset, configured lifecycle PAUSED/LIVE notification arrives
  -> lifecycle reconciliation still calls generation_factory
  -> generation 3 is built from current manifests
  -> request is not rejected as "automatic reconstruction rebuild already attempted"
```

Also prove malformed lifecycle notification follows the same lifecycle-reconciliation path and cannot be suppressed by the causal budget.

---

# 5. Blocker C — lifespan cleanup stops after the first cleanup exception

## 5.1 Confirmed defect

Current `create_application()` teardown is sequential:

```text
await service.stop()
await valkey.aclose()
await DBPoolManager.close_pools()
ConfigManager.shutdown()
```

without nested cleanup protection.

Independent reproduction with an owned Valkey client whose `aclose()` raises:

```text
lifespan error: RuntimeError("close failed")
ConfigManager.shutdown calls: 0
```

Therefore later owned cleanup is skipped when an earlier cleanup operation raises.

This violates the D9C resource contract:

```text
resources are closed once
and cleanup continues through all owned resources
```

## 5.2 Required correction

Use a minimal nested `try/finally` cleanup sequence so each later cleanup stage is attempted even if an earlier stage raises/cancels:

```text
service stop
  finally -> Valkey close
    finally -> DB pool close
      finally -> ConfigManager.shutdown
```

Keep the required ownership order:

```text
finish/stop DecisionService
close Valkey
close DB pools
shutdown ConfigManager
```

Do not swallow `CancelledError` as a normal success. Cleanup should run, then the active exception/cancellation may propagate under normal Python semantics.

No cleanup manager/framework is needed.

## 5.3 Required regressions

Prove at minimum:

```text
D9A/generation startup raises
  -> service task never starts
  -> owned Valkey close attempted once
  -> owned DB pools close attempted once
  -> ConfigManager.shutdown once

Valkey aclose raises
  -> DB pool cleanup still attempted
  -> ConfigManager.shutdown still attempted

DB pool close raises
  -> ConfigManager.shutdown still attempted

normal lifespan shutdown
  -> each owned resource closes exactly once
```

Injected non-owned resources must remain governed by current ownership flags; do not start closing caller-owned resources.

---

# 6. D9C acceptance coverage that remains incomplete

The original D9C handoff explicitly required service-level proofs beyond the current 15 focused tests. Complete these during this remediation so D9C can be certified rather than relying only on lower-phase inference.

Do not duplicate D9A/D9B unit tests unnecessarily; add focused service-level tests only where the D9C boundary is the thing being proven.

## 6.1 Lifecycle + manifest authority

Add deterministic tests proving:

```text
configured PAUSED lifecycle notification
  -> current bounded poll completes
  -> fresh generation reads current manifest
  -> lane becomes inactive/not scheduled

configured RESUMED/LIVE notification
  -> fresh generation reconstructs before next live evaluation

stale lifecycle payload cannot override newer manifest state
  -> generation follows current AssetManifestStore state, not event payload

multiple lifecycle events in one bounded batch
  -> one current-manifest rebuild

unconfigured lifecycle event
  -> no graph mutation / no generation rebuild
```

It is acceptable to use a deterministic fake/in-memory manifest authority plus a generation factory seam when a full D9A fixture would obscure the D9C behavior.

## 6.2 Pause/resume publication suppression

Add a service-level causal proof, preferably using real SR as already approved:

```text
initial D9A SR generation at cutoff C
live SR candle C+1 -> NO_SIGNAL -> COMMITTED -> checkpoint
pause
additional canonical history appears while paused
no market poll / no decision publication while paused
resume
fresh D9A reconstructs publication-suppressed through current durable cutoff
no stale historical decision is emitted
reconstructed SR committed state matches deterministic uninterrupted/replayed expectation
next genuinely live SR candle advances normally
```

Do not change SR math/config.

For a synthetic decision-capable service proof, it is also useful to assert history accumulated during pause is not published as delayed live SIGNAL on resume.

## 6.3 Market transport/rebuild behavior

Complete explicit service-level checks for:

```text
transport error preserves same generation and exact cursor/watermark
forward-contiguous retry continues on same generation
failed generation rebuild leaves old generation unpolled
manual reconnect creates a fresh D9A/D9B generation
```

## 6.4 Synthetic signal hard-fault service proof

The original D9C plan required service-level publication failure coverage.

Prove at least:

```text
synthetic SIGNAL -> PUBLISHED -> COMMITTED
then isolated CONFLICT or FAILED path
  -> lane HALTED/RECONSTRUCTION_REQUIRED exactly as D9B says
  -> service remains alive/control plane responsive
  -> no automatic causal rebuild loop for hard fault
```

Do not point tests at shared/production `signals:*`.

## 6.5 Actual HTTP readiness/control semantics

Use the repository's FastAPI TestClient/ASGI transport pattern and prove the actual routes, not only direct helper calls:

```text
GET /health/live -> 200, no runtime I/O
GET /health/ready -> 503 before generation
GET /health/ready -> 503 PAUSED
GET /health/ready -> 503 REBUILDING/ERROR
GET /health/ready -> 200 RUNNING
GET /health/ready -> 200 DEGRADED only when desired_state == RUNNING and generation installed
GET /runtime -> bounded snapshot
GET /runtime/lanes -> bounded lane/watermark data
GET /runtime/inputs -> bounded cursor/block data
POST /runtime/pause -> pause contract
POST /runtime/resume -> fresh generation
POST /runtime/reconnect -> fresh generation
missing decision_service dependency -> 503
```

Health/status calls must cause zero DB/Valkey/model/history I/O.

## 6.6 Feature-policy wiring

Current non-default D9B transport-setting test is good. Add one non-default feature-policy test proving:

```text
DecisionGlobalSettings.feature_policy
    -> build_production_composition()
    -> exact D4 FeaturePolicy identity + allowed_features
```

Do not silently enable ATR when policy is absent; the existing fail-closed empty default remains correct.

---

# 7. Preserve approved architecture

Do NOT change or add:

```text
D6 model transaction semantics
D8 DecisionPolicy/finalization
D9A checkpoint/state reconstruction identity
D9B direct market XREAD semantics
D9B exact-ID signal transport
signal outbox
persistent InputReadCursor
consumer groups / PEL
PriceRelay / price_update:*
D7B Momentum integration
hot decision graph mutation
asset/model mutation API
generic supervisor/event framework
main.py
HTTP port assignment
Docker/Compose decision service
production configs/decision/assets/*.yaml
risk/execution changes
legacy signal_app/strategy_app changes
```

Decision config remains static for one process generation family; lifecycle rebuilds re-read current manifests. Do not introduce hot config reload to solve lifecycle behavior.

---

# 8. Files / scope

Expected changes should remain concentrated in existing D9C surfaces:

```text
src/apps/decision_app/service.py
src/apps/decision_app/bootstrap.py
src/apps/decision_app/api/routes.py            # only if readiness/control route behavior needs adjustment
possibly src/apps/decision_app/lifecycle.py     # only if required by typed rebuild evidence

tests/decision/test_d9c_service.py
tests/decision/test_d9c_lifecycle.py
tests/decision/test_d9c_api_bootstrap.py
tests/decision/test_d9c_composition.py
```

A tiny internal enum/literal/data field for rebuild source is acceptable in `service.py`.

Avoid new production modules unless strictly necessary.

---

# 9. Focused validation

Run first:

```text
tests/decision/test_d9c_composition.py
tests/decision/test_d9c_lifecycle.py
tests/decision/test_d9c_service.py
tests/decision/test_d9c_api_bootstrap.py
```

Must include new adversarial tests for all three confirmed blockers.

Then run:

```text
complete tests/decision
D9A/D8 focused compatibility
D9B focused surface
relevant non-research SR core/config/lifecycle/replay/serialization/adapter tests
commons ConfigManager/connections/pool/asset-manifest tests
signal serialization + risk profile/staleness/ATR SL/TP compatibility
canonical ingestion lifecycle/outbox/HTF/provenance contract tests
```

Full research SR remains non-gating when it fails only because already-documented frozen research artifacts are absent.

Local Timescale/Valkey integration remains environment-gated if the worktree still lacks `.env`:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

Do not create/copy `.env` or credentials and do not touch shared/production signal state.

---

# 10. Static validation

Run:

```text
Ruff check
Ruff format --check
compileall
AST/import boundary scan
git diff --check
trailing-whitespace scan
forbidden market XREADGROUP/XACK/XAUTOCLAIM/PEL scan
forbidden PriceRelay/price_update scan
forbidden legacy signal/strategy runtime import scan
FastAPI route inventory check
repo-local __pycache__ cleanup
```

No D9D leakage.

---

# 11. Two-pass coder self-review

## Pass 1 — correctness

Explicitly verify:

```text
PAUSED can never become readiness=200 because of background degradation
REBUILDING/STOPPING cannot be overwritten by stale background classification
control state and desired state remain coherent
causal auto-rebuild budget applies only to causal reconstruction
lifecycle reconciliation is never suppressed by causal rebuild budget
lifecycle cursor remains monotonic and notification remains non-authoritative
manifest state, not event payload, determines rebuilt generation
pause/resume never emits stale historical decisions
manual reconnect creates fresh reconstructed state
resource teardown attempts every owned stage despite earlier cleanup failure
all resource ownership remains once-only
D9A/D9B/D8 transaction semantics unchanged
```

## Pass 2 — simplicity / scope

Verify:

```text
no generic state machine
no generic rebuild queue
no cleanup framework
no per-lane/per-asset task
no PEL/consumer group
no PriceRelay
no new production config
no service port/main/Compose
no D9D
```

---

# 12. Handoff back to orchestrator

Update:

```text
plans/coder-to-orchestrator-decision-app-d9c-service-lifecycle-control-v1.md
```

Record exact evidence for:

```text
files/symbols changed
service-state precedence fix
ready/desired-state semantics
causal-vs-lifecycle rebuild-source contract
lifecycle-after-causal-budget adversarial proof
cleanup exception-isolation proof
PAUSED/RESUMED manifest-authority proofs
pause/resume replay-suppression proof
transport/rebuild proofs
synthetic hard-fault service proof
actual HTTP route/readiness/control proof
feature-policy wiring proof
focused/cumulative/SR/commons/risk/ingestion counts
local infra environment gate
static/import/forbidden/cache results
Pass 1 findings
Pass 2 findings
residual risks
D9D/PriceRelay carry-forward
```

Do not claim production decision config, service port, Compose runnable status, PriceRelay, resource certification, shadow parity, or cutover readiness.

Do not start D9D automatically.

Final line exactly:

```text
DECISION_APP_D9C_SERVICE_LIFECYCLE_CONTROL_READY_FOR_REVIEW
```
