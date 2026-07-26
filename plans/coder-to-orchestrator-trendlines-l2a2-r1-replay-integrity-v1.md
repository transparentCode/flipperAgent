# Mature Trendlines L2-A2-R1 — Replay and Evidence Integrity

## 1. Disposition

L2-A2-R1 remediation is complete and remains uncommitted. Independent
truncation comparison, replay-point mutation detection, global summary bounds
and evidence semantic validation are implemented. No model, data, YAML,
provider, notebook or viewer behavior changed.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
starting commit: d33dfde560beb4b4d3048fd7ced2f3ba0b7af678
starting subject: feat: add trendline research foundation
```

## 3. Worktree proof

Validation used:

```text
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
RUFF=/Users/aloobhujia/.local/bin/ruff
PYTHONPATH=$PWD/src:$PWD
```

No dependencies or provider calls were used. Existing L2-A2 changes and both
L2-A2 handoffs remain uncommitted.

## 4. Independent-truncation reproduction

The original verifier rejected a valid comparison because independently
prepared full and truncated datasets necessarily had different parent
identities. The remediation compares compatible causal scope and shared-point
identities, not parent preparation or dataset IDs.

Reproduction used one deterministic full frame and an exact injected prefix:

```text
full preparation_id:       48d41e124f7b0ce73fbefedfbe8ac674af030f578e9343ff0c26528bd3f9bcd9
truncated preparation_id:  90d331a47cddaf92fe0a9ed8a4ee43c5286783de5680f798ebbaf44d8574197e
full dataset_id:           c2ce5d36e76efd67fc35b32f32135f4e9e7376ebb1f4a37ead449976e8a2120d
truncated dataset_id:      acb3f16d127078037025c8c0e37407c16d7b44d91d1d55c03fef96caf6fca46c
shared position:           22
shared prefix source_id:   97cc0d1833e3bfa2bcd189bd7b2bea6feec32657c339358f9b48e369a02e184b
```

The full replay ended at position 27; the independent prefix replay ended at
position 23. Shared-point verification passed. A changed shared-prefix volume
produced structured `ReplayFutureInvarianceError` detail with field
`prefix_source_id`.

## 5. Post-identity mutation reproduction

Before remediation, mutating nested boundary content after ID creation was
accepted, IDs stayed unchanged and evidence construction succeeded. Now a
mutation such as `boundary.interaction = "MUTATED_AFTER_ID"` is rejected by
`output_at()` with `TrendlineReplayIntegrityError`; evidence construction also
rejects the stale point.

## 6. Multi-timeframe-bound reproduction

The old summary used timeframe iteration order (`4h`, then `1h`) as its bounds.
The corrected summary uses true extrema across all recorded rows:

```text
reported/actual first_event_at:      2025-01-01T20:00:00+00:00
reported/actual last_event_at:       2025-01-06T16:00:00+00:00
reported/actual first_available_at:  2025-01-01T21:00:00+00:00
reported/actual last_available_at:   2025-01-06T20:00:00+00:00
```

Results are independent of prepared timeframe order.

## 7. Inconsistent-bundle reproduction

Before remediation, changing `selection.position` without changing the
selected binding, recomputing `bundle_id` and reading the bundle was accepted.
The reader now verifies content address first, then cross-field semantics, and
rejects the contradiction with `TrendlineEvidenceContractError`. Summary/row
contradictions are rejected the same way even with a recomputed bundle ID.

## 8. Independent invariance semantics

`verify_replay_future_invariance()` permits different preparation IDs, dataset
IDs, replay IDs and parent frame lengths. It requires the same asset,
research/pipeline configuration, timestamp semantics, availability source,
signal mode, compatible warm-up and a recorded shared position. It compares
event/availability times, prefix source, checkpoint, fit/boundary/signal IDs,
content, serialized output and replay-point identity.

## 9. Point content identity

Added:

```text
REPLAY_POINT_CONTENT_SEMANTICS_VERSION =
trendlines.research-replay-point-content.v1
```

`content_id` binds compact deterministic `TrendlineOutput`, boundary snapshot,
event/availability, prefix source reference and semantics version. It excludes
parent IDs, wall-clock time and full frames. `replay_point_id` now includes
`content_id`.

Shared independent point evidence:

```text
shared content_id:      225e94e9a182904600274db68920936593acb8aa825ea9938ff92d930f22e48c
shared replay_point_id: 750a16ecd99f83772820bb4ddfa7a1f6585049b82f699fd3fa16a7c4896c1a49
```

Full and truncated runs produced identical values.

## 10. Point integrity validation

`validate_replay_point_integrity()` verifies source/checkpoint horizons,
fit/boundary/signal stages, output-boundary equality, compact content digest
and replay-point digest. Public point access, serialization, invariance,
diagnostics, pivot inspection, summary and evidence construction validate before
trusting nested content. Bundle table construction validates each point once.

## 11. Invalid-output test correction

The mutation-based invalid-output fixture was removed. An early natural prefix
at position 19 now produces `fit_valid=False` during canonical execution and is
still recorded. No post-ID mutation is used to represent invalid model output.

## 12. Global summary bounds

`diagnostics._summary_from_rows()` computes event and availability extrema with
timestamp-aware `min`/`max` over every recorded row. Deterministic row ordering
and timeframe grouping remain unchanged.

## 13. Evidence semantic validation

`validate_evidence_bundle()` checks selection/binding identity, exactly one
selected snapshot coordinate, selected-row identity fields, selected-pivot
bindings, unique coordinates, pivot-row coverage, line/ray role totals,
diagnostic point references, summary counts/distributions and global temporal
extrema. Content addressing and semantic consistency are separate checks.

## 14. Deserialisation validation

`read_research_evidence_bundle()` performs:

```text
typed parse
bundle_id verification
semantic cross-field validation
return
```

Stale-ID tampering fails content-address validation. Recomputed-ID selection,
selected-pivot or summary contradictions fail semantic validation. Valid JSON
round-trips preserve deterministic serialized content.

## 15. Dedicated tests

Exactly eight R1 tests were added across the existing replay/evidence files:

```text
test_research_replay.py:    6
test_research_evidence.py: 2
total R1 additions:        8
```

Focused result:

```text
32 passed
```

## 16. Performance evidence

Deterministic synthetic benchmark:

```text
preparation_id:              5ebff6f5b442432942f5f64fc8da86a19787c1dfd25e3a0675c2da619d3c2c11
dataset_id:                  f30feb731a8f194ed662b6be3558bf7b9d315e1ffc6f17671601eaf909e14f4a
research_configuration_id:   ab6ec43eede637492f1e11bea6f4ae0cf72ef12045ee87265d648edb0cfc5853
```

Single-repetition final measurements, 19-bar warm-up:

| Workload | Executed | Recorded | Time |
|---|---:|---:|---:|
| Boundary replay | 512 | 512 | 15,557.959 ms |
| Signal replay | 256 | 256 | 3,295.815 ms |
| Snapshot diagnostic rows | 512 | 512 | 960.131 ms |
| Evidence bundle build | 512 | 512 | 1,541.849 ms |
| Semantic bundle validation | 512 | 512 | 2.643 ms |

Instrumentation:

```text
content hashes:                 512
integrity validations:          512
model executions, boundary:     512
model executions, signal:       256
provider calls:                 0
bundle serialized size:         2,537,540 bytes
```

Acceptance passed: boundary <=20 s, signal <=20 s, diagnostic rows <=1 s.
No full-frame hash, provider call, root-config re-resolution, per-row OHLCV
dictionary conversion or per-extractor validation was added.

## 17. Canonical regression

```text
427 collected
427 passed
```

## 18. Bridge regression

```text
Mocked Binance bridge: 8 passed
Provider calls: 0
```

## 19. Consumer regression

```text
Consumer/ingestion matrix: 71 passed
```

## 20. Offline regression

```text
Offline workflow group: 20 passed
```

## 21. Static validation

```text
Changed-file Ruff: passed
Compileall: passed
git diff --check: passed
Repository-local caches removed
```

## 22. Files changed

```text
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
M  src/libs/models/trendlines/workflows/research/__init__.py
M  src/libs/models/trendlines/workflows/research/contracts.py
M  src/libs/models/trendlines/workflows/research/replay.py
M  src/libs/models/trendlines/workflows/research/diagnostics.py
M  src/libs/models/trendlines/workflows/research/evidence.py
A  src/libs/models/trendlines/tests/test_research_replay.py
A  src/libs/models/trendlines/tests/test_research_evidence.py
?? plans/coder-to-orchestrator-trendlines-l2a2-causal-replay-v1.md
?? plans/coder-to-orchestrator-trendlines-l2a2-r1-replay-integrity-v1.md
```

## 23. Git status

Expected final status is exactly the paths listed in section 22. No application,
YAML, provider, notebook or viewer path changed. No commit was created.

## 24. Residual risks

- Replay remains in-memory; persistent evidence storage is out of scope.
- Replay runtime is model-dominated and grows with executed prefixes.
- RDP remains retrospective/revising and research-only.
- Multi-timeframe composition, optimisation, holdout access, promotion and
  presentation remain outside L2-A2.

## 25. Recommended next phase

```text
L2-B — Thin research notebook and TVLC presentation
```

Do not start L2-B in this phase.

## Conclusion

Independent full/truncated preparations now compare at shared causal points.
Replay points detect nested post-identity mutation. Summary bounds are global,
and persisted evidence requires both valid content addressing and semantic
cross-field consistency. No model algorithm, numerical parameter, notebook,
viewer, optimisation or promotion behavior changed.
