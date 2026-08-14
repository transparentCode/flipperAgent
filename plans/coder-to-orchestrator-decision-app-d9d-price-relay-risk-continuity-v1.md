---
goal: Implement and validate the model-independent decision_app PriceRelay and downstream risk continuity boundary
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d9d, price-relay, risk, continuity]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# D9D PriceRelay / downstream risk continuity

## Result

D9D is implemented in the cumulative isolated worktree. It adds a
model-independent canonical-series PriceRelay inside the existing D9B poll
cycle, plus bounded downstream risk compatibility fixes for closed-bar replay.

No new model/plugin, Momentum/D7B work, PriceRelay task, service, Compose entry,
production decision asset YAML, or D10+ implementation was added.

## Files and symbols

- `src/apps/decision_app/price_relay.py`: canonical plan compilation,
  exact-ID publisher, bootstrap, bounded catch-up, and continuity evidence.
- `src/apps/decision_app/contracts.py`: `PriceRelayPlan` and
  `PriceRelayProgress` contracts.
- `src/apps/decision_app/settings.py`: strict relay-only asset settings and
  global publication settings.
- `src/apps/decision_app/startup.py`: required relay series, manifest, capacity,
  and startup-position integration.
- `src/apps/decision_app/bootstrap.py`: explicit relay construction/config.
- `src/apps/decision_app/live_runtime.py`: relay-before-lane ordering and
  paused polling support.
- `src/apps/decision_app/service.py`: bounded relay evidence and continued
  market polling while model evaluation is paused.
- `src/apps/risk_app/runtime/worker.py`: price PEL reclaim, timestamp
  normalization, and replay-safe price processing.
- `src/libs/risk/position_tracker.py`: bar-close eligibility for price,
  trailing, and SL/TP operations.
- `configs/decision/global.yaml`: relay defaults of maxlen 200 and approximate
  trimming enabled.
- Tests: `tests/decision/test_d9d_price_relay.py`,
  `tests/decision/test_d9d_price_relay_runtime.py`,
  `tests/risk/test_d9d_price_relay_risk.py`, and affected risk fixtures.

Pre-existing cumulative SR adapter import-boundary changes were preserved.

## Contract evidence

Relay identity is the canonical ingestion series:

```text
manifest_asset + venue + instrument_id + timeframe
```

There is no `source_lane` coupling. Relay-only assets with `lanes={}` are
valid; an asset with neither a lane nor an enabled relay is rejected. The
injected current risk graph compiles without model lanes:

```text
BTCUSDT  1h, 4h
ETHUSDT  4h
XRPUSDT  1h
SOLUSDT  1h
BNBUSDT  30m
DOGEUSDT 4h
```

Every route resolves to a canonical ingestion instrument and the expected
`price_update:{asset}:{timeframe}` stream.

Wire compatibility is unchanged: `PriceUpdate.timestamp` is bar-open epoch
milliseconds, OHLCV fields use the existing float payload, and streams are
`price_update:{asset}:{timeframe}`. Transport IDs are deterministic
`bar-close epoch-ms-0`.

Exact-ID publication is:

```text
absent -> PUBLISHED
same ID and same payload -> ALREADY_IDENTICAL
same ID with different/invalid payload -> CONFLICT
ambiguous XADD with exact row after retry -> ALREADY_IDENTICAL
ambiguous XADD with no exact row -> FAILED
missing exact ID behind newer head -> CONFLICT
```

Bootstrap validates tails against canonical history/geometry. No tail plus a
captured canonical cutoff establishes a no-replay baseline. Catch-up starts at
the exact next canonical open, reads `ingestion.candles`, publishes oldest to
newest, is bounded by live batch size and stream retention, and never skips a
missing bar. Progress advances only after idempotent publication success.

## Runtime and risk integration

The existing D9B `poll_once()` remains the only market transaction and PriceRelay
runs before enabled authoritative lane evaluation. There is no third task.
While `DecisionService` is paused, input/BarStore/PriceRelay continue and lane
evaluation, policy, signal publication, state commits, and lane watermarks are
disabled. The service-level regression observed relay publication while
`PAUSED/PAUSED` with false lane-evaluation flags.

Risk keeps `risk_app_price_group` and drains its PEL after the signal PEL;
successful reclaim is acknowledged and failed processing remains pending.
Price processing derives `bar_open_seconds = timestamp / 1000` and
`bar_close_seconds = bar_open_seconds + timeframe_duration`. Price-derived
order and pending-close timestamps use bar-close seconds; idempotency retains
the original bar-open milliseconds. Positions with
`entry_timestamp >= bar_close_seconds` are excluded from replayed bars.
Existing SL/TP, multi-TP, trailing, pending-close, and order mathematics remain
unchanged.

## Validation

Focused D9D results:

- PriceRelay core/config/runtime and service-pause tests: **15 passed**.
- D9D risk compatibility tests: **6 passed**.
- Focused D9D total: **21 passed**.

Additional validation:

- `tests/decision`: **334 passed**.
- `tests/risk`: **162 passed**.
- `tests/signals` plus `tests/integration/signals`: **92 passed**, one warning.
- `tests/commons`: **78 passed**.
- affected execution/order/idempotency slice: **46 passed**.
- SR core/config/lifecycle/replay/serialization/adapter slice: **380 passed**.
- ingestion lifecycle/HTF/outbox/provenance slice: **110 passed**.

The full `tests/ingestion` run produced **499 passed, 14 skipped, 2 warnings,
1 failed**. The single failure was the existing FINAL harness test
`test_first_failed_gate_stops_later_gates`: it calls `docker compose config`
before its mocked gate, and this worktree has no `.env`. The actual Compose
error was the missing worktree environment file. This is recorded as:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

No credentials were created or copied and no external Valkey/Timescale state
was mutated.

Static/scope checks passed: scoped Ruff, format check on 76 files, compileall,
`git diff --check`, trailing-whitespace scan, decision PEL/XREADGROUP/XACK scan
(zero matches), architecture guard scan, and `PYTHONPATH=src` import smoke.
Repo-local `__pycache__` and `.pytest_cache` were removed. Codebase-memory and
GitNexus indexes were refreshed after the changes.

## Two-pass self-review and carry-forward

Pass 1 confirmed exact wire units/IDs, closed-bar chronological catch-up,
gap-fail-closed progress, pause price continuity, PEL reclaim, pre-entry
filtering, bar-close order timestamps, and unchanged risk mathematics.

Pass 2 confirmed one poll-owned relay, no worker/task per series, no event bus,
relay table, retry framework, compatibility bridge, model integration,
production decision asset YAML, `main.py`, port, or Compose service.

Not claimed: production asset configuration, legacy price-publisher ownership
handoff/cutover, real production PriceRelay/risk stream certification, resource
certification, shadow parity, or D10+ work. These remain carry-forward gates.

No commit, merge, push, branch switch, reset, or restore was performed.

## D9D target/retry remediation

Independent review found three bounded PriceRelay state defects after the
initial D9D implementation: a live target was lost after the input cursor had
advanced, transient `FAILED` publication became terminal `UNRESOLVED`, and a
new relay with neither a downstream tail nor a startup cutoff could not
establish its first valid closed-bar baseline.

The remediation changed only the poll-owned PriceRelay state:

- Each relay plan now retains one monotonic in-memory target cutoff separate
  from publication progress. Idle reconciliations continue bounded catch-up
  without requiring another input event; the retained target is cleared only
  after publication reaches it.
- `PUBLISHED` and `ALREADY_IDENTICAL` advance publication progress. `FAILED`
  leaves progress unchanged, reports `GAP_DETECTED`, and retries the exact
  next deterministic bar on the next bounded poll. `CONFLICT` remains terminal
  `UNRESOLVED` and never rewrites the stream.
- The explicit no-tail/no-warm bootstrap state accepts the first valid closed
  canonical bar. A transient first publication failure is retried from
  canonical history; semantic corruption remains fail-closed.
- `PriceRelayResult` and bounded gap evidence expose the retained target and
  remaining backlog without adding a queue, journal, task, or persistence
  surface.

The added regression evidence covers:

- target retention across idle reconciliations with exact bar1/bar2/bar3
  ordering;
- transient XADD failure and exact-ID retry;
- no-tail/no-warm first-candle establishment and first-candle retry;
- independent relay-plan failure while another plan progresses;
- runtime input-cursor advancement despite relay failure and later durable
  retry;
- paused lifecycle generation rebuild with a fresh relay continuing while
  lane evaluation remains disabled;
- risk startup signal-PEL then price-PEL ordering;
- reclaimed SL/TP price producing one close order, with pending-close blocking
  duplicate retry orders.

## Remediation validation

Current focused D9D surface: **30 passed**.

Current cumulative compatibility results:

- `tests/decision`: **341 passed**.
- `tests/risk`: **164 passed**.
- `tests/signals` plus `tests/integration/signals`: **92 passed**, one warning.
- `tests/commons`: **78 passed**.
- affected ingestion lifecycle/HTF/outbox/provenance slice: **97 passed, 2 skipped**.
- affected execution/order/idempotency slice: **30 passed**.
- non-research SR domain/config/lifecycle/serialization/replay/adapter slice:
  **286 passed**.

Static validation passed:

- scoped Ruff check;
- Ruff format check: **77 files already formatted**;
- compileall;
- `git diff --check`.

The worktree still has no `.env`, so the previously recorded full ingestion
collection gate remains environment-blocked by the existing FINAL harness
Compose preflight (`LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT`). The
remediation did not rerun live/destructive certification, create credentials,
or mutate external Timescale/Valkey state. The prior full-ingestion evidence
remains **499 passed, 14 skipped, 2 warnings, 1 environment-gated failure**;
the current affected ingestion slice is independently green above.

The two self-review passes found no change to D9B cursor/lane watermark
semantics, D8 publication/finalization, risk mathematics, PriceUpdate wire
fields, deterministic IDs, pause input/relay behavior, or the one-task
PriceRelay architecture. No D7B, D10, model integration, production config,
or external-state operation was performed.

## D9D input-gap / relay-continuity remediation

The remaining continuity defect was a cross-component trust-boundary gap:
`DirectCursorInput` correctly blocked a canonical series after a forward market
gap, but the matching `PriceRelay` still retained its previous `CONTINUOUS`
status. That could make relay continuity contradict the input cursor and service
degraded evidence.

The fix stays at the existing `_mark_series_failure()` boundary. When a known
canonical series fails, the runtime now calls
`PriceRelay.mark_input_failure()` for relay plans sourced by that exact series.
The affected relay preserves its last successful publication cutoff, records
bounded `input_failure` evidence and any known observed target, becomes
`UNRESOLVED`, disables first-candle bootstrap, and cannot publish again in the
current generation. Unrelated streams, lanes, and relay plans remain
independent. A fresh generation creates a fresh relay and can re-establish
continuity after startup validation.

The relay retains only one failure record per plan. This also handles the
runtime ordering where input failure is marked before the first relay
bootstrap: bootstrap validation runs, then the failure evidence is reapplied
so the initial reconciliation cannot overwrite `UNRESOLVED` with a baseline
`CONTINUOUS` state.

The previous transport distinction remains unchanged:

- canonical input failure/block -> current-generation `UNRESOLVED`, no retry;
- downstream PriceRelay publication `FAILED` -> retryable `GAP_DETECTED` with
  the exact retained target and deterministic next-bar retry;
- downstream `CONFLICT` remains terminal `UNRESOLVED`.

Added regression evidence covers:

- same-series forward canonical gap through the real D9B input cursor;
- unchanged cursor, blocked input stream, preserved last relay cutoff, and no
  failed-candidate PriceUpdate publication;
- unresolved state persisting across an idle poll;
- input-failure isolation for two relay plans, with the unrelated plan
  publishing normally;
- pre-bootstrap input failure not being overwritten by relay bootstrap;
- fresh-generation recovery to a normal first-candle publication;
- the already-approved transient publication `FAILED` retry path and
  lane-local/relay independence regressions remaining green.

Current validation after this remediation:

- focused D9D PriceRelay/runtime/risk surface: **33 passed**;
- `tests/decision`: **344 passed**;
- `tests/risk`: **164 passed**;
- `tests/signals` plus `tests/integration/signals`: **92 passed**, one existing
  OpenTelemetry deprecation warning;
- `tests/commons` plus `tests/execution`: **138 passed**;
- architecture guardrails: **8 passed**;
- scoped Ruff check: passed;
- scoped Ruff format check: **76 files already formatted**;
- compileall: passed;
- `git diff --check`: passed;
- scoped trailing-whitespace and cache checks: passed.

No live or destructive certification was run. The worktree still has no
`.env`, so external Timescale/Valkey validation remains the previously recorded
`LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT` gate. No credentials were
created or copied, and no external state was mutated. D10, model integration,
and cutover remain unstarted.

## D9D deferred-input-failure relay evidence remediation

The final D9D evidence defect was limited to a stale bounded result after the
already-approved valid-prefix ordering. A valid canonical prefix could publish
its PriceUpdate, then a deferred malformed suffix could invalidate the source;
the internal `PriceRelayProgress` became `UNRESOLVED`, but the earlier
`DecisionPollResult.relay_results` entry still said `CONTINUOUS`.

The fix preserves the existing ordering and successful prefix transaction. The
poll runtime now receives the affected relay IDs from
`PriceRelay.mark_input_failure()` and performs a pure `result_snapshot()` merge
for only those IDs. The snapshot takes continuity, latest published cutoff,
reason, and bounded backlog from final relay progress while preserving the
earlier publication outcome and target. It never calls `reconcile_all()` and
therefore cannot publish a second catch-up batch or alter an unrelated relay.

The new regression uses the real `LiveDecisionRuntime` and `PriceRelay` with:

```text
valid bar -> malformed suffix -> valid suffix
```

It proves:

- the valid prefix is `INSERTED` and publishes exactly one PriceUpdate;
- the malformed suffix is surfaced afterward and the later suffix is not
  accepted;
- the input cursor remains at the valid prefix and the stream is blocked;
- returned relay evidence preserves `PUBLISHED` and the valid prefix cutoff
  while reporting final `UNRESOLVED` input-failure continuity;
- internal relay progress has matching `UNRESOLVED` evidence;
- the first poll invokes relay reconciliation exactly once;
- an idle poll adds no publication and leaves the blocked relay unresolved.

Current validation after this remediation:

- focused D9D PriceRelay/runtime/risk surface: **34 passed**;
- `tests/decision`: **345 passed**;
- combined risk, signals/integration, commons, execution, and architecture
  guardrails: **402 passed**, one existing OpenTelemetry deprecation warning;
- scoped Ruff check: passed;
- scoped Ruff format check: **76 files already formatted**;
- compileall: passed;
- `git diff --check`: passed;
- scoped import, whitespace, and cache checks: passed.

No live/destructive certification or external-state operation was performed.
The missing `.env` remains the recorded
`LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT` gate. D10 and all later
deployment/cutover work remain unstarted.

No commit, merge, push, branch switch, reset, or restore was performed.

DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_READY_FOR_REVIEW
