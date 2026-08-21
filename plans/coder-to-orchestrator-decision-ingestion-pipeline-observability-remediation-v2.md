# Coder-to-orchestrator: Decision observability v2 remediation

## Result

The exact transaction-counting remediation is complete in:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

Base/worktree HEAD remains:

`444c480aa65634fcb6c736dab6c449076a08f871`

Primary `main` was not modified. No commit, merge, fast-forward, or push was
performed.

## v2 delta

Only these implementation/test files changed for v2:

- `src/apps/decision_app/observability.py`
- `src/apps/decision_app/runtime/live.py`
- `tests/decision/test_d9b_live_runtime.py`

The existing v1 observability, alert, dashboard, documentation, and D12B
historical-archive changes remain intact.

## Exact hook locations

`LiveDecisionRuntime._attempt_lane()` now records:

- `record_lane_evaluation()` immediately after a successful policy evaluation
  returns `SIGNAL`, `NO_SIGNAL`, `BLOCKED`, or `INVALID`;
- `record_publication()` immediately after a valid signal or shadow publisher
  acknowledgement returns, before finalization/checkpoint/effect-progress
  handling.

The former final per-lane poll-summary counter path was removed. Poll summaries
remain bounded evidence only and no longer determine evaluation/publication
counter totals. Therefore publication acknowledgements remain counted even if a
later finalization or durability step fails, while `NO_SIGNAL` creates no
fabricated publication metric.

Metric names, labels, dashboard queries, and generation-ID removal are
unchanged.

## Multi-cutoff regression

`tests/decision/test_d9b_live_runtime.py::test_signal_batch_processes_each_cutoff_before_capacity_eviction`
now attaches `DecisionObservability` and processes two cutoffs in one
`poll_once()`.

Measured assertions:

```text
input dispositions             INSERTED, INSERTED
signal stream entries          2
evaluation counter adds        2 (SIGNAL, SIGNAL)
publication counter adds       2 (PUBLISHED, PUBLISHED)
idle follow-up additions       0 evaluation, 0 publication
```

The existing single-cutoff hook test remains green.

## Validation

- Focused observability/D9B/D9C/D12/alerts suite: **69 passed**.
- Full `tests/decision`: **492 passed**.
- Ruff `check --no-cache`: passed.
- Ruff `format --check`: passed.
- `compileall -q src tests`: passed.
- `git diff --check`: passed.
- D12B protected artifact unchanged:
  `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`.

No nine-service rerun was necessary: v2 only relocates in-process counter
hooks and preserves metric names, labels, dashboard queries, exporter wiring,
and the previously validated disposable topology.

## Self-review

The runtime still executes the same evaluations, publications, finalization,
checkpoint, and effect-progress semantics. The change only observes each real
transaction at its actual boundary; idle polls and summary-only states do not
increment counters. No new service, storage, tracing contract, metric label,
or architecture surface was introduced.

## Terminal

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_V2_READY_FOR_REVIEW`
