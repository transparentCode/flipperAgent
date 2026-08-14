---
goal: Implement the ASGI-owned decision_app service, lifecycle generation boundary, controls, and bounded observability around approved D9A and D9B primitives
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d9c, service, lifecycle, fastapi, control]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — D9C service / lifecycle / control

## 1. Starting state and scope

- Starting SHA: `4fc0de62515112dc371e08a6cde503746c54f7f7`.
- Worktree: `/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0`.
- The cumulative worktree was already dirty with the approved D0–D9B
  implementation and handoffs. Those changes were preserved; no branch, reset,
  restore, commit, merge, or push was performed.
- D9C adds the ASGI/service shell only. No D9D, PriceRelay, risk/execution,
  signal_app, strategy_app, Docker, Compose, port assignment, or production
  decision asset configuration was added.

## 2. Files and symbols

Added/changed D9C implementation surfaces:

```text
src/apps/decision_app/composition.py
src/apps/decision_app/lifecycle.py
src/apps/decision_app/service.py
src/apps/decision_app/bootstrap.py
src/apps/decision_app/api/__init__.py
src/apps/decision_app/api/app.py
src/apps/decision_app/api/dependencies.py
src/apps/decision_app/api/routes.py
```

Focused D9C tests:

```text
tests/decision/test_d9c_composition.py
tests/decision/test_d9c_lifecycle.py
tests/decision/test_d9c_service.py
tests/decision/test_d9c_api_bootstrap.py
```

The service owns one market task, one lifecycle-notification task, one
transition lock, one current `DecisionRuntimeGeneration`, and one bounded
cached snapshot. The approved D9B `poll_once()` remains the only market
transaction primitive.

## 3. Explicit production composition

`build_production_composition()` uses closed catalogs only:

```text
PluginCatalog          SR_MODEL_SPEC
RuntimePluginCatalog   SRDecisionPlugin
FeatureCatalog         SR_ATR_DEFINITION
DecisionPolicyCatalog  passthrough@1, priority@1
DataSourceCatalog      empty
DataPolicy             explicit empty concept set
```

No discovery or unfinished model is registered. A missing feature policy is an
explicit empty policy; it does not enable every feature.

## 4. D9B configuration wiring

`build_generation_factory()` passes the configured values through unchanged:

```text
decision.live_input.batch_size              -> DirectCursorInput / D9B runtime
decision.live_input.block_ms                -> DirectCursorInput and service pacing
decision.signal_publication.stream_maxlen   -> ValkeySignalPublisher
decision.signal_publication.stream_approximate -> ValkeySignalPublisher
```

The focused non-default wiring test uses `3`, `17`, `77`, and `False`, and
observes those values in the constructed D9B runtime/publisher.

## 5. Lifecycle and generation semantics

`capture_lifecycle_tail()` uses direct `XREVRANGE` and returns `0-0` when the
lifecycle stream is absent. `LifecycleNotificationReader` uses direct `XREAD`
only, advances a bounded in-memory cursor, ignores unconfigured manifest
assets, and turns relevant or malformed notifications into a current-manifest
generation rebuild request. It creates no consumer group, PEL, or lifecycle
state authority.

Bootstrap ordering is:

```text
create resources
→ capture asset:lifecycle tail
→ build D9A startup generation from current manifests
→ construct D9B
→ start DecisionService
```

Pause waits for the current bounded poll, stops new market polls, and leaves the
lifecycle watcher alive. Resume and reconnect always build a fresh D9A/D9B
generation. Automatic rebuild is limited to explicit
`RECONSTRUCTION_REQUIRED`; malformed/conflicting input and invalid/halted
lanes remain degraded and do not enter an automatic rebuild loop. A hard D9B
fault takes precedence over a same-result reconstruction marker, while a
lifecycle rebuild that arrived during the bounded poll is preserved.

The service wake-up path was explicitly wired so a manual resume/reconnect
cannot leave the market loop asleep after the new generation is installed.

## 6. Transaction evidence and shutdown

The cached service snapshot retains the last transaction-bearing
`LanePollResult` per current lane rather than allowing rapid idle polls to erase
completed policy/publication/finalization/checkpoint evidence. Generation
replacement clears this bounded cache so old-generation evidence is not shown
as current.

Shutdown sets `STOPPING`, prevents new polls, waits for the active D9B poll to
finish, cancels/awaits only the lifecycle wait task, awaits the market task,
then allows the ASGI bootstrap to close Valkey, DB pools, and ConfigManager in
that ownership order. The deterministic stop regression proves one active poll
finishes and no second poll starts.

## 7. ASGI control plane

The testable app factory exposes exactly:

```text
GET  /health/live
GET  /health/ready
GET  /runtime
GET  /runtime/lanes
GET  /runtime/inputs
POST /runtime/pause
POST /runtime/resume
POST /runtime/reconnect
```

Handlers use only the cached `DecisionServiceSnapshot`; no DB, Valkey, model, or
history I/O is performed by health/status routes. Readiness is 200 only for an
installed generation whose `desired_state` is `RUNNING` and whose service state
is `RUNNING` or `DEGRADED`. Startup, rebuilding, paused, error, stopping,
stopped, and absent-generation states remain 503.

`create_application()` owns the existing ConfigManager, one Valkey client, DB
pool initialization, the explicit decision checkpoint schema bootstrap, the
canonical reader/checkpoint repositories, manifest store, composition, and
DecisionService. It performs no startup I/O before ASGI lifespan entry and
always shuts down ConfigManager; owned clients/pools are closed on cleanup.

There is intentionally no `main.py`, HTTP port, Compose service, or production
`configs/decision/assets/*.yaml`. The current repository has no approved
production decision graph, so D9C uses deterministic injected configurations in
tests rather than inventing one.

## 8. Required service proofs

The focused D9C surface passes **26 tests**, including:

- missing lifecycle stream → `0-0` and direct-reader cursor behavior;
- lifecycle evidence coalesced into one generation rebuild;
- pause waits for an active transaction and resume installs a fresh generation;
- reconnect does not poll the old generation again;
- transport interruption preserves the generation and retries without rebuild;
- one automatic reconstruction rebuild and no automatic loop for malformed,
  conflicting, or halted D9B evidence;
- graceful stop waits for the current poll and starts no next poll;
- real SR service-owned `NO_SIGNAL → COMMITTED → checkpoint UPDATED`;
- bounded cached transaction evidence remains visible after idle polls;
- isolated synthetic `SIGNAL → PUBLISHED → COMMITTED` with an exact market-time
  signal ID;
- explicit production composition remains closed;
- exact route inventory, bounded snapshot payload, and non-default D9B setting
  wiring.

The real SR proof uses the approved test-only SR configuration and in-memory
history/checkpoint/stream seams. The synthetic signal proof uses an isolated
Valkey-like client and never touches shared or production `signals:*` state.

## 9. Validation evidence

```text
tests/decision                                           309 passed
D9C focused                                             26 passed
non-research SR core/config/lifecycle/etc.              407 passed
commons config/connections/pool/manifest slice          57 passed
signal source + risk profile/SL/TP compatibility slice   39 passed
canonical ingestion lifecycle/outbox/provenance slice     147 passed
Ruff check (decision source/tests + SR adapter)          passed
Ruff format --check                                      70 files already formatted
compileall                                               passed
git diff --check                                         passed
production import boundary                               clean
D9C forbidden market-runtime surface scan                clean
repo-local decision caches after cleanup                 clean
```

The full `tests/models/sr` tree was also attempted. It produced `899 passed`,
`36 failed`, and `119 errors`, all in the research/source-artifact surface
blocked by missing frozen bundles/capsules (including the approved V1.5 bundle
and TAOUSDT development capsule). The focused non-research SR result above is
the relevant D9C regression evidence; no D9C adapter/service failure was
observed in that run.

Local Timescale/Valkey certification was not run because this worktree has no
repository `.env` (`LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT`). No
credentials were created/copied and no external/shared signal state was
mutated.

## 10. D9C remediation evidence

The service-shell remediation was applied in this same cumulative worktree. The
approved D9A/D9B primitives, publication/finalization semantics, checkpoint
ordering, and SR behavior were not changed.

### Control-state precedence

`DecisionServiceSnapshot.ready` now requires all three conditions:

```text
installed generation
desired_state == RUNNING
service_state in {RUNNING, DEGRADED}
```

Background lifecycle and market faults still record bounded `last_error`
evidence, but cannot overwrite the authoritative `PAUSED`, `REBUILDING`,
`STOPPING`, `STOPPED`, or `ERROR` state. The focused regressions cover paused
lifecycle transport failure and completed-poll evidence while rebuilding,
stopping, and error states.

### Rebuild-source isolation

Queued rebuilds carry one of the bounded sources
`CAUSAL_RECONSTRUCTION`, `LIFECYCLE_RECONCILIATION`, or `MANUAL`.
Only causal reconstruction consumes the one-shot automatic rebuild budget.
Lifecycle reconciliation remains eligible after that budget is consumed and
manual resume/reconnect remains explicit. A regression builds a causal
generation followed by a lifecycle generation while the causal budget remains
set, proving the lifecycle request is not suppressed.

### Exception-safe lifespan cleanup

ASGI teardown now uses nested `try/finally` stages:

```text
DecisionService.stop()
  -> owned Valkey close
  -> owned DB-pool close
  -> ConfigManager.shutdown()
```

Later owned cleanup is attempted when generation startup fails, Valkey close
fails, or DB-pool close fails. Normal teardown and ownership boundaries are
covered by focused tests; caller-owned resources are still not closed by the
bootstrap.

### Expanded D9C acceptance coverage

The remediation added actual ASGI route checks for cached readiness/control
semantics, non-default feature-policy composition wiring, and owned-resource
cleanup regressions. Existing service tests continue to cover lifecycle
coalescing, pause/resume generation replacement, transport retry, real SR
`NO_SIGNAL` finalization, isolated synthetic signal publication, and hard-fault
non-rebuild behavior.

### Control-transition serialization

`pause()` now holds the existing transition lock from the initial
`desired_state = PAUSED` write through the active-poll boundary and coherent
`PAUSED/PAUSED` snapshot. Manual resume/reconnect also captures its result while
holding the lock. This prevents an overlapping control from changing the
desired state between pause completion and its returned evidence.

The two adversarial orderings are covered:

```text
pause first, then reconnect
  -> pause returns PAUSED / PAUSED before the fresh generation is installed

reconnect first, then pause
  -> fresh generation installs, then pause returns PAUSED / PAUSED
```

Both tests assert that the active generation's poll count does not increase
after the completed pause boundary. The returned pause snapshot is explicitly
`PAUSED` / `PAUSED` and not ready; the reconnect-first case also proves the
fresh generation is the one that becomes paused.

## 11. Two-pass self-review

### Pass 1 — correctness

Verified that D9A/D9B remain authoritative, lifecycle notifications do not
override manifest authority, generation replacement occurs only at bounded poll
boundaries, pause/reconnect controls serialize to coherent state, pause/resume
never continues stale generation state, transport
errors preserve the existing runtime/cursors, only reconstruction-required
conditions auto-rebuild, and committed transaction evidence is not erased by
idle polls. Service shutdown does not intentionally cancel an in-flight D9B
transaction.

### Pass 2 — simplicity/scope

Verified one service object, one market task, one lifecycle task, one transition
lock, no per-lane tasks, no consumer groups/PEL, no persistent cursor, no signal
outbox, no PriceRelay, no D7B, no deployment/port invention, no graph mutation
API, and no generic supervisor/event framework.

## 12. Residual risks and carry-forward

D9C does not certify or provide:

```text
production decision asset/lane configuration
decision service port/process/Compose registration
PriceRelay or downstream risk price-gap continuity
real local infrastructure soak
D7B Momentum/decision-capable model integration
D10 resource certification
D11 shadow parity
D12 cutover
D13 legacy retirement
```

The ASGI factory/service shell is ready for independent review; D9D and
PriceRelay remain separately gated.

DECISION_APP_D9C_SERVICE_LIFECYCLE_CONTROL_READY_FOR_REVIEW
