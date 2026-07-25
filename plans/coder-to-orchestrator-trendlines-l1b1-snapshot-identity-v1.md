# Mature Trendlines L1-B1 — Snapshot Identity Handoff

## 1. Disposition

L1-B1 implementation is complete and ready for L1-B2 review. This phase adds
deterministic source, checkpoint, snapshot, revision, stage, and finality
contracts without changing model algorithms or history ordering.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Starting commit: `989a64c71ebfa1811cf795cbce0f51e2abba6922`
- Subject: `feat: enforce trendline extractor execution policy`
- No merge, rebase, reset, or dependency installation performed.

## 3. Worktree and environment proof

- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`
- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`
- Ruff: `/Users/aloobhujia/.local/bin/ruff`
- `PYTHONPATH=$PWD/src:$PWD`
- Branch and package imports resolve inside this worktree.

## 4. Baseline ambiguity reproduction

Before L1-B1, fit metadata contained `execution_mode` and
`extractor_finality`, but no source checkpoint. `TrendlineOutput` had no
`as_of`, snapshot ID, or revision ID. `BoundaryResult` exposed only
`timestamp`; `TrendlineSnapshot` exposed no snapshot or revision identity.

Baseline payloads included:

```text
fit_pipeline_metadata {'extractor': 'fractal', 'fitter': 'pathfinding',
 'n_high_pivots': 0, 'n_low_pivots': 0, 'execution_mode': 'runtime',
 'extractor_finality': 'confirmed_append_only',
 'extractor_supported_modes': ['research', 'runtime']}
fit_output_keys ['boundary_result', 'config', 'fit_result', 'is_valid',
 'metadata', 'signal_output']
boundary_result_keys ... 'timestamp' ...
trendline_snapshot_fields ... 'timestamp' ...
fit_identity_fields ['is_valid', 'metadata', 'resistance_lines', 'support_lines']
```

## 5. Typed identity contracts

Added `contracts/identity.py` with frozen contracts and enums:

- `TrendlineExecutionMode`, `PivotFinality`, `SourceIdentityKind`.
- `TrendlineSnapshotStage`: `FIT`, `BOUNDARY`, `SIGNAL`.
- `TrendlineSnapshotFinality`: `CONFIRMED_AS_OF`,
  `RETROSPECTIVE_REVISING`.
- `TrendlineSourceRef`, `TrendlineCheckpoint`,
  `TrendlineSnapshotIdentity`.

All contracts validate required fields and expose deterministic `to_dict()`.
Optional typed identity fields were added to `TrendlineFitResult`,
`TrendlineOutput`, `BoundaryResult`, and `TrendlineSnapshot`.

## 6. Canonical hashing contract

One SHA-256 seam now canonicalizes dataclasses, enums, mappings with
non-string keys, sequences, sets, pandas timestamps/indexes, datetime values,
NumPy scalars/arrays, bytes, and non-finite floats. It uses sorted compact JSON,
explicit semantics versions, and native array digests. It never uses `repr()`
or process-dependent `hash()` for identity.

## 7. Source horizon validation

`resolve_source_horizon()` rejects empty frames, non-monotonic indexes,
duplicate indexes, and duplicate columns. `as_of` defaults to the final frame
index. A supplied `as_of` must exactly match that final index; earlier, future,
or mismatched values are rejected. Earlier point-in-time execution requires a
frame prefix.

## 8. Computed source identity

Computed `TrendlineSourceRef` uses `SourceIdentityKind.COMPUTED` and hashes
index values, visible model columns (`open`, `high`, `low`, `close`,
`volume`), dtypes, source start, `as_of`, row count, and source-fingerprint
semantics version. The fixture used by tests has source start
`2024-01-01T00:00:00`, `as_of` `2024-01-04T23:00:00`, and 96 rows.
Changing an earlier OHLCV value changes `source_id`.

## 9. Provided source fast path

`source_ref: TrendlineSourceRef | None` is accepted by pipeline and facade
entrypoints. Provided refs use `SourceIdentityKind.PROVIDED`, validate horizon,
row count, and columns, preserve the upstream `source_id`, and avoid frame
fingerprinting. Test instrumentation observed zero calls to
`compute_source_id` on this path.

## 10. Configuration identity

`config_id` includes canonical extractor/fitter names, component parameters,
execution mode, extractor capability metadata, and resolved pipeline
configuration. Caller extractor changes produce different configuration and
checkpoint identities. No YAML or model hyperparameter changed.

## 11. Checkpoint identity

`checkpoint_id` hashes source reference, effective configuration, execution
mode, extractor finality, and checkpoint semantics version. Identical
source/configuration/mode produced stable checkpoint IDs.

## 12. Snapshot identity

`snapshot_id` identifies logical scope, `as_of`, stage, and snapshot semantics.
Unscoped fit identities include source identity; scoped identities use asset,
timeframe, `as_of`, and stage. FIT, BOUNDARY, and SIGNAL stages are distinct.

## 13. Revision identity

`content_id` hashes semantic output content without recursive identity fields.
`revision_id` hashes snapshot ID, checkpoint ID, content ID, and revision
semantics. Same logical scoped point with changed source produced stable
`snapshot_id` and changed `revision_id`.

## 14. Finality mapping

The central mapping is:

```text
CONFIRMED_APPEND_ONLY -> CONFIRMED_AS_OF
RETROSPECTIVE_PREFIX_REVISING -> RETROSPECTIVE_REVISING
```

Runtime Fractal output is `confirmed_as_of`; explicit research RDP output is
`retrospective_revising`.

## 15. Pipeline propagation

`run_trendline_pipeline`, `run_trendline_pipeline_from_config`, and
`execute_trendline_pipeline` propagate `asset`, `timeframe`, `as_of`, and
`source_ref`. One source resolution and one checkpoint are created per call.
Typed checkpoint and FIT identity fields are authoritative; serialized mirrors
remain in metadata for compatibility.

## 16. Public facade propagation

`fit_trendlines`, `fit_trendlines_to_boundary`, `fit_oscillator_to_boundary`,
and `fit_and_signal` accept `as_of` and `source_ref`; fit also accepts paired
optional `asset`/`timeframe`. Boundary and signal calls reuse the fit
checkpoint and create stage-specific content and snapshot identities.

## 17. Boundary identity

`BoundaryResult` receives a BOUNDARY identity and validates stage, scope, and
timestamp/as-of agreement when identity is present. Legacy manually built
fixtures remain valid when identity is `None`.

## 18. TrendlineSnapshot foundation

`TrendlineSnapshot` now carries optional `snapshot_identity`; `from_boundary()`
copies it and `to_dict()` serializes it. L1-B1 did not change history maxlen,
ordering, duplicate handling, latest semantics, replacement, or selection.

## 19. Dedicated tests

Added `test_snapshot_identity.py` with exactly 20 non-parametrised tests covering
horizon rejection, source identity, provided refs, checkpoint stability,
finality, stage identity, revision changes, deterministic serialization, and
single source-resolution behavior.

## 20. Determinism evidence

Identical 96-bar fixture executions produced identical source IDs, checkpoint
IDs, snapshot IDs, revision IDs, and canonical serialized payloads. Runtime
identity classes resolve under `libs.models.trendlines.*`.

## 21. Revision evidence

Changing an earlier OHLCV value while preserving asset, timeframe, row count,
and final `as_of` preserved scoped `snapshot_id` and changed `revision_id`.
Runtime Fractal and research RDP finality mappings both passed.

## 22. Performance baseline

Old clean L1-A2 implementation, 15 repetitions for 1k/10k and 7 for 100k:

```text
fixture hash (1k):   d4a10a3ed6846cb6c88e0e41b326a1a4f1c73fe980acea0c6803223bf9feff6b
fixture hash (10k):  72b385cb68ad3635f97f54e55e441422b4cc138433e9bfc294d155e083112137
fixture hash (100k): 5f62ba9595bbc75204d416864a011a3be57c83fdb6d04fc00987b2519849f313
                 1k        10k        100k
baseline       1.500417   0.301167   2.332792 ms
```

## 23. Performance post-change

```text
path                  1k        10k        100k
computed source    2.286875   1.056167   5.448042 ms
provided source    2.442292   0.560167   2.797000 ms
```

100k computed delta: `+3.115250 ms`, `+133.55%`, absolute budget `<=5 ms`:
pass. Provided delta: `+0.464208 ms`, `+19.90%`; combined acceptance condition
(`>5%` and `>0.5 ms`) is false. No asymptotic change; source fingerprint runs
once.

## 24. Canonical regression

`src/libs/models/trendlines/tests`: `312 collected, 312 passed`.
Dedicated identity tests: `20 collected, 20 passed`.
Existing focused identity/pipeline/API/boundary/history/policy tests: `66 passed`.

## 25. Consumer regression

`tests/test_regime_v2_trendline_feature_producer.py`: `6 passed`.
RegimeV2 feature semantics were not changed.

## 26. Offline research regression

`test_optimizer.py`, `test_optimization_integration.py`, and
`test_trendlines_pipeline_workflow.py`: `20 passed`. Research RDP identities
remain retrospective and no runtime bypass was introduced.

## 27. Static validation

- Canonical-package compileall: passed.
- Targeted Ruff over every changed/new Python file: passed.
- `git diff --check`: passed before handoff creation.
- Repository-local Python caches removed after validation.
- Full-package Ruff remains outside gate because pre-existing package debt is
  unchanged.

## 28. Files changed

```text
M  src/libs/models/trendlines/__init__.py
M  src/libs/models/trendlines/api.py
M  src/libs/models/trendlines/boundary/contracts.py
M  src/libs/models/trendlines/boundary/history.py
M  src/libs/models/trendlines/contracts/__init__.py
M  src/libs/models/trendlines/contracts/contracts.py
A  src/libs/models/trendlines/contracts/identity.py
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/boundary.md
M  src/libs/models/trendlines/docs/pipeline.md
M  src/libs/models/trendlines/pipeline/orchestrator.py
M  src/libs/models/trendlines/pivots/capabilities.py
A  src/libs/models/trendlines/tests/test_snapshot_identity.py
```

No YAML, Trendline V2, algorithm, signal, evidence, or unrelated repository
path changed.

## 29. Git diff summary

Before adding this handoff, implementation diff was 11 modified tracked files,
346 insertions and 25 deletions, plus the two new Python files listed above.
No commit was created for L1-B1.

## 30. Git status

Expected after handoff creation and cache cleanup:

```text
 M src/libs/models/trendlines/__init__.py
 M src/libs/models/trendlines/api.py
 M src/libs/models/trendlines/boundary/contracts.py
 M src/libs/models/trendlines/boundary/history.py
 M src/libs/models/trendlines/contracts/__init__.py
 M src/libs/models/trendlines/contracts/contracts.py
 M src/libs/models/trendlines/docs/architecture.md
 M src/libs/models/trendlines/docs/boundary.md
 M src/libs/models/trendlines/docs/pipeline.md
 M src/libs/models/trendlines/pipeline/orchestrator.py
 M src/libs/models/trendlines/pivots/capabilities.py
?? plans/coder-to-orchestrator-trendlines-l1b1-snapshot-identity-v1.md
?? src/libs/models/trendlines/contracts/identity.py
?? src/libs/models/trendlines/tests/test_snapshot_identity.py
```

## 31. Commands executed

Ran preflight, baseline canonical and RegimeV2 tests, source-horizon and
identity smoke commands, focused suites, dedicated 20-test collection/run,
canonical 312-test collection/run, offline 20-test workflow run, source
fingerprint call-count instrumentation, deterministic 1k/10k/100k benchmarks,
targeted Ruff, compileall, `git diff --check`, and cache cleanup.

## 32. Residual risks

- L1-B2 still must define ordered, revision-aware history insertion and
  point-in-time selection.
- L1-B3 still must validate signal context timestamps and future-history use.
- Direct low-level callers that bypass public pipeline/facade APIs do not gain
  automatic identity construction.
- Computed source identity adds one linear frame pass; provided refs are the
  production fast path.
- Full-package pre-existing Ruff debt remains separate from this change.

## 33. Recommended next phase

`L1-B2 — Ordered, revision-aware point-in-time snapshot history`.

Required conclusion: every public mature-trendlines output now carries explicit
source checkpoint and point-in-time identity; `as_of` equals the final supplied
frame row; identical source/config/output is deterministic; revised
source/config/output produces a new `revision_id`; no model hyperparameter or
unsafe YAML override was added.
