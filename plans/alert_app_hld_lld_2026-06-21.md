# Alert App Architecture Plan (HLD + LLD)

Date: 2026-06-21
Stage: Implemented MVP with validated handoff
Scope: `alert_app` for flipperAgent pipeline operations and delivery

---

## 1. Objective

Build `alert_app` as the operational alerting service for the flipperAgent pipeline.

It must:
- consume operational facts from pipeline apps
- convert them into normalized alert events and incidents
- deduplicate, throttle, escalate, recover, silence, and acknowledge alerts
- route notifications to multiple channels such as Telegram, webhook, Slack later
- expose an internal API for current alert state and audit history

It must **not**:
- become the source of truth for asset lifecycle or runtime state
- parse raw container logs as its primary signal source
- let upstream apps decide alerting policy

---

## 2. Position in the System

Current pipeline:
- scrape -> ingest -> signal -> strategy -> risk -> execution -> portfolio

`alert_app` sits beside the pipeline as an **operations control plane consumer**.

It reads:
- lifecycle events
- runtime status snapshots
- failure streams
- freshness signals
- app health signals

It writes:
- incidents
- notification jobs
- ack / silence state
- optional incident history rows

### 2.1 Ownership boundaries

Canonical ownership remains unchanged:
- `ingestion_app` owns canonical asset lifecycle and manifest projection
- each app owns its own runtime state and local failure streams
- `alert_app` owns only:
  - normalized alert policy
  - incident lifecycle
  - notification routing
  - dedupe / cooldown / escalation

---

## 3. High-Level Design (HLD)

## 3.1 Sources consumed by alert_app

### A. Lifecycle stream
- stream: `asset:lifecycle`
- producer: `ingestion_app`
- purpose:
  - detect add/remove/pause/resume transitions
  - detect assets stuck in transitional states
  - correlate incidents to asset lifecycle intent

### B. Ingestion runtime events
- stream: `ingestion:events`
- producer: `ingestion_app`
- purpose:
  - gap-fill partial failure
  - websocket reconnect storms
  - warmup timeout
  - runtime degraded / failed events

### C. Per-app observability state
- current examples already exist in app observability services
- purpose:
  - stale data detection
  - worker state detection
  - health polling fallback when streams are quiet

### D. Execution failures
- stream family: `execution:failures:{ASSET}`
- producer: `execution_app`
- purpose:
  - hard trading failures
  - retry exhaustion
  - broker / venue / validation failures

### E. Future sources
- scraper provider failures
- risk rejection anomaly spikes
- portfolio drift anomalies
- API health endpoint degradations

---

## 3.2 Alerting model

The app should use a 3-stage model:

1. **Raw operational fact**
   - observed from streams or polling
   - example: `execution failure for BTCUSDT`

2. **Normalized alert event**
   - converted into a uniform internal schema
   - example: `event_type=execution_failure`, `severity=critical`

3. **Incident**
   - long-lived alert state after dedupe/grouping
   - example: one incident for repeated execution failures on BTCUSDT

This separation avoids overloading stream payloads with policy decisions.

---

## 3.3 Alert categories

Initial categories:
- `lifecycle_transition_timeout`
- `worker_stuck_warming`
- `runtime_degraded`
- `runtime_failed`
- `missing_expected_event`
- `freshness_breach`
- `execution_failure`
- `scraper_provider_failure`
- `repeated_retry_exhausted`
- `health_endpoint_degraded`

Initial severities:
- `info`
- `warning`
- `critical`

---

## 3.4 Alert routing model

Support multiple logical destinations from day 1.

Planned routing groups:
- `system_alerts`
- `trading_alerts`
- `execution_alerts`
- `scraper_alerts`
- `dev_debug`

Routing dimensions:
- by app (`ingestion`, `signal`, `strategy`, `risk`, `execution`, `portfolio`, `scraper`)
- by severity
- by event category
- by asset / timeframe scope
- by environment (`dev`, `paper`, `prod`)

Telegram is just one delivery transport.
The routing model must stay transport-agnostic.

---

## 3.5 Rate limiting and dedupe model

Alert noise control is mandatory.

Need four layers:

### A. Event dedupe
Suppress exact duplicate normalized events for a short TTL.
- key basis: `(event_type, scope, fingerprint)`
- TTL example: `60s`

### B. Incident cooldown
If incident is already open, do not reopen it repeatedly.
- only bump counters / timestamps
- optional re-notify after cooldown

### C. Delivery rate limiting
Per notification route / channel.
- example: max `5` sends per `5m` for warning alerts
- example: no cap for first critical event, but cap repeats

### D. Escalation pacing
If unresolved:
- warn once
- re-notify after `N` minutes
- escalate route after `M` intervals

---

## 3.6 Recovery model

Every incident must have explicit recovery semantics.

Incident states:
- `open`
- `acked`
- `silenced`
- `resolved`

Resolution paths:
- explicit recovery event observed
- stale incident automatically resolved after health restoration window
- manual operator resolve optional

Important rule:
- silence suppresses notifications, not incident state updates
- ack marks ownership, not resolution

---

## 3.7 Storage strategy

Use split storage:

### Hot path: Valkey
For:
- current incident state
- dedupe keys
- cooldown windows
- rate-limit counters
- pending notification jobs
- ack/silence quick lookup

### Durable path: Postgres / Timescale
For:
- incident history
- notification audit log
- acknowledgment audit trail
- silence policy changes
- recovery durations / MTTR analytics

Reason:
- Valkey handles fast policy decisions
- Postgres gives auditability and reporting

---

## 3.8 API surface

Expose internal app API similar to other apps.

Minimum endpoints:
- `GET /alerts/health`
- `GET /alerts/summary`
- `GET /alerts/incidents`
- `GET /alerts/incidents/{incident_id}`
- `POST /alerts/incidents/{incident_id}/ack`
- `POST /alerts/incidents/{incident_id}/resolve`
- `GET /alerts/silences`
- `POST /alerts/silences`
- `DELETE /alerts/silences/{silence_id}`
- `GET /alerts/routes`
- `GET /alerts/notifications`

---

## 3.9 Deployment model

Single container app is enough initially.

Subcomponents inside `alert_app`:
- runtime stream consumer
- periodic reconciler
- API server
- notification dispatcher

This can run in one container first, later split if volume grows.

---

## 4. Low-Level Design (LLD)

## 4.1 Proposed folder structure

```text
src/apps/alert_app/
  __init__.py
  main.py
  settings.py
  state.py
  contracts.py
  factories.py
  bootstrap.py
  runtime/
    __init__.py
    runner.py
    consumer.py
    reconciler.py
  ingestion/
    __init__.py
    normalizers.py
    subscribers.py
  rules/
    __init__.py
    engine.py
    severity.py
    dedupe.py
    cooldown.py
    escalation.py
    routing.py
    freshness.py
  incidents/
    __init__.py
    models.py
    keys.py
    store.py
    repository.py
    service.py
  notifications/
    __init__.py
    dispatcher.py
    queue.py
    router.py
    transports/
      __init__.py
      base.py
      webhook.py
      telegram.py
  api/
    __init__.py
    app.py
    main.py
    routes.py
    dependencies.py
  observability/
    __init__.py
    service.py
```

---

## 4.2 Internal contracts

## 4.2.1 NormalizedAlertEvent

Fields:
- `event_id`
- `source_app`
- `source_kind` (`stream`, `status_poll`, `health_poll`, `synthetic_check`)
- `event_type`
- `severity`
- `asset` nullable
- `timeframe` nullable
- `scope_key`
- `fingerprint`
- `title`
- `message`
- `detail`
- `observed_at`
- `raw_ref`

Purpose:
- canonical internal alert candidate

## 4.2.2 AlertIncident

Fields:
- `incident_id`
- `scope_key`
- `event_type`
- `severity`
- `state`
- `source_app`
- `asset`
- `timeframe`
- `first_seen_at`
- `last_seen_at`
- `last_notified_at`
- `repeat_count`
- `fingerprint`
- `title`
- `message`
- `detail`
- `acked_by`
- `acked_at`
- `silenced_until`
- `resolved_at`

## 4.2.3 NotificationJob

Fields:
- `job_id`
- `incident_id`
- `route_key`
- `transport`
- `destination`
- `status`
- `attempt_count`
- `next_attempt_at`
- `payload`
- `created_at`
- `sent_at`
- `last_error`

---

## 4.3 Valkey keyspace design

### Streams
- `alerts:events`
- `alerts:incidents`
- `alerts:notifications`

### Hot state hashes / keys
- `alerts:incident:{incident_id}`
- `alerts:incident_open:{scope_key}:{event_type}`
- `alerts:silence:{silence_id}`
- `alerts:ack:{incident_id}`
- `alerts:dedupe:{fingerprint}`
- `alerts:ratelimit:{route_key}:{bucket}`
- `alerts:cooldown:{incident_id}`

### Optional indexes
- `alerts:index:open`
- `alerts:index:severity:{severity}`
- `alerts:index:source_app:{app}`

---

## 4.4 SQL tables

### `alert_incidents`
- primary durable incident record

### `alert_incident_events`
- append-only history of event observations / state transitions

### `alert_notifications`
- notification delivery audit log

### `alert_silences`
- silence definitions and audit metadata

### `alert_acknowledgements`
- ack actor/time/comment history

---

## 4.5 Runtime components

## 4.5.1 `runtime.consumer`
Consumes operational sources and emits normalized events.

Responsibilities:
- subscribe to known streams
- decode source payloads
- call source-specific normalizers
- hand off to rules engine

Initial sources:
- `asset:lifecycle`
- `ingestion:events`
- `execution:failures:*`

## 4.5.2 `runtime.reconciler`
Periodic synthetic checker.

Responsibilities:
- poll observability services / Valkey state
- compute freshness / staleness breaches
- emit normalized events when thresholds violated
- emit recovery events when healthy again

This is how we catch silent failures.

## 4.5.3 `rules.engine`
Core policy executor.

Responsibilities:
- derive severity
- compute fingerprint
- dedupe
- open/update/resolve incidents
- create notification jobs
- enforce silence / ack / cooldown / escalation

## 4.5.4 `notifications.dispatcher`
Consumes notification jobs and sends outbound messages.

Responsibilities:
- transport selection
- per-route rate limiting
- retry with backoff
- audit success/failure

---

## 4.6 Source normalizers

Each source gets a strict normalizer.

Examples:

### Lifecycle normalizer
Input:
- asset lifecycle event
Output:
- transition warning / timeout seed event

### Ingestion runtime normalizer
Input:
- `IngestionRuntimeEvent`
Output:
- `runtime_degraded`, `retry_exhausted`, `warmup_timeout`

### Execution failure normalizer
Input:
- execution failure stream event
Output:
- `execution_failure`

### Health/freshness normalizer
Input:
- last seen timestamps / lag
Output:
- `freshness_breach`

---

## 4.7 Routing config model

Add new config file:
- `configs/alerts.yaml`

Sections:

### `routes`
Defines route groups.

Example concepts:
- `system_alerts`
- `trading_alerts`
- `execution_alerts`
- `scraper_alerts`
- `dev_debug`

Each route:
- `enabled`
- `transport`
- `destination`
- `severity_min`
- `burst_limit`
- `burst_window_seconds`
- `renotify_seconds`

### `policies`
Maps event types / apps / severities to routes.

### `silences`
Optional bootstrap silences.

### `freshness`
Defines staleness thresholds by app or stream.

Examples:
- signal feature lag > 20m
- strategy signal lag > 30m
- execution fills idle while orders failing

---

## 4.8 Telegram support design

Telegram support should be built as transport abstraction.

Not hardcoded single channel.

### Telegram transport config per route
- `bot_token`
- `chat_id`
- `thread_id` optional
- `parse_mode`

This naturally supports multiple Telegram channels:
- one bot, many chats
- or multiple bots if needed later

---

## 4.9 Rate limiting design details

Use token-bucket or fixed-window counters in Valkey.

Recommended initial implementation:
- fixed-window counters
- route-scoped keys with TTL

Levels:
1. `event_dedupe_ttl_seconds`
2. `incident_renotify_seconds`
3. `route_burst_limit`
4. `route_burst_window_seconds`
5. `critical_bypass_first_send` boolean

---

## 4.10 Incident state machine

```text
new_event
  -> open_incident
  -> notify

repeat_event while open
  -> update counters
  -> maybe renotify

operator_ack
  -> acked

silence_applied
  -> silenced (notifications suppressed)

recovery_event
  -> resolved
```

Rules:
- `acked` can still receive state updates
- `silenced` suppresses delivery only
- `resolved` closes open incident binding

---

## 4.11 Freshness / silent failure checks

This is one of the most important pieces.

Initial checks:
- ingestion pair stuck `WARMING` too long
- signal pair no feature updates beyond threshold
- strategy pair no signal updates beyond threshold
- execution failures increasing without successful fills
- scraper jobs failing repeatedly

Each checker should produce:
- breach event
- recovery event

---

## 4.12 API response model

### `/alerts/summary`
- open incident count
- incidents by severity
- incidents by source app
- muted incidents count
- notification failures count

### `/alerts/incidents`
Supports filters:
- state
- severity
- app
- asset
- timeframe
- event_type

### `/alerts/routes`
- resolved route map
- rate-limit config
- transport status

### `/alerts/notifications`
- queued
- sent
- failed
- retrying

---

## 5. Non-Functional Requirements

## 5.1 Reliability
- app should not crash on malformed source events
- one bad transport send must not block incident creation
- notification delivery must be retriable

## 5.2 Idempotency
- normalized events must be deduped
- repeated lifecycle / failure events must not create incident explosions

## 5.3 Performance
- should handle bursty failure storms without unbounded stream amplification
- no synchronous external notification call in hot incident path

## 5.4 Security
- secrets only from config / env / secret mounts
- do not leak full sensitive order/account payloads into alerts
- sanitize notification payloads

## 5.5 Operability
- alert_app itself needs health + runtime status
- notification transport failures must themselves surface as incidents

---

## 6. Implementation Phases

## Phase 1 — Contracts + config
- add `configs/alerts.yaml`
- add alert contracts/models
- add Valkey key helpers
- add SQL schema

## Phase 2 — Incident engine MVP
- source consumers:
  - lifecycle
  - ingestion events
  - execution failures
- normalized event pipeline
- incident store/service
- dedupe + cooldown

## Phase 3 — API
- summary
- incidents list/detail
- ack
- silence CRUD

## Phase 4 — Reconciler / freshness
- stale runtime detection
- silent failure detection
- recovery emission

## Phase 5 — Notifications
- webhook transport first
- Telegram multi-channel transport next
- delivery rate limiting and retry

## Phase 6 — E2E / Docker
- inject failures
- verify incident creation
- verify dedupe
- verify silence / ack
- verify recovery
- verify rate limit and multi-route delivery

---

## 7. Testing Plan

### Unit tests
- normalizers
- rules engine
- dedupe logic
- escalation logic
- routing logic
- rate-limit logic
- silence / ack transitions

### Integration tests
- Valkey incident open/update/resolve flow
- SQL persistence flow
- notification queue retry flow

### Docker E2E
- ingestion event -> alert incident
- execution failure -> critical incident
- stale signal / strategy lane -> freshness incident
- incident recovery after healthy event

---

## 8. Key Decisions Locked Before Implementation

1. `alert_app` is **fact-consumer + policy-owner**, not source-of-truth owner.
2. Upstream apps emit runtime facts, not alert decisions.
3. Multi-channel routing is first-class in architecture.
4. Rate limiting and dedupe are mandatory in MVP design.
5. Valkey is hot state; Postgres is durable audit.
6. Silent failure detection must exist via reconciler, not streams alone.
7. Telegram is a transport plugin, not the alert model itself.

---

## 9. Open Questions Before Coding

These are small, implementation-grade choices, not architecture blockers:
- should incident history live in Timescale or plain Postgres tables?
- should first delivery transport be webhook or Telegram?
- do we want operator auth on ack/silence API immediately or later behind internal network trust?
- should `alert_app` consume app status by polling API endpoints, by Valkey directly, or hybrid? (recommended: hybrid, Valkey first, API fallback)

---

## 10. Implementation Status

### Implemented

- `configs/alerts.yaml` runtime, route, policy, freshness, and health-check contract
- app scaffold under `src/apps/alert_app/`
- incident contract models, Valkey hot-state store, and SQL schema
- lifecycle, ingestion runtime, and execution-failure consumers
- incident API including detail, ack, resolve, silence create/delete, routes, and notifications
- reconciler checks for:
  - ingestion warming/backfilling timeout + recovery
  - signal freshness breach + recovery
  - strategy freshness breach + recovery
  - scraper job failure + recovery
  - configured health-check breach + recovery
- webhook + Telegram transports with retry and route burst limiting
- Docker-backed alert validation

### Validated

- `PYTHONPATH=src .venv/bin/pytest tests/alerts -q`
- `PYTHONPATH=src .venv/bin/pytest tests/alerts/test_docker_alerts.py -q`

### Deferred

- richer multi-step escalation ladders beyond current renotify + burst throttling
- Slack transport
- more source-specific integrations from `risk_app` / `portfolio_app`
- broader live toggling tests for health-breach recovery across additional services

