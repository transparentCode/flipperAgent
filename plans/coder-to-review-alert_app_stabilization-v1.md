# Coder → Review: alert_app Stabilization Findings

## Scope Executed

Implemented the three alert_app stabilization findings from the orchestrator handoff, scoped to `alert_app` plus focused tests, plus a blocking dispatcher bookkeeping fix raised by review:

1. **last_notified_at advanced before transport success** — `record_event` no longer mutates `last_notified_at`. The dispatcher now calls `incident_service.mark_notified(...)` only after a transport returns successfully.
2. **Recovery resolves state without updating title or clearing stale failure detail keys** — recovery events now overwrite `title`, `summary`, and `detail` (replacing merged failure details with the recovery event's clean detail).
3. **Ingestion success-event suppression duplicated between consumer allowlist and normalizer default-failure mapping** — removed the consumer allowlist; `normalize_ingestion_runtime_event` now returns `None` for any `IngestionEventType` that is not an explicitly mapped failure. The consumer skips `None` normalized events.
4. **Blocking dispatcher bookkeeping bug (review follow-up)** — `mark_notified` now runs in the `else` branch after a successful send, with its own exception handler. A post-send bookkeeping failure logs a warning but does not reclassify the delivery as `failed` and does not record a duplicate delivery.

## Files and Symbols Changed

| File | Change |
|------|--------|
| `src/apps/alert_app/incidents/service.py` | New `mark_notified(...)` method; new incidents start with `last_notified_at=None`; existing-incident updates no longer touch `last_notified_at`; recovery path now updates `title` and replaces `detail`. |
| `src/apps/alert_app/notifications/dispatcher.py` | Added optional `incident_service` constructor arg; worker records `sent`, then calls `mark_notified` in an `else` branch with isolated exception handling so bookkeeping failures do not flip the delivery to `failed`. |
| `src/apps/alert_app/runtime/runner.py` | Wired `incident_service` into `AlertNotificationDispatcher`. |
| `src/apps/alert_app/runtime/normalizers.py` | `normalize_ingestion_runtime_event` return type is now `NormalizedAlertEvent \| None`; returns `None` for unmapped (non-failure) event types. |
| `src/apps/alert_app/runtime/consumer.py` | Removed `_NON_INCIDENT_INGESTION_EVENTS` allowlist and `IngestionEventType` import; skips normalized ingestion events that are `None`. |
| `configs/alerts.yaml` | Enabled `system_alerts` webhook route so default/execution/scraper policies resolve at least one enabled route in stock env. |
| `tests/alerts/test_incident_service.py` | Extended helper to accept `title`/`detail`; added `mark_notified` test; asserted recovery title/detail replacement and `last_notified_at` behavior. |
| `tests/alerts/test_dispatcher.py` | Added `_FakeIncidentService` and `_FailingMarkNotifiedIncidentService`; asserted `mark_notified` is invoked on success, not on transport failure, and that a `mark_notified` failure leaves the delivery as `sent` with no duplicate `failed` record. |
| `tests/alerts/test_normalizers.py` | Added test confirming success ingestion events (`COMMAND_ACCEPTED`, `GAP_FILL_COMPLETED`, `ASSET_PURGE_COMPLETED`) normalize to `None`. |

## Blast Radius Considered

- **Callers of `record_event`**: consumer and reconciler are unaffected; they still receive `(incident, should_notify)`.
- **Callers of `normalize_ingestion_runtime_event`**: only the consumer uses it; return-type change is handled.
- **Dispatcher callers**: `runner.py` now passes `incident_service`. Existing dispatcher tests updated; constructor arg is optional for backward compatibility.
- **Recovery behavior**: Any recovery event (reconciler, ingestion runtime, execution) now replaces `detail` instead of merging. This is the intended fix.
- **Renotification semantics**: New incidents no longer seed `last_notified_at`; notifications are attempted on creation and each renotify-window event until a transport succeeds. This matches the requirement that failed deliveries must not suppress windows.
- **Bookkeeping failure isolation**: A failure in `mark_notified` no longer poisons the delivery record. The delivery stays `sent` and observability remains consistent; only `last_notified_at` remains stale until the next successful bookkeeping call.

## Validation Performed

```bash
.venv/bin/python -m pytest tests/alerts/ -v --ignore=tests/alerts/test_docker_alerts.py
```

Result: **33 passed, 0 failed**.

- All touched tests pass:
  - `tests/alerts/test_incident_service.py` (4/4)
  - `tests/alerts/test_dispatcher.py` (4/4)
  - `tests/alerts/test_normalizers.py` (4/4)
  - `tests/alerts/test_consumer.py` (2/2)
  - `tests/alerts/test_routing.py` (1/1) — fixed by enabling `system_alerts` in config

Lint: `ruff` is not installed in the active `.venv`, so it could not be run.

## Not Changed

- No changes to regime/trendline work.
- No broad alert architecture changes beyond the three findings plus the route-enablement config fix flagged by review.
- `IngestionEventType` enum in `src/libs/contracts/ingestion.py` was not modified; only its consumers were adjusted.
- Telegram auto-disable behavior in `settings.py` was preserved; only the webhook route was enabled.
- Docker E2E alert tests were not run (require running stack).

## Risks or Follow-Up Items

1. **Notification retry spam**: With `last_notified_at=None` for new incidents and after failed deliveries, every eligible event triggers a notification attempt until one succeeds. If a transport is down for an extended period, this creates more attempts than before. A future improvement could add exponential backoff or per-route retry state, but that is out of scope for these findings.
2. **ruff unavailable**: Linting could not be verified in this environment; recommend running `ruff check src/apps/alert_app tests/alerts` once available.
3. **Ingestion recovery via success events**: The current change preserves the existing behavior of not auto-recovering ingestion failure incidents from success events (e.g., `GAP_FILL_COMPLETED` does not resolve a `GAP_FILL_FAILED` incident). If auto-recovery is desired, it would require a deliberate design expansion.
4. **Webhook destination**: Enabling `system_alerts` means the runtime will attempt POSTs to `http://localhost:8088/alerts/system`. In the Docker stack this endpoint must be reachable; in local dev without the target service, deliveries will record `failed` status but incidents will still be created.
