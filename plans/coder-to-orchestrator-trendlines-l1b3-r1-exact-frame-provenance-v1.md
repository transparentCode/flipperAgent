# Mature Trendlines L1-B3-R1
## Exact-Frame Identity and Availability-Provenance Remediation

### 1. Disposition

R1 complete. Native orchestration now requires exact-frame and boundary identity
binding. RegimeV2 now rejects missing or unknown availability provenance. No
commit was created; L2-A was not started.

### 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
HEAD: 34aa761a59d93a295d2f395acb7c011117f7e0ec
subject: feat: add revision-aware trendline history
```

### 3. Worktree proof

Preflight found only the authorised uncommitted L1-B3 implementation and
handoff paths. R1 added only its scoped implementation, test, documentation,
and this handoff.

### 4. Missing-frame reproduction

Before remediation:

```text
TrendlineSignalOrchestrator().run(identityless_boundary,
    signal_inputs=typed_inputs, frame=None)
→ accepted
→ signal_input_id: dfec154548511c9127d2d64f3f89a7020c213e6e04de69efc306466545492c3e
→ checkpoint/source absent: True
```

After remediation:

```text
frame=None
→ SignalContextContractError: frame must be a pandas DataFrame
```

### 5. Missing-boundary-identity reproduction

Before remediation, identity-less current boundary plus valid typed context was
accepted. After remediation:

```text
→ SignalContextContractError: current boundary requires a snapshot identity
```

### 6. Missing-provenance reproduction

Before remediation, both missing and invalid `bar_availability_source` were
silently labelled `exchange_close_time`. After remediation:

```text
missing → ValueError: bar_available_at requires bar_availability_source provenance
unknown → ValueError: unknown bar_availability_source: 'unknown'
```

### 7. Current boundary identity validation

`validate_signal_inputs()` now requires boundary-stage identity, matching asset
and timeframe, and checkpoint source `as_of` matching boundary timestamp.

### 8. Exact-frame horizon validation

Required frame is validated once before extractors. Check covers timezone,
ordering, uniqueness, final event timestamp, source start, final `as_of`, row
count, and model-visible columns. Existing source-horizon resolver is reused;
no fingerprint/hash pass is added.

Observed rejection evidence:

```text
wrong current-boundary stage/scope/horizon → SignalContextContractError
row-count/start/visible-column mismatch → SignalContextContractError
```

### 9. Precomputed validation binding

`ValidatedTrendlineSignalInputs` now carries immutable:

```text
boundary_snapshot_id
checkpoint_id
source_id
```

Orchestrator verifies these values and exact `TrendlineSignalInputs` object when
precomputed validation is supplied. It does not validate once per extractor.

### 10. Signal-input identity evidence

`signal_input_id` now fails closed without valid boundary identity and always
binds non-null checkpoint/source IDs and current `as_of`. Metadata exposes:

```text
signal_boundary_snapshot_id
signal_checkpoint_id
signal_source_id
```

### 11. Availability-provenance validation

With `bar_available_at`, only these sources are valid:

```text
exchange_close_time
fixed_interval_derived
close_time_index (only with CLOSE_TIME semantics)
```

Missing/unknown source rejects. Frames without the column retain strict fixed
interval derivation or explicit close-time-index behavior.

Valid exchange and fixed-derived provenance resolve successfully; valid
close-time-index provenance requires `CLOSE_TIME` semantics.

### 12. Attribute-preservation evidence

Preparation explicitly copies `bar_availability_source` through copy, sort,
timestamp-index preparation, and generated-index paths. Live check:

```text
normalised source: exchange_close_time
prefix source:     exchange_close_time
prepared source:   exchange_close_time
```

No provenance column was added to model-visible OHLCV.

### 13. Dedicated tests

Added exactly five canonical tests:

```text
frame=None rejection
identity-less boundary rejection
wrong stage/scope/horizon rejection
row/start/visible-column checkpoint mismatch rejection
valid exact-frame identity-bound signal input
```

Added exactly two external tests: missing provenance and unknown provenance.
Direct orchestrator fixtures now supply identity-bearing boundaries and exact
frames.

### 14. Canonical regression

```text
367 collected
367 passed
Focused causal signal/API/context group: 65 passed
```

### 15. Consumer regression

```text
RegimeV2, shadow collector, RegimeV2 integration, ingestion adapters:
71 passed
```

### 16. Offline regression

```text
test_optimizer.py
test_optimization_integration.py
test_trendlines_pipeline_workflow.py
20 passed
```

### 17. Performance evidence

Provided-source 100,000-bar fixture:

```text
source_id: 85d74689ab02ca1f50d86fe7b2a7413bbfd0fbd72ba52c9d8c6bd7a9f8361e38
repetitions: 5 for full pipeline; 20 for validator isolation
```

Same-frame simulated pre-R1 versus R1 full-pipeline medians:

```text
pre-R1: 236.172 ms
R1:     202.062 ms
delta:  -34.110 ms (-14.44%)
```

Validator-only medians:

```text
pre-R1: 0.2295 ms
R1:     0.3561 ms
delta:  +0.1267 ms
```

R1 delta is below 1 ms. No extra frame hash, DataFrame copy, sort, or
per-extractor validation was introduced.

### 18. Static validation

```text
compileall over changed packages/files: passed
targeted Ruff over every changed/new Python file: passed
git diff --check: passed
```

Repository-local Python caches were removed after validation.

### 19. Files changed

R1-scoped paths:

```text
src/libs/models/trendlines/signals/context.py
src/libs/models/trendlines/signals/orchestrator.py
src/libs/models/regime_v2/adapters/trendline_feature_producer.py
src/libs/models/trendlines/docs/signals.md
src/libs/models/trendlines/tests/test_signal_context_alignment.py
src/libs/models/trendlines/tests/test_end_to_end_pipeline.py
src/libs/models/trendlines/tests/test_signal_orchestrator_config.py
src/libs/models/trendlines/tests/test_signals.py
tests/test_regime_v2_trendline_feature_producer.py
plans/coder-to-orchestrator-trendlines-l1b3-r1-exact-frame-provenance-v1.md
```

Existing L1-B3 paths remain uncommitted.

### 20. Git status

Expected after cache cleanup:

```text
M  src/apps/ingestion_app/adapters/binance_native.py
M  src/libs/models/regime_v2/adapters/trendline_feature_producer.py
M  src/libs/models/regime_v2/scripts/compare_binance_native.py
M  src/libs/models/trendlines/__init__.py
M  src/libs/models/trendlines/api.py
M  src/libs/models/trendlines/boundary/history.py
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/boundary.md
M  src/libs/models/trendlines/docs/pipeline.md
M  src/libs/models/trendlines/docs/signals.md
M  src/libs/models/trendlines/signals/__init__.py
M  src/libs/models/trendlines/signals/orchestrator.py
M  src/libs/models/trendlines/tests/test_end_to_end_pipeline.py
M  src/libs/models/trendlines/tests/test_import_boundaries.py
M  src/libs/models/trendlines/tests/test_integration_pipeline.py
M  src/libs/models/trendlines/tests/test_signal_orchestrator_config.py
M  src/libs/models/trendlines/tests/test_signals.py
M  src/libs/models/trendlines/tests/test_snapshot_identity.py
M  tests/ingestion/test_adapters.py
M  tests/test_regime_v2.py
M  tests/test_regime_v2_trendline_feature_producer.py
?? plans/coder-to-orchestrator-trendlines-l1b3-signal-context-alignment-v1.md
?? plans/coder-to-orchestrator-trendlines-l1b3-r1-exact-frame-provenance-v1.md
?? src/libs/models/trendlines/signals/context.py
?? src/libs/models/trendlines/tests/test_signal_context_alignment.py
```

No commit was created.

### 21. Residual risks

RDP remains restricted by L1-A2. History ordering/revision policy remains
L1-B2. Signal formulas and degraded-extractor semantics were not changed.
Callers must still construct typed availability context from authoritative
source metadata.

### 22. Recommended next phase

```text
L2-A — Canonical research-support and causal replay APIs
```

Do not build the research notebook before L2-A approval.
