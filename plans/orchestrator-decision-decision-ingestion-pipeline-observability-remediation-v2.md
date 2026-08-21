---
goal: Review the remediated ingestion-to-Decision observability implementation and identify any remaining blocker
stage: orchestrator-decision
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Needs Revision
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, ingestion, observability, remediation]
---

# Decision — ingestion-to-Decision observability remediation v2

## Decision

`REMEDIATE`

The first remediation successfully resolves the four previously identified blockers:

- `AlertSourceApp.DECISION = "decision"` is present and `decision` / `decision_app` normalize to the Decision identity;
- D12B is graduated to immutable historical-artifact validation without regenerating the protected artifact;
- generation-ID telemetry is removed from production metrics/dashboard;
- deterministic D9B/D9C hook tests now exercise real production wiring.

Independent validation reproduced:

- focused remediation suite: **69 passed**;
- full `tests/decision`: **492 passed**;
- protected D12B artifact SHA-256 remains exactly
  `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`.

## Remaining blocker — per-transaction lane telemetry undercounts multi-cutoff polls

### Verified behavior

`LiveDecisionRuntime.poll_once()` can process more than one trigger cutoff for the same lane in a single bounded poll. This is already protected by:

`tests/decision/test_d9b_live_runtime.py::test_signal_batch_processes_each_cutoff_before_capacity_eviction`

That path consumes two canonical input records and publishes two signals in one `poll_once()`.

The observability implementation currently records evaluation/publication counters only after building the final per-lane `LanePollResult` at the end of the poll via `_record_lane_results()`.

`_LanePollEvidence.begin()` resets transaction-local evidence on each cutoff, so only the **last** lane transaction survives into the final per-lane result.

Independent counterexample on the remediated worktree:

```text
inputs ['INSERTED', 'INSERTED']
published_entries 2
evaluation_metric_adds 1
publication_metric_adds 1
```

Therefore:

- `decision.lane.evaluation_total` undercounts real policy evaluations;
- `decision.publication.total` undercounts real publication acknowledgements;
- backlog/catch-up and any multi-cutoff batch can make Grafana throughput/outcome panels materially inaccurate.

This violates the frozen contract requiring every lane transaction/evaluation/publication outcome to be recorded at its existing runtime boundary.

## Required remediation

Move evaluation/publication telemetry from the final per-lane poll summary to the exact transaction boundaries inside `_attempt_lane()` (or an equally exact existing boundary).

Required semantics:

1. Record one evaluation counter for each actual policy evaluation result:
   - `SIGNAL`
   - `NO_SIGNAL`
   - `BLOCKED`
   - `INVALID`
2. Record one publication counter for each actual publication acknowledgement that exists.
3. A poll processing two cutoffs for one lane must produce two evaluation observations and, when both publish, two publication observations.
4. An idle poll must produce none.
5. A lane that is merely returned again in a later poll without a new evaluation must not increment counters.
6. Preserve existing business behavior and `LanePollResult` semantics.
7. Do not add transaction IDs, cutoff timestamps, stream IDs, or other high-cardinality labels.

Prefer separating the telemetry API into explicit `record_lane_evaluation(...)` and `record_publication(...)` methods if that gives a cleaner exact boundary than reconstructing partial `LanePollResult` objects. Keep changes minimal.

## Required regression

Extend the existing two-cutoff test (or add a tightly related observability regression) to assert:

```text
2 INSERTED inputs
2 actual signal publications
2 decision.lane.evaluation_total increments
2 decision.publication.total increments
```

Also preserve the existing idle-poll no-fabrication assertion.

## Non-goals

Do not reopen:

- alert identity design;
- D12B historical graduation;
- dashboard architecture;
- metric labels;
- lag semantics;
- generation telemetry;
- distributed tracing;
- service/storage/topology design.

Do not regenerate or modify the protected D12B artifact.

## Acceptance

After remediation, independently relevant evidence must show:

- multi-cutoff per-transaction counters are exact;
- focused observability/D9B/D9C/D12/alert suite passes;
- full `tests/decision` passes;
- D12B SHA remains exact;
- existing dashboard/alert/generation-metric protections remain intact;
- Ruff/format/compile/diff checks pass;
- no commit, merge, fast-forward, push, or primary-main mutation.

Terminal decision:

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_V2_REQUIRED`
