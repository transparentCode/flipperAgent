# L2-A2-R2 Diagnostic Integrity Handoff

## 1. Disposition

READY_FOR_L2B_RESEARCH_NOTEBOOK

L2-A2-R2 closes persisted diagnostic-row coordinate, identity, and summary-consistency gaps. No commit was created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Starting HEAD: `d33dfde560beb4b4d3048fd7ced2f3ba0b7af678`
- Starting commit: `d33dfde feat: add trendline research foundation`

## 3. Worktree proof

The existing uncommitted L2-A2/R1 scope was preserved. R2 changed only the existing research replay/diagnostics/evidence package, its tests and documentation, plus this handoff. No app, YAML, provider, notebook, viewer, model or replay-execution scope was added.

Environment:

```text
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
RUFF=/Users/aloobhujia/.local/bin/ruff
PYTHONPATH=$PWD/src
provider calls: 0
```

## 4. Line-reassignment reproduction

Before R2, a valid line row was assigned another recorded point's valid `replay_point_id`, with the remaining row fields unchanged. The bundle hash was recomputed and the reader returned:

```text
accepted
```

After R2 the same payload is rejected:

```text
TrendlineEvidenceContractError:
diagnostic row differs from snapshot row: replay_point_id
```

## 5. Pivot-checkpoint reproduction

Before R2, one pivot-count row was assigned another recorded point's valid checkpoint ID. Recomputed bundle was accepted. After R2:

```text
TrendlineEvidenceContractError:
diagnostic row differs from snapshot row: checkpoint_id
```

## 6. Summary-count reproduction

Before R2, both mutations were accepted after recomputing `bundle_id`:

```text
summary.timeframe_count = 999       accepted
summary.executed_point_count = 999  accepted
```

After R2 both fail closed:

```text
summary does not match evidence rows: timeframe_count
summary does not match evidence rows: executed_point_count
```

## 7. Stale-row-ID reproduction

Before R2, changing line slope or ray end price while retaining the old `evidence_id` was accepted after recomputing the bundle ID. After R2 both are rejected:

```text
diagnostic evidence_id does not match row content
```

The same central builders are used during row construction and read-time validation.

## 8. Snapshot coordinate identity

`SnapshotSummaryRow` now carries the authoritative coordinate binding:

```text
(timeframe, position) -> replay_point_id, content_id, source_id, checkpoint_id,
                         fit IDs, boundary IDs, signal IDs
```

For the deterministic four-point `1h` bundle selected at position 22:

```text
timeframe:          1h
position:           22
event_at:           2025-01-01T22:00:00+00:00
available_at:       2025-01-01T23:00:00+00:00
source_id:          97cc0d1833e3bfa2bcd189bd7b2bea6feec32657c339358f9b48e369a02e184b
checkpoint_id:      17bc5b73c8ab5162a4f6dd2910dba6e9d7a2d707c8ab1d408d064d1a77101262
fit snapshot ID:    933777725b3466730a5234905d90567094ddedf346849e46dec116fa8999cb10
fit revision ID:    6dc2277cf34ee0bd4ae723c172c43f8cac751101023a70fe1bb45b6f571a811d
boundary snapshot:  269e9b004a60dca70f8fbeac76ceb94eaeda6ffb325e7da2a16d883f1c02b7bb
boundary revision:  9e042929226127d49ad02af1061e5b490812f53de18cba66e1feddfb770fbd55
content_id:         225e94e9a182904600274db68920936593acb8aa825ea9938ff92d930f22e48c
replay_point_id:    750a16ecd99f83772820bb4ddfa7a1f6585049b82f699fd3fa16a7c4896c1a49
```

All identity fields are validated as lowercase SHA-256 values where applicable.

## 9. Diagnostic point/content binding

Pivot-count, line, ray, signal and selected-pivot rows now carry `timeframe`, `position`, `replay_point_id` and `content_id`. Every row is checked against exactly one snapshot coordinate. Source, checkpoint, boundary and signal stage IDs are checked against that same snapshot row.

Per-coordinate checks enforce:

```text
one pivot-count row
line/ray counts equal snapshot counts by role
signal count equals snapshot signal_count
ordinal continuity: 0, 1, 2, ... per coordinate and role
```

## 10. Row evidence identities

Added central builders:

```text
build_pivot_count_evidence_id
build_line_evidence_id
build_ray_evidence_id
build_signal_evidence_id
```

Each identity binds row type, coordinate, replay-point/content IDs, source/checkpoint IDs, row-specific semantic fields and `trendlines.research-diagnostics.v2`. The `evidence_id` field itself is excluded from its preimage. Duplicate, malformed or stale IDs are rejected.

## 11. Per-coordinate counts

For the four-point boundary-only evidence sample:

```text
snapshot rows: 4
pivot-count rows: 4
line rows: 1
ray rows: 1
signal rows: 0

positions: 20, 21, 22, 23
support line counts:       0, 0, 0, 1
resistance line counts:    0, 0, 0, 0
support ray counts:        0, 0, 0, 1
resistance ray counts:     0, 0, 0, 0
signal counts:             0, 0, 0, 0
```

## 12. Replay-spec coordinate coverage

Expected recorded coordinates derive directly from each replay window:

```python
range(record_start_position, end_position + 1, record_every)
```

Snapshot coordinates must equal this set for every prepared timeframe. Missing, unexpected, duplicate or extra coordinates fail closed. A tampered `record_every` is rejected even when `bundle_id` is recomputed.

## 13. Summary execution validation

`timeframe_count` now derives from replay-spec windows. `executed_point_count` derives from the inclusive warm-up-to-end range for every window. Recorded count, unique coordinates, valid/invalid counts, line/ray/signal totals, distributions and global temporal extrema are cross-checked against persisted rows.

For the sample bundle:

```text
timeframe_count:                 1
executed_point_count:            5  (positions 19..23)
recorded_snapshot_count:         4
unique_recorded_position_count:  4
```

## 14. Bundle construction

Construction validates replay points once, builds one coordinate map, derives all diagnostic tables from those validated points, derives selection from one selected point, computes `bundle_id`, then runs complete semantic validation before returning. No model executes during table generation or validation.

## 15. Deserialisation validation

Read order remains:

```text
typed deserialisation
content-address verification
full semantic validation
return
```

Recomputed-hash contradictions now reject:

```text
selection/binding coordinate mismatch
selected binding content or replay-point mismatch
line/ray reassignment
pivot checkpoint reassignment
stale row evidence IDs
duplicate row IDs
replay-spec coordinate mismatch
summary count mismatch
per-coordinate row-count mismatch
```

Selection validation does not depend on selected pivots being non-empty. A zero-pivot selected point still requires matching content, point, source, checkpoint and stage identities.

## 16. Dedicated tests

Added exactly eight R2 tests. Dedicated replay/evidence total:

```text
40 passed
```

Coverage includes independent row reassignment, checkpoint/content mismatch, stale line/ray IDs, summary counts, replay-spec coverage and zero-pivot selected binding validation. Existing natural early invalid-output coverage remains; no post-ID mutation is used to represent invalid model output.

## 17. Performance evidence

Deterministic synthetic `1h` benchmark, 600-bar prepared frame, positions 19..530 inclusive:

```text
executed/recorded positions: 512
boundary-only replay:        17,081.879 ms
diagnostic snapshot rows:       958.809 ms
evidence bundle build:        1,334.822 ms
semantic validation:             59.388 ms
```

Signal-enabled benchmark, positions 19..274 inclusive:

```text
executed/recorded positions: 256
signal replay:                3,801.547 ms
history peak:                   256
```

Instrumented 512-point boundary bundle:

```text
row evidence-ID calls:                    2,560
row evidence-ID validation:                 47.149 ms
coordinate/cross-table residual checks:     15.846 ms
complete semantic validation:               62.996 ms
bundle construction:                     1,352.713 ms
```

Requirements remain satisfied:

```text
one model execution per executed position: yes
one prefix source hash per executed position: yes
content hashes per executed position: 512
integrity validation per recorded point: one
provider calls: 0
root-config re-resolution during replay: 0
full-frame hash during evidence validation: 0
```

Validation is linear in evidence rows and uses one snapshot coordinate map; no nested all-pairs scan or model execution occurs.

## 18. Canonical regression

```text
435 collected
435 passed
```

## 19. Bridge regression

```text
Mocked Binance bridge: 8 passed
Provider calls:        0
```

## 20. Consumer regression

```text
Consumer/ingestion: 71 passed
```

## 21. Offline regression

```text
Offline workflows: 20 passed
```

## 22. Static validation

```text
Targeted Ruff: passed
Compileall:    passed
git diff --check: passed
```

Repository-local Python caches were removed after validation.

## 23. Files changed

Existing L2-A2/R1 plus R2 authorized scope:

```text
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
M  src/libs/models/trendlines/workflows/research/__init__.py
M  src/libs/models/trendlines/workflows/research/contracts.py
A  src/libs/models/trendlines/workflows/research/replay.py
A  src/libs/models/trendlines/workflows/research/diagnostics.py
A  src/libs/models/trendlines/workflows/research/evidence.py
A  src/libs/models/trendlines/tests/test_research_replay.py
A  src/libs/models/trendlines/tests/test_research_evidence.py
?? plans/coder-to-orchestrator-trendlines-l2a2-causal-replay-v1.md
?? plans/coder-to-orchestrator-trendlines-l2a2-r1-replay-integrity-v1.md
?? plans/coder-to-orchestrator-trendlines-l2a2-r2-diagnostic-integrity-v1.md
```

## 24. Git status

Expected final status is exactly the authorized L2-A2/R1/R2 files above, all uncommitted. No unrelated path is changed.

## 25. Residual risks

- Evidence remains explicit sorted JSON, not durable database storage.
- Replay history and evidence retention remain in-memory and bounded by existing YAML policy.
- RDP evidence remains retrospective/revising and research-only.
- Multi-timeframe outputs remain independent; no confluence or cross-timeframe composition exists.
- Diagnostic table validation trusts typed replay objects after integrity validation; provider/network paths remain outside L2-A2.

## 26. Recommended next phase

L2-B — Thin research notebook and TVLC presentation.

Notebook/viewer work may consume only validated replay outputs and semantically validated evidence bundles.
