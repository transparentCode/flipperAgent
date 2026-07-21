# Coder To Orchestrator: Trendline V2 Phase 6A

Status: `READY_FOR_ORCHESTRATOR_REVIEW`

Stop state:

```text
PHASE_6A_COMPLETE
PHASE_6B_PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED
PHASE_6C_PROVIDER_VALIDATION_NOT_AUTHORIZED
PHASE_6V_TVLC_VIEWER_NOT_AUTHORIZED
```

## Scope

Phase 6A adds typed provider configuration, field policy registration,
semantic request binding, typed confirmed-extrema evidence, tests, and
architecture-only plans. No provider algorithm, registry, kernel, Numba,
viewer, YAML provider value, tracking, MTF, research, optimization, or runtime
integration is in scope.

## Decisions

```text
history_horizon = lookback_duration_seconds_v1
lookback_duration_seconds = required explicit fixture/request value
body_validation_policy = exact_side_v1
body_clearance_tolerance = absent
max_hypotheses = semantic/hash-bound
max_output_candidates = semantic/hash-bound
provider_config = explicit immutable typed request field
universal CandidateEvidence = unchanged
provider evidence = separate immutable typed record
canonical YAML = provider-inactive
```

## Changed files

Validated source scope:

```text
src/libs/models/trendline_v2/configuration/__init__.py
src/libs/models/trendline_v2/configuration/field_policy.py
src/libs/models/trendline_v2/configuration/provider.py
src/libs/models/trendline_v2/discovery/__init__.py
src/libs/models/trendline_v2/discovery/contracts.py
src/libs/models/trendline_v2/discovery/provider_evidence.py
tests/models/trendline_v2/test_provider.py
tests/models/trendline_v2/test_extrema_pair_contracts.py
plans/trendline-v2-extrema-pair-contract-v1.md
plans/trendline-v2-extrema-pair-config-policy-v1.md
plans/trendline-v2-tvlc-viewer-contract-v1.md
plans/coder-to-orchestrator-trendline-v2-phase-6a-v1.md
```

## Required validation

```text
focused Phase 6A tests: 27 passed
tests/models/trendline_v2: 59 passed
tests/models/trendline_family: 399 passed
ruff: passed
compileall: passed
git diff --check: passed
codebase-memory index: passed; 58,016 nodes / 231,585 edges
```

## Review checklist

```text
[ ] no provider implementation
[ ] no extrema scanner or pair enumeration
[ ] no registry
[ ] no kernels or Numba
[ ] no viewer source or chart dependency
[ ] no YAML provider values
[ ] no old trendline/SR/Regime/research/optimization imports
[ ] provider config fields all required and typed
[ ] unresolved fields YAML-inactive
[ ] request identity binds actual provider config
[ ] evidence immutable, typed, causal, deterministic
[ ] universal evidence unchanged
[ ] Phase 5 worktree and main untouched
```
