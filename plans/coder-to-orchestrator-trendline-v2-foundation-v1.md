# Coder to Orchestrator: Trendline V2 Foundation V1

## Objective

Implemented only the authorized Trendline V2 foundation: Phase 0 program
contract/reconnaissance, Phase 1 domain contracts and identity, Phase 2 causal
confirmed-OHLCV input, Phase 3 strict configuration, and Phase 4 provider
protocol. No provider technique was selected or implemented.

## Branch and Worktree

- Branch: `feature/trendline-v2-foundation-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-v2-foundation`
- Base branch: `main`
- Base commit: `0180def936b8bf90cf2793db4ce8920aaa80d56e`
- Original checkout: `/Users/aloobhujia/flipperAgent`
- No commit, merge, push or branch switch performed.

The delegated coder transport returned no filesystem progress. Implementation
was completed in this assigned isolated worktree as an orchestrator transport
fallback. The original checkout was not edited.

## Scope and Files

Added only new V2-owned files:

```text
configs/trendline_v2.yaml
plans/architect-to-coder-trendline-v2-foundation-v1.md
plans/trendline-v2-program-roadmap.md
plans/coder-to-orchestrator-trendline-v2-foundation-v1.md
src/libs/models/trendline_v2/
tests/models/trendline_v2/
```

Package layers are limited to `domain/`, `input/`, `configuration/` and
`discovery/`. No API composition, provider implementation, provider registry,
kernels, tracking, interaction, lifecycle, MTF, storage, research,
optimization or integration package was created.

## Contracts

Domain owns immutable UTC timestamp-space `LineGeometry`, `AnchorRef`, common
`CandidateEvidence`, `LineCandidate`, `DiscoverySnapshot`, closed enums,
canonical primitive serialization and content-addressed IDs. Candidates require
at least two unique ordered causal anchors, confirmation at or before
observation, geometry endpoints equal to outer anchors, anchor prices on the
geometry, and explicit provider provenance.

Input owns normalized confirmed OHLCV. It requires an explicit `observed_at`
and `confirmed_through`, UTC unique monotonic index, finite numeric values,
valid OHLC relationships and non-negative volume. It preserves irregular
timestamps, returns read-only float64 arrays, and hashes the normalized prefix.
Future rows cannot affect a fixed confirmation boundary.

Configuration has strict typed resolution, complete provenance, field policy,
semantic identity and separate runtime settings. YAML loading is confined to
`configuration/loader.py`; no semantic dataclass default can complete missing
canonical YAML. No algorithm or provider parameter is enabled.

Discovery defines only `CandidateProvider`, `ProviderRequest`,
`ProviderDiagnostics`, `ProviderResult` and `ProviderStatus`. Success,
expected abstention and provider failure are distinct. Provider identity is a
deterministic hash of explicit provider name/version. No registry or fallback is
present.

## Import and Ownership Boundaries

Allowed direction:

```text
api -> input, configuration, discovery, domain
discovery -> domain, configuration
input -> domain validation only
configuration -> domain validation and identity only
domain -> standard library and sibling domain modules only
```

Runtime source has no imports or references to:

```text
libs.models.trendline
libs.models.trendline_family
libs.trendlines
libs.models.trendlines_old
app.trendlines
```

Domain source has no pandas, NumPy, YAML, configuration, discovery, research
or optimization import. Existing v1, compatibility, legacy, consumer, runtime,
RegimeV2, signal, selection and research files were not changed.

## Configuration Inventory

```text
model.name             INVARIANT              semantic, YAML/hash
model.version          INVARIANT              semantic, YAML/hash
model.schema_version   INVARIANT              semantic, YAML/hash
runtime.backend        RUNTIME_NON_SEMANTIC   YAML only
runtime.debug          RUNTIME_NON_SEMANTIC   YAML only
```

No `GLOBAL`, `TIMEFRAME`, `ASSET`, `ASSET_TIMEFRAME` or `RESEARCH_OVERRIDE`
model field is enabled yet. Provider parameters, pivot windows, fit thresholds,
quality gates, weights, candidate limits and search spaces remain unresolved.

## Determinism and Causality Evidence

Tests cover future-row invariance, explicit confirmation boundaries, irregular
timestamps, deterministic geometry projection, immutable contracts, canonical
serialization, candidate/snapshot/provider identities, canonical ordering,
malformed payload rejection and provider/status semantics.

Owned parameter effects are explicit: model identity/schema changes semantic
config identity; runtime fields do not; observation/confirmation boundaries
change input identity; candidate content/provider provenance changes candidate
identity; snapshot content changes snapshot identity. No tuning parameter exists
in this phase.

## Validation

```text
V2 focused:
30 passed in 2.83s

V1 protected suite:
399 passed in 31.13s

Ruff:
All checks passed

compileall:
Passed

Import smoke:
8 V2 modules imported successfully

git diff --check:
Passed
```

Exact focused command:

```text
PYTHONPATH=/Users/aloobhujia/flipperAgent-trendline-v2-foundation/src \
  /Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest \
  /Users/aloobhujia/flipperAgent-trendline-v2-foundation/tests/models/trendline_v2 -q -ra
```

Exact protected-suite command:

```text
PYTHONPATH=/Users/aloobhujia/flipperAgent-trendline-v2-foundation/src \
  /Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest \
  /Users/aloobhujia/flipperAgent-trendline-v2-foundation/tests/models/trendline_family -q -ra
```

## Protected Scope and Risks

`src/libs/models/trendline/`, `src/libs/models/trendline_family/`,
`src/libs/trendlines/`, `src/libs/models/trendlines_old/`, `src/apps/`,
`src/libs/models/regime_v2/` and `configs/trendline_family.yaml` remain
unchanged. Original checkout remains clean on `main` at the base commit.

Residual risk is intentionally limited: no provider has been selected, no
discovery output can be produced, no public discovery API exists, and no
provider-specific evidence/parameters are defined. These are later phases.

## Next Unauthorized Phase

Phase 5 provider selection study remains unauthorized until this foundation is
reviewed and explicitly approved. It must not assume fractal/pathfinding or
Hough and must return a new bounded architect handoff before provider code.

## Final State

READY_FOR_ORCHESTRATOR_REVIEW
