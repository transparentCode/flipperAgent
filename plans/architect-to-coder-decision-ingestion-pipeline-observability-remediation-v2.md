---
goal: Fix per-transaction Decision observability undercounting in multi-cutoff polls
stage: architect-to-coder
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, observability, remediation]
---

# D9B observability exact transaction counting remediation

## Objective

Fix the single remaining observability defect in the existing isolated worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

The current implementation records Decision lane evaluation/publication counters from the final per-lane `LanePollResult` after `poll_once()`. A single poll may process multiple cutoffs for one lane, so transaction-local evidence is overwritten and counters undercount.

Do not redesign the observability package. Do not alter business/runtime semantics.

## Verified counterexample

The existing runtime path:

`tests/decision/test_d9b_live_runtime.py::test_signal_batch_processes_each_cutoff_before_capacity_eviction`

processes two cutoffs in one poll and produces two signal publications.

With current observability attached, independent review measured:

```text
inputs ['INSERTED', 'INSERTED']
published_entries 2
evaluation_metric_adds 1
publication_metric_adds 1
```

Root cause:

- `_LanePollEvidence.begin()` resets transaction-local policy/publication evidence for each cutoff;
- `_record_lane_results()` runs only once on the final per-lane poll summary.

## Scope

Expected production changes should be limited to:

```text
src/apps/decision_app/observability.py
src/apps/decision_app/runtime/live.py
```

Expected test change:

```text
tests/decision/test_d9b_live_runtime.py
```

Only touch another file if strictly necessary for typing/test compatibility and explain why in the handoff.

## Required implementation semantics

Record telemetry at the actual lane transaction boundaries, not at final poll summarization.

### Evaluation

Every successful policy evaluation invocation that returns one of:

```text
SIGNAL
NO_SIGNAL
BLOCKED
INVALID
```

must increment `decision.lane.evaluation_total` exactly once using the existing bounded lane/asset/timeframe/outcome labels.

### Publication

Every real publication acknowledgement must increment `decision.publication.total` exactly once using the existing bounded labels.

Do not fabricate a publication outcome for `NO_SIGNAL`.

If publication acknowledgement occurred but a later finalization/checkpoint/effect-progress step fails, the publication acknowledgement metric must still reflect the real publication that happened.

### Poll semantics

A single `poll_once()` may process multiple cutoffs for the same lane. Each actual evaluation/publication must be counted individually.

An idle poll or a poll returning a lane state without a new evaluation must not increment evaluation/publication counters.

### API shape

Prefer explicit observability methods such as:

```text
record_lane_evaluation(...)
record_publication(...)
```

if they make the exact boundary clear and avoid constructing artificial `LanePollResult` values. Remove or stop using the poll-summary `_record_lane_results()` path for these counters.

Do not add IDs/timestamps/reasons as metric labels.

## Preserve all resolved remediation work

Do not regress:

- `AlertSourceApp.DECISION` and Decision health source mapping;
- D12B immutable historical graduation;
- protected D12B artifact SHA
  `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`;
- generation-ID metric removal;
- dynamic dashboard variables;
- direct-XREAD closed-interval lag semantics;
- cache-only gauge callbacks;
- no new service/storage/tracing framework.

## Tests

Extend `test_signal_batch_processes_each_cutoff_before_capacity_eviction` or add one tightly adjacent regression with observability attached.

It must prove in one `poll_once()`:

```text
input INSERTED count             = 2
actual signal stream entries     = 2
evaluation counter increments    = 2
publication counter increments   = 2
```

Assert the outcomes are the expected values as well.

Keep/extend the existing idle-poll assertion proving no duplicate/fabricated evaluation or publication increments.

Also retain the single-transaction observability hook test.

## Validation

Run at minimum:

```text
pytest -q tests/decision/test_observability.py \
  tests/decision/test_d9b_live_runtime.py \
  tests/decision/test_d9c_service.py \
  tests/decision/test_d12_decision_only_topology.py \
  tests/alerts/test_reconciler.py \
  tests/alerts/test_settings.py

pytest -q tests/decision
```

Verify:

```text
shasum -a 256 artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json
```

must remain:

`64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`

Run Ruff, format check, compileall, and `git diff --check` using the same environment that succeeded in the prior coder validation.

A second nine-service real telemetry run is not required if the only production change is relocation of in-process counter hooks and all real exporter/dashboard evidence from remediation v1 remains otherwise unchanged. If the implementation changes metric names/labels or dashboard queries, rerun the real telemetry topology.

Do not commit, merge, fast-forward, push, or modify primary `main`.

## Handoff

Create:

`plans/coder-to-orchestrator-decision-ingestion-pipeline-observability-remediation-v2.md`

Report exact changed files, the new exact hook locations, multi-cutoff regression evidence, focused/full Decision results, D12B SHA, static checks, and whether a new real stack run was necessary.

End exactly with:

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_V2_READY_FOR_REVIEW`
