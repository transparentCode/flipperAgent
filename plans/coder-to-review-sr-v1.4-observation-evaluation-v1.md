---
goal: Implement SR-V1.4 causal observation traces and descriptive diagnostics
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Coder Agent
status: Ready
tags: [handoff, quant, sr, observation, evaluation, diagnostics, causality]
source_agent: Coder Agent
target_agent: Quant Review Agent
base_commit: d85a02ea5fa2aa5debba64234efc607220ccabba
source_branch: feature/sr-v1.3-checkpoint-replay
target_branch: feature/sr-v1.4-observation-evaluation
implementation_commit: 34f73d5
implementation_followup_commit: dfc1743
handoff_commit: b33d3d9
remediation_commit: 0bee141
---

# Coder To Review: SR-V1.4 Observation And Evaluation v1

## Scope Executed

Implemented approved SR-V1.4 from exact base commit `d85a02e` on
`feature/sr-v1.4-observation-evaluation`. Implementation commit:
`34f73d5 feat(sr): add observation evaluation`.

Focused identity-contract hardening commit:
`dfc1743 fix(sr): harden evaluation identity contracts`.

Coder handoff file introduced in commit `b33d3d9 docs(sr): add V1.4 review
handoff`.

Focused contract-remediation commit:
`0bee141 fix(sr): harden evaluation reconciliation`.

Scope is limited to immutable observation/evaluation contracts, pure trace
building, descriptive diagnostics, direct-constructor regression tests, and no
SR model or configuration behavior changes. No merge performed.

## Changes Made

Added exactly these production files:

- `src/libs/models/sr/evaluation/__init__.py`
- `src/libs/models/sr/evaluation/contracts.py`
- `src/libs/models/sr/evaluation/identity.py`
- `src/libs/models/sr/evaluation/trace_builder.py`
- `src/libs/models/sr/evaluation/diagnostics.py`

Added exactly these test files:

- `tests/models/sr/evaluation/__init__.py`
- `tests/models/sr/evaluation/test_contracts.py`
- `tests/models/sr/evaluation/test_trace_builder.py`
- `tests/models/sr/evaluation/test_diagnostics.py`
- `tests/models/sr/evaluation/test_causality.py`
- `tests/models/sr/evaluation/test_checkpoint_parity.py`

The remediation commit modifies exactly these existing evaluation files:

- `src/libs/models/sr/evaluation/contracts.py`
- `src/libs/models/sr/evaluation/diagnostics.py`
- `tests/models/sr/evaluation/test_contracts.py`
- `tests/models/sr/evaluation/test_diagnostics.py`

No production or test file outside the listed evaluation scope was modified.

### Public evaluation contracts and APIs

Only `libs.models.sr.evaluation` exports these names; `libs.models.sr` root
exports remain unchanged:

- `SR_EVALUATION_SCHEMA_VERSION = "1.0"`
- `ZoneRenderKind`: exact `LINE` and `BAND` values
- `SnapshotReference`
- `ObservedEvent`
- `ZoneObservation`
- `SREvaluationTrace`
- `ZoneDiagnostics`
- `SnapshotDiagnostics`
- `SRDiagnostics`
- `build_evaluation_trace(snapshots, resolved_config)`
- `compute_diagnostics(trace)`

All contracts are frozen dataclasses with derived deterministic IDs where
specified. Exact-type checks reject subclasses, lists, arbitrary iterables,
unknown ownership, duplicate identities, malformed hashes, invalid timestamps,
non-finite numbers, and inconsistent nested records.

### Visibility, geometry, and ordering

- `LINE` is derived only from `geometry.half_width == 0.0`.
- `BAND` is derived only from positive half-width geometry.
- Bounds are copied from immutable `ZoneGeometry` and remain positive, finite,
  and ordered.
- `atr_at_creation` is copied and validated as part of the self-contained zone
  observation and its identity payload.
- `visible_from` is exactly `definition.available_at`, never `created_at`.
- Live zones have `visible_until=None`.
- `BROKEN` and `EXPIRED` zones have `visible_until=runtime.updated_at`.
- Terminal visible windows and definition geometry remain frozen across retained
  observations.
- Snapshot references, zone observations, and events preserve caller snapshot
  order and authoritative per-snapshot order. Diagnostics order zones by first
  observation position, then `zone_id`.

### Deterministic identities

`evaluation.identity` delegates only to approved SR deterministic hashing and UTC
primitive helpers. Payloads are constructed explicitly; they contain canonical
UTC timestamp strings, enum string values, ordered tuples/lists, and semantic
fields only. `observation_id` excludes itself. `trace_id` includes schema, state
key, config hash, ordered provenance, snapshot IDs, observation IDs, and event
IDs. `diagnostic_id` and `diagnostics_id` include all semantic scalar and nested
diagnostic content required by the contracts.

### Trace and diagnostics semantics

`build_evaluation_trace` validates the complete exact snapshot tuple before
constructing output. It copies event identity and fields from authoritative
`SREvent` values, validates the existing domain `event_id`, copies all zone
definition/runtime values, and copies
`ResolvedSRConfig.field_provenance` and `resolved_config_hash` without creating
a second parameter registry or configuration model. It performs no replay,
engine call, I/O, clock access, sorting, repair, or mutation.

`compute_diagnostics` reads only `SREvaluationTrace`:

- exact six event counts;
- unique support/resistance zone counts;
- per-snapshot active, pending, live, newly-terminal, and event counts;
- max/final live counts;
- final runtime counters and age;
- first-touch timestamp/bar distance when not left-censored;
- fixed-order status-bar counts through terminal time, inclusive;
- explicit left/right censoring;
- no scores, ratios, thresholds, rankings, averages, or future-bar labels.

The remediation closes the reviewed contract gaps:

- Unknown event snapshot IDs are rejected with `ContractValidationError`
  before snapshot-position lookup.
- `atr_at_creation` is included in the frozen per-zone definition invariant.
- Terminal/live censoring and left-censored first-touch combinations are
  rejected when contradictory.
- Snapshot and zone diagnostic IDs are unique; per-snapshot terminal counts
  cannot exceed event counts; nested terminal totals reconcile with aggregate
  break/expiry counts.

## Dependency And Call Graph

```text
libs.models.sr.evaluation.__init__
  -> evaluation.contracts
  -> evaluation.diagnostics
  -> evaluation.trace_builder

evaluation.identity
  -> libs.models.sr.domain.identity deterministic_hash/UTC helpers

evaluation.contracts
  -> SR domain contracts/enums
  -> evaluation.identity

evaluation.trace_builder
  -> evaluation.contracts
  -> SR SRSnapshot/SREvent/ZoneRecord contracts
  -> ResolvedSRConfig

evaluation.diagnostics
  -> evaluation.contracts
  -> SR event/status/side enums
```

Evaluation never imports or calls `SREngine`, replay, serialization, lifecycle
rules, detection, association, adapters, YAML, storage, network, plotting,
legacy SR, trendline, regime, strategy, risk, execution, portfolio, or
optimization code. Runtime dependencies are standard library plus approved SR
domain/config contracts.

## Blast Radius Considered

- Existing SR root exports and import boundaries are unchanged.
- Existing domain, config, YAML, lifecycle, detection, association, replay, and
  serialization trees are clean against `d85a02e`.
- `git diff --quiet d85a02e -- configs src/libs/models/sr/config` passed.
- New package has no production callers outside its own public API and tests.
- No optional data, plotting, persistence, or external-service dependency was
  introduced.

## Validation Performed

Baseline before implementation:

- Full SR suite: `263 passed`.
- Trendline-family import boundary: `2 passed`.

Final:

- `.venv/bin/python -m pytest tests/models/sr/evaluation -q`
  - `31 passed`
- `.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/replay tests/models/sr/evaluation -q`
  - `121 passed`
- `.venv/bin/python -m pytest tests/models/sr -q`
  - `294 passed`
- `.venv/bin/python -m pytest tests/models/sr/lifecycle -q`
  - `55 passed`
- SR import boundaries plus YAML adapter boundary: `3 passed`.
- Trendline-family import boundary: `2 passed`.
- `ruff check src/libs/models/sr tests/models/sr`: passed.
- `.venv/bin/python -m compileall -q src/libs/models/sr`: passed.
- Public evaluation import with root-export isolation: `ok`.
- Config diff against `d85a02e`: clean.
- `git diff --check`: passed.
- Prohibited-import scan in evaluation production/tests: no matches.

Independent probes passed:

1. Delayed pivot visibility starts at `available_at`, not `created_at`.
2. Zero-width `LINE` and positive-width `BAND` observations.
3. Fakeout keeps zone ID, geometry, creation/availability/visibility fields;
   `BREACH_PENDING` returns to `ACTIVE` and fakeout count increases.
4. Terminal visible window and geometry remain frozen across retained snapshots.
5. Prefix trace preserves prior observations, events, and identities.
6. Checkpoint-resumed suffix matches uninterrupted snapshot, observation, event,
   identity, and per-snapshot diagnostic records.
7. Resolved config hash and all field provenance are copied unchanged.
8. Diagnostic totals reconcile nested records and exact event counts.
9. Left/right censoring is explicit; left-censored first-touch history is not
   fabricated.
10. Input tuple remains unchanged and invalid list input fails closed.
11. Direct constructors reject unknown event snapshots, ATR drift, diagnostic
    censoring contradictions, duplicate nested IDs, per-snapshot terminal
    overflow, and nested/aggregate terminal-count mismatches.

## Not Changed

- No SRState, SRSnapshot, SREvent, ZoneRecord, lifecycle, detection, association,
  replay, serialization, configuration, or YAML behavior was changed.
- No new YAML key, default, override, runtime layer, evaluation threshold, or
  parameter registry.
- No market data fetching, raw-data adapter, future-horizon label, return,
  excursion, PnL, Sharpe, drawdown, win rate, quality score, confidence,
  ranking, or trading-readiness claim.
- No chart/UI/HTML/SVG/image/plotting output.
- No CSV/Parquet/JSON/YAML writer, storage, cache, database, worker, or runtime
  integration.
- No tuning, grid search, Optuna, walk-forward, holdout, multi-timeframe,
  feature, ML, volume, order-book, regime, trendline, or V1.5 work.
- No schema migration, terminal pruning, event-history persistence, or legacy SR
  integration.
- Factory runtime annotation introspection follow-up remains deliberately
  deferred per the orchestrator non-goal.
- Pre-existing `.codebase-memory` artifacts and unrelated untracked plan drafts
  remain unstaged and uncommitted.

## Risks Or Follow-Up Items

- Evaluation output is descriptive evidence only; it does not establish
  predictive quality or trading readiness.
- Left-censored traces intentionally omit pre-trace touch/event history.
- Diagnostics assume authoritative snapshots retain terminal zones, as required
  by the approved V1.3 contract; no pruning or recovery path exists.
- Future phases may add artifact/report writers or plotting, but they must remain
  outside this standard-library-only evaluation surface and require a new
  approved handoff.
- V1.5 remains blocked pending rereview of this remediation. Do not begin
  market trials, data acquisition, plotting, features, tuning, storage, or
  strategy integration before Quant Review approval.
