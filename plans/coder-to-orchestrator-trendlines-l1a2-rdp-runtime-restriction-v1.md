# Mature Trendlines L1-A2 — Typed Extractor Execution Policy

## 1. Disposition

READY_FOR_L1B_SNAPSHOT_FINALITY_CONTRACTS

RDP ZigZag remains available for explicit research execution and is rejected
before extraction in runtime execution. Policy is centralized through immutable
typed extractor capabilities. No L1-A2 commit was created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Starting commit: `1d6857a fix: make fractal plateau pivots append-only`
- Worktree was clean after the L1-A1 checkpoint commit.
- Canonical package contains 147 tracked files.

## 3. Worktree and environment proof

Work remained inside:

```text
/Users/aloobhujia/flipperAgent-wt-legacy-trendlines
```

Validation used:

```text
Python: /Users/aloobhujia/flipperAgent/.venv/bin/python
Ruff:   /Users/aloobhujia/.local/bin/ruff
PYTHONPATH=$PWD/src:$PWD
```

No dependency install or provider/network call was made. Current-checkout
codebase-memory indexing was attempted but its worker crashed on a file and the
checkout was not available as an indexed project; live-source inspection was
used as fallback. No GitNexus index or repository source was modified.

## 4. Baseline unsafe-runtime reproduction

Before implementation, canonical baseline was:

```text
274 tests collected
274 passed
RegimeV2 adapter: 6 passed
```

The following runtime call succeeded before policy enforcement:

```python
run_trendline_pipeline(
    frame,
    extractor="rdp_zigzag",
    fitter="least_squares",
)
```

Observed output:

```text
baseline_rdp_runtime_succeeded True
baseline_pipeline_metadata {
  'extractor': 'rdp_zigzag',
  'fitter': 'least_squares',
  'n_high_pivots': 5,
  'n_low_pivots': 4,
}
```

No caller declared retrospective research.

## 5. Typed execution contracts

Added:

```text
src/libs/models/trendlines/pivots/capabilities.py
```

The module defines:

- `TrendlineExecutionMode.RUNTIME` and `.RESEARCH`
- `PivotFinality.CONFIRMED_APPEND_ONLY` and
  `.RETROSPECTIVE_PREFIX_REVISING`
- frozen `ExtractorCapabilities`
- `ExtractorExecutionPolicyError(ValueError)`
- mode normalization, capability lookup, validation, and metadata serialization

Capability modes are stored as `frozenset` values. No execution policy is a
free-form internal string dictionary.

## 6. Extractor capability registry

`register_extractor()` now requires a `capabilities` argument. Registration
stores the immutable descriptor in the central `EXTRACTOR_CAPABILITIES` map and
attaches it to the registered class as `CAPABILITIES`. No implicit capability
default exists.

Registry additions:

```text
canonical_extractor_name
get_registered_extractor_capabilities
list_extractors_for_mode
```

`build_extractor()` validates mode before constructing the extractor. Denial
messages include canonical name, requested mode, supported modes, and finality.

## 7. Fractal capability

`FractalPivotExtractor` declares:

```text
supported modes: RUNTIME, RESEARCH
finality:        CONFIRMED_APPEND_ONLY
```

Existing L1-A1 append-only plateau behavior remains unchanged.

## 8. RDP capability

`RDPZigZagPivotExtractor` declares:

```text
supported modes: RESEARCH
finality:        RETROSPECTIVE_PREFIX_REVISING
```

RDP numerical behavior was not changed: endpoint selection, RDP
simplification, ATR calculation, epsilon, segment spacing, pivot
classification, and search-grid values remain intact.

## 9. Named extractor enforcement

Runtime registry listing:

```text
('fractal',)
```

Research registry listing:

```text
('fractal', 'rdp_zigzag')
```

Both canonical `rdp_zigzag` and deprecated `rdp-zigzag` aliases resolve to the
canonical name before validation. Runtime construction fails before class
construction when policy denies access.

## 10. Direct-instance enforcement

`run_trendline_pipeline()` validates directly supplied extractor instances
through their class-level typed `CAPABILITIES` descriptor before calling
`extract()`. Direct RDP instances fail in runtime mode and succeed in research
mode.

## 11. Custom extractor policy

Unclassified custom extractors fail closed with
`ExtractorExecutionPolicyError`. Classified custom extractors are accepted only
in declared modes. Tests cover:

```text
classified runtime custom extractor: accepted in runtime
research-only custom extractor:       rejected in runtime, accepted in research
unclassified custom extractor:         rejected
```

No bypass such as `skip_validation`, `trust_custom_extractor`, or `allow_unknown`
was added.

## 12. Public facade propagation

Typed keyword-only `execution_mode`, defaulting to `RUNTIME`, now propagates
through:

```text
fit_trendlines
fit_trendlines_to_boundary
fit_oscillator_to_boundary
fit_and_signal
```

Runtime facade calls using RDP fail closed. Explicit research facade calls
complete and retain retrospective finality in fit-result pipeline metadata.

## 13. Offline research callsite propagation

Explicit `TrendlineExecutionMode.RESEARCH` was added to extractor construction
and pipeline execution in:

```text
src/libs/models/trendlines/optimization/optimizer.py
src/libs/models/trendlines/optimization/oscillator.py
src/libs/models/trendlines/workflows/pipeline/evaluation.py
```

The pipeline workflow CLI now derives extractor choices from
`list_extractors_for_mode(TrendlineExecutionMode.RESEARCH)` rather than a
hardcoded choice list.

No offline callsite that can select RDP relies on runtime default.

## 14. YAML/configuration behavior

No YAML file or numerical hyperparameter changed. YAML may continue selecting
`rdp_zigzag`; it cannot override execution policy. Runtime config-selected RDP
fails closed, while explicit research-mode config execution succeeds.

No unsafe override was added:

```text
allow_rdp_runtime: absent
allow_retrospective_extractors: absent
disable_causality_guard: absent
```

## 15. Dedicated policy tests

Added exactly 18 non-parametrised tests:

```text
src/libs/models/trendlines/tests/test_extractor_execution_policy.py
```

Result:

```text
18 collected
18 passed
```

Coverage includes both capability declarations, mode listings, named and alias
construction, named and direct pipeline paths, custom extractors, config
selection, and public facade metadata.

## 16. Runtime rejection evidence

All required runtime cases fail with `ExtractorExecutionPolicyError` before
pivot extraction:

```text
registered RDP name:              rejected
deprecated RDP alias:             rejected
direct RDP instance:              rejected
research-only custom instance:    rejected
unclassified custom instance:     rejected
config-resolved RDP selection:    rejected
public facade RDP selection:      rejected
```

## 17. Research preservation evidence

All required research cases succeed:

```text
registered RDP name:              accepted
deprecated RDP alias:             accepted
direct RDP instance:              accepted
config-resolved RDP selection:    accepted
offline optimization paths:       explicit research mode
```

## 18. Pipeline metadata evidence

Successful pipeline results now record:

```text
execution_mode
extractor_finality
extractor_supported_modes
```

Example RDP research metadata:

```text
execution_mode:             research
extractor_finality:         retrospective_prefix_revising
extractor_supported_modes:  [research]
```

No snapshot finality, `as_of`, revision identifier, or history semantics were
introduced; those remain L1-B scope.

## 19. Performance baseline

Ephemeral deterministic fixture:

```text
seed: 42
columns: open, high, low, close
hashing: canonical float64 OHLCV bytes
registry repetitions: 7 x 1,000 constructions
pipeline repetitions: 15 / 15 / 7 for 1k / 10k / 100k
```

Baseline medians:

| Workload | Repetitions | Fixture hash | Median |
|-|-|-|-|
| Registry Fractal construction | 7,000 | n/a | 0.000395 ms |
| Runtime Fractal pipeline, 1,000 bars | 15 | `3e5292ade7c758168e80da01b0b5775b5904cb873a171f6c79dc25147bc821bf` | 0.335417 ms |
| Runtime Fractal pipeline, 10,000 bars | 15 | `9c7c811339e4a7b2c70f9e5ddc8e002efd7b6ea1abe5021e2f4de2e4618125e6` | 1.342625 ms |
| Runtime Fractal pipeline, 100,000 bars | 7 | `356942f1d0ea474210d1c4814e12a9f902efe18be1a680607d27cc247b21c3cb` | 12.651417 ms |

## 20. Performance post-change result

Post-change medians on identical fixtures and repetitions:

| Workload | Baseline | Post | Absolute delta | Relative delta |
|-|-|-|-|-|
| Registry Fractal construction | 0.000395 ms | 0.000971 ms | +0.000576 ms | +145.82% |
| Runtime Fractal pipeline, 1,000 bars | 0.335417 ms | 0.349541 ms | +0.014124 ms | +4.21% |
| Runtime Fractal pipeline, 10,000 bars | 1.342625 ms | 1.389083 ms | +0.046458 ms | +3.46% |
| Runtime Fractal pipeline, 100,000 bars | 12.651417 ms | 12.807792 ms | +0.156375 ms | +1.24% |

Policy validation performs only constant-time capability lookup/validation before
frame extraction. It does not scan OHLCV data, pivots, recompute ATR, copy the
frame, or run per bar. No asymptotic change occurred. The 100,000-bar threshold
passes: regression is below both 5% and 0.5 ms.

## 21. Canonical regression

```text
292 collected
292 passed
```

Focused policy/registry/pipeline/public/finality group:

```text
42 passed
```

## 22. Consumer regression

```text
tests/test_regime_v2_trendline_feature_producer.py
6 passed
```

Offline workflow/optimization coverage:

```text
test_optimizer.py
test_optimization_integration.py
test_trendlines_pipeline_workflow.py
20 passed
```

`test_optimization_oscillator.py` does not exist in this checkout; oscillator
callsite propagation was reviewed and covered through the canonical suite.

## 23. Static validation

```text
compileall src/libs/models/trendlines: passed
targeted Ruff on every changed Python file: passed
git diff --check: passed
repository-local __pycache__ directories: removed
```

Canonical CLI help and capability smoke also passed. No generated artifact was
created.

## 24. Files changed

Added:

```text
src/libs/models/trendlines/pivots/capabilities.py
src/libs/models/trendlines/tests/test_extractor_execution_policy.py
plans/coder-to-orchestrator-trendlines-l1a2-rdp-runtime-restriction-v1.md
```

Modified:

```text
src/libs/models/trendlines/__init__.py
src/libs/models/trendlines/api.py
src/libs/models/trendlines/docs/pipeline.md
src/libs/models/trendlines/docs/pivots.md
src/libs/models/trendlines/optimization/optimizer.py
src/libs/models/trendlines/optimization/oscillator.py
src/libs/models/trendlines/pipeline/orchestrator.py
src/libs/models/trendlines/pivots/__init__.py
src/libs/models/trendlines/pivots/base.py
src/libs/models/trendlines/pivots/fractal.py
src/libs/models/trendlines/pivots/rdp_zigzag.py
src/libs/models/trendlines/registry/__init__.py
src/libs/models/trendlines/registry/registry.py
src/libs/models/trendlines/tests/test_end_to_end_pipeline.py
src/libs/models/trendlines/tests/test_pipeline_executor.py
src/libs/models/trendlines/tests/test_registry.py
src/libs/models/trendlines/workflows/pipeline/evaluation.py
src/libs/models/trendlines/workflows/pipeline/workflow.py
```

No config, RDP algorithm, boundary, signal, fitter, Trendline V2, artifact, or
research-evidence path changed.

## 25. Git diff summary

Implementation diff: 18 modified tracked Python/Markdown files, plus two new
Python files. The handoff is the only new plan. No numerical RDP parameter moved
into code. No hardcoded extractor-name policy checks were added; production
policy uses typed capabilities and dynamic registry queries.

## 26. Git status

Expected final status after handoff creation:

```text
M  src/libs/models/trendlines/__init__.py
M  src/libs/models/trendlines/api.py
M  src/libs/models/trendlines/docs/pipeline.md
M  src/libs/models/trendlines/docs/pivots.md
M  src/libs/models/trendlines/optimization/optimizer.py
M  src/libs/models/trendlines/optimization/oscillator.py
M  src/libs/models/trendlines/pipeline/orchestrator.py
M  src/libs/models/trendlines/pivots/__init__.py
M  src/libs/models/trendlines/pivots/base.py
M  src/libs/models/trendlines/pivots/fractal.py
M  src/libs/models/trendlines/pivots/rdp_zigzag.py
M  src/libs/models/trendlines/registry/__init__.py
M  src/libs/models/trendlines/registry/registry.py
M  src/libs/models/trendlines/tests/test_end_to_end_pipeline.py
M  src/libs/models/trendlines/tests/test_pipeline_executor.py
M  src/libs/models/trendlines/tests/test_registry.py
M  src/libs/models/trendlines/workflows/pipeline/evaluation.py
M  src/libs/models/trendlines/workflows/pipeline/workflow.py
?? src/libs/models/trendlines/pivots/capabilities.py
?? src/libs/models/trendlines/tests/test_extractor_execution_policy.py
?? plans/coder-to-orchestrator-trendlines-l1a2-rdp-runtime-restriction-v1.md
```

No L1-A2 commit was created.

## 27. Commands executed

```text
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
git status --short --untracked-files=all
python -m pytest --collect-only -q src/libs/models/trendlines/tests
python -m pytest -q src/libs/models/trendlines/tests
python -m pytest -q tests/test_regime_v2_trendline_feature_producer.py
python -m pytest -q src/libs/models/trendlines/tests/test_extractor_execution_policy.py
python -m pytest -q src/libs/models/trendlines/tests/test_optimizer.py src/libs/models/trendlines/tests/test_optimization_integration.py src/libs/models/trendlines/tests/test_trendlines_pipeline_workflow.py
python -m libs.models.trendlines.cli --help
python -m compileall -q src/libs/models/trendlines
ruff check <every changed Python file>
git diff --check
```

Ephemeral Python commands also reproduced pre-change runtime RDP success,
post-change capability metadata, registry lists, and 1k/10k/100k performance.

## 28. Residual risks

- RDP remains retrospective and must stay restricted to explicit research mode.
- Public snapshot `as_of`, finality, and revision identity contracts remain L1-B.
- Direct `.extract()` calls on an RDP instance remain available by design; policy
  guards pipeline construction/execution, not low-level research primitives.
- Runtime drift-monitor execution retains runtime default and therefore rejects
  any RDP selected through an unexpected runtime config, as required.

## 29. Recommended next phase

L1-B — Public snapshot finality, as-of and revision contracts.

