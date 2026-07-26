# Mature Trendlines L2-A2 — Causal Replay, Diagnostics and Evidence

## 1. Disposition

L2-A2 implementation complete and uncommitted. Replay executes availability-confirmed prefixes through canonical public facades; diagnostics and deterministic evidence persistence are present. No notebook, viewer, optimisation, provider call, SQLite storage or promotion behavior was added.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
starting commit: d33dfde560beb4b4d3048fd7ced2f3ba0b7af678
starting subject: feat: add trendline research foundation
```

## 3. Worktree/environment proof

Validation used:

```text
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
RUFF=/Users/aloobhujia/.local/bin/ruff
PYTHONPATH=$PWD/src:$PWD
```

No dependencies were installed. No provider calls were made. L2-A2 changes remain uncommitted.

## 4. Baseline replay gap

L2-A1 stopped at validated research specification, prepared frames, source and availability identities, resolved pipeline configuration and preparation identity. It did not execute causal prefixes, maintain replay history, expose replay identities, produce diagnostic rows or persist evidence bundles.

## 5. Replay-window contracts

`TrendlineReplayWindow` validates zero-based inclusive warm-up, record-start and end positions, positive non-boolean `record_every`, and prepared-frame bounds. `TrendlineResearchReplaySpec` requires exact prepared timeframe coverage and an actual boolean `include_signals`.

## 6. Warm-up and recording semantics

Every position from warm-up start through end executes. Recording stride filters evidence only; it never skips model execution or history updates. Replay exposes executed, warm-up and recorded counts.

## 7. Prefix construction

Each position uses only `df.iloc[:position + 1]`, source-model-visible column order and matching availability prefix. Knowledge time is final prefix availability. One prefix `TrendlineSourceRef` is computed per executed position and passed to the canonical facade.

## 8. Canonical execution path

Replay calls only `fit_trendlines_to_boundary()` for boundary-only runs and `fit_and_signal()` for signal runs, with `TrendlineExecutionMode.RESEARCH`, prepared component configuration, exact `as_of`, exact source reference and prepared root configuration. No manual extractor/fitter chaining occurs.

## 9. Signal-history causality

Signal runs build typed `TrendlineSignalContext` and `TrendlineSignalInputs` from the exact prefix. Prior snapshots come from `snapshots_before()` using current event time and current availability as knowledge cutoff. Current boundary is added with final prefix availability as `known_at`. YAML-resolved history policy is used through prepared configuration.

## 10. Failure policy

Unexpected position failures raise `TrendlineReplayError` containing timeframe, position, event timestamp, availability timestamp and underlying exception type. Invalid or empty model outputs remain valid recorded observations.

## 11. Replay and point identities

```text
replay_id = preparation_id + dataset_id + research_configuration_id
            + replay specification + replay semantics version
replay_point_id = timeframe + position + event/availability + prefix source
                  + checkpoint + stage identities + finality
```

Point identity does not bind full parent dataset identity, allowing independent truncated replays to match shared causal points.

## 12. Future-row invariance

`verify_replay_future_invariance()` compares shared point source, checkpoint, fit/boundary/signal snapshot and revision IDs, replay point ID, serialized boundary content and serialized signal content. It raises structured mismatch details and rejects preparation/configuration identity mismatch.

## 13. Snapshot diagnostics

Snapshot rows contain event/availability, source/checkpoint IDs, stage identities, finality, validity, line/ray counts, structural state, interaction, market position, hull/quality and signal summary fields. Pivot-count rows use authoritative pipeline metadata.

## 14. Line/ray/signal diagnostics

Line, ray and native signal rows have deterministic role/ordinal ordering and stable evidence IDs. Geometry, quality, touch and point-identity fields are preserved. Boundary-only replay emits empty signal rows. Diagnostic table construction performs no model execution.

## 15. Selected pivot inspection

`inspect_replay_pivots()` accepts only a recorded replay position, verifies preparation/replay identity agreement, reconstructs the exact prefix, builds the configured extractor through the canonical registry in research mode, and checks extracted high/low counts against authoritative pipeline metadata.

## 16. Aggregate summary

`TrendlineReplaySummary` reports timeframe count, executed/recorded/valid/invalid positions, line/ray totals, signal total, finality and state distributions, and event/availability bounds using truthful `recorded_snapshot_count` and `unique_recorded_position_count` names.

## 17. Evidence selection

`TrendlineEvidenceSelection` contains only timeframe and recorded position. Bundle construction derives every selected ID, timestamp and source value from `replay.output_at()`; callers cannot independently provide snapshot or revision identifiers.

## 18. Evidence bundle

`TrendlineResearchEvidenceBundle` contains preparation, dataset, configuration and replay identities, replay specification, aggregate summary, snapshot/pivot-count/line/ray/signal rows, selected binding and selected pivots. It excludes complete frames, wall-clock time, notebook state, mutable YAML and credentials.

## 19. Persistence and tamper validation

`write_research_evidence_bundle()` is explicit-only and writes compact sorted deterministic JSON through `TrendlineArtifactRef`. `read_research_evidence_bundle()` reconstructs the typed bundle and verifies the recomputed `bundle_id`; tampered payloads are rejected. Round-trip serialized content is stable.

## 20. Multi-timeframe isolation

Each prepared timeframe replays independently in requested order. No resampling, interpolation, confluence, cross-timeframe matching or cross-timeframe signals were added.

## 21. RDP evidence

RDP executes only through explicit research mode. RDP replay points retain `RETROSPECTIVE_REVISING` / `retrospective_revising` finality. No runtime path was added and no numerical RDP behavior changed.

## 22. Dedicated tests

Exactly 24 non-parametrised tests were added:

```text
test_research_replay.py:   13
test_research_evidence.py: 11
total:                     24
```

Focused result: `24 passed`.

## 23. Performance evidence

Deterministic synthetic preparation ID for the 512-position boundary benchmark:

```text
preparation_id: 83fb6df55534d4243c6b67621dc22d2982417dadcce5ab832db71d88ba41dca4
dataset_id:     9974a245e795cff4ad42f73c577ccb7dbfcb542847de0b9558a18e1d007672a6
config_id:      ab6ec43eede637492f1e11bea6f4ae0cf72ef12045ee87265d648edb0cfc5853
replay_id:      da120ed40efa1479ada0466ce908e635b65bdce773e97c784fa93cb0f005f2a8
```

Single-repetition timings, 19-bar warm-up:

| Workload | Executed | Recorded | Time | ms/executed |
|---|---:|---:|---:|---:|
| Boundary replay | 128 | 128 | 660.457 ms | 5.16 |
| Boundary replay | 256 | 256 | 2,301.893 ms | 8.99 |
| Boundary replay | 512 | 512 | 18,232.279 ms | 35.61 |
| Signal replay | 128 | 128 | 865.766 ms | 6.76 |
| Signal replay | 256 | 256 | 2,424.500 ms | 9.47 |

Control instrumentation for 493 executed positions observed 493 prefix source-reference calls, 493 model executions, peak retained history 256, and zero root configuration loads during replay. Diagnostic construction for 512 recorded points took 355.895 ms. Bundle size was 2,534,023 bytes. Boundary rows were 512 snapshots, 512 pivot-count rows, 1,024 lines, 1,024 rays and 0 signals. No provider calls occurred.

Acceptance passed: 512-prefix boundary replay was below 20 seconds; 256-prefix signal replay was below 20 seconds; diagnostic construction was below 1 second. No per-row OHLCV dictionary conversion or full-frame sort was introduced.

## 24. Canonical regression

```text
419 collected
419 passed
```

## 25. Bridge regression

```text
Mocked Binance bridge: 8 passed
Provider calls: 0
```

## 26. Consumer regression

```text
Consumer/ingestion matrix: 71 passed
```

## 27. Offline regression

```text
Offline workflow group: 20 passed
```

## 28. Static validation

```text
Changed-file Ruff: passed
Compileall: passed
git diff --check: passed
Repository-local caches removed
```

## 29. Files changed

```text
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
M  src/libs/models/trendlines/workflows/research/__init__.py
M  src/libs/models/trendlines/workflows/research/contracts.py
A  src/libs/models/trendlines/workflows/research/diagnostics.py
A  src/libs/models/trendlines/workflows/research/evidence.py
A  src/libs/models/trendlines/workflows/research/replay.py
A  src/libs/models/trendlines/tests/test_research_evidence.py
A  src/libs/models/trendlines/tests/test_research_replay.py
A  plans/coder-to-orchestrator-trendlines-l2a2-causal-replay-v1.md
```

## 30. Git status

Expected final status is exactly the files listed in section 29, all uncommitted. No unrelated path is authorized.

## 31. Commands executed

```text
pytest collect-only and canonical trendlines suite
pytest dedicated replay/evidence suite
pytest mocked Binance bridge
pytest consumer/ingestion matrix
pytest offline workflow group
compileall over changed canonical package
targeted Ruff over changed Python files
git diff --check
find-based repository-local __pycache__ cleanup
ephemeral deterministic replay, invariance, diagnostic, evidence and timing commands
```

## 32. Residual risks

- Replay intentionally remains in-memory; persistent evidence storage is outside L2-A2.
- Replay runtime is model-dominated and grows with executed prefixes; measured acceptance limits pass for required workloads.
- RDP evidence remains retrospective/revising and is research-only.
- Multi-timeframe composition, optimisation, holdout access, promotion and presentation remain out of scope.

## 33. Recommended next phase

```text
L2-B — Thin research notebook and TVLC presentation
```

Do not start L2-B in this phase.

## Final conclusion

The mature trendlines research path executes only availability-confirmed prefixes. Warm-up and recording stride do not alter causal state. Every replay point binds exact prefix source, configuration, boundary and selected signal history. Full and independently truncated runs match at shared causal points. Diagnostic tables and exported evidence are deterministic and selected-position consistent. No model algorithm, numerical parameter, notebook, viewer, optimisation or promotion behavior changed.
