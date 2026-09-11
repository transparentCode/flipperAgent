# ABORTED_HARNESS_RECOVERY_ACK_BEFORE_MEASUREMENT

2026-09-08: User authorized stopping the retrying harness and correcting its
recovery-response check. Launchd bootout completed at 03:07:38Z. Guard records
GUARD_SIGNAL / exit143 and lifecycle TERMINAL. No RUN_STATE.json was created;
measurement never started. Frozen tooling remains unchanged.

Root cause: startup rejected valid recovery HTTP200 snapshots with state=stopped
while a newly installed supervisor task had not yet run. Consequently BTC recovery
repeated and neither ETH preparation nor resource-server startup was reached.

Final manual snapshot before isolated-project cleanup:

- Ingestion running/LIVE, desired running, last_error null, six enabled assets.
- Outbox unpublished rows: 0.
- Ingestion ID b120e2cfca66fb2323e81654a59f0cf2d4724b67739d57c13c7921368e6d4f38;
  start 2026-09-08T02:15:10.118604589Z, restart0, OOMfalse; RSS227.3MiB/512MiB.
- DB ID edb91ad27788471a1e202ab2d1632c43d367eba2e12c6eca5a2390bc8dc0873b;
  start 2026-09-08T02:14:59.503427417Z, restart0, OOMfalse; RSS194.7MiB/1GiB.
- Broker ID 684c20fd029742f3ed1f1c3b93fa9cf64778cebd58eeceb70bff3f83c172104f;
  start 2026-09-08T02:14:59.378819542Z, restart0, OOMfalse; RSS32.9MiB/256MiB.
- Decision and measurement-infrastructure containers were not created.
- CBM e2329c8af97feb51bd0fef1f01051306ce3de034305a0fa8d2a1f4dc6a470011
  remains running since 2026-09-07T13:10:06.118751836Z, restart0, OOMfalse.
- GitNexus dd9595e4eff41f372e93d028b569f92c4b988ca50a3b162564e80201d2d0e6e0
  remains running since 2026-09-07T13:10:05.906294628Z, restart0, OOMfalse.
- Hindsight 74cedeece696cc1f9497d49ddfa1d828f1a98edcbc88b8c4f1b2a0d7993f8add
  remains exited, restart0, OOMfalse; deliberately not started.

Cleanup uses the frozen stop script: capture bounded raw logs, then remove only
this isolated project containers/network without deleting volumes. Corrected
attempt is separate 20260908T030738Z; no evidence or duration carried forward.
