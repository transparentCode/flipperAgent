# SR Architecture

## Active implementation

`src/libs/models/sr` is only active Support/Resistance implementation. It owns
immutable contracts, typed configuration, causal detection and association,
lifecycle execution, replay/checkpoint serialization, evaluation, shared
research infrastructure, canonical studies, and viewer tooling.

`src/libs/sr` is not part of this runtime dependency graph. Its separate
kernel-ensemble implementation remains reference-only; see
[`LEGACY_SR_STATUS.md`](LEGACY_SR_STATUS.md).

## Dependency direction

```text
domain + config
        ↓
detection + association + lifecycle
        ↓
replay + serialization
        ↓
evaluation
        ↓
research shared infrastructure
        ↓
research studies
        ↓
scripts compatibility facades + viewer tools
```

- `domain` owns immutable bars, candidates, zones, events, state, snapshots,
  identities, and `ContractValidationError`.
- `config` owns strict YAML loading, schema validation, typed sections,
  resolution, provenance, and resolved identities.
- `detection` confirms causal pivots; `association` matches compatible levels.
- `lifecycle` owns price rules plus deterministic `SREngine` orchestration.
  `validation`, `transitions`, and `creation` retain ordered preconditions,
  existing-zone advancement, and candidate handling.
- `replay`, `serialization`, and `evaluation` consume public core contracts.
- `research` owns neutral artifacts, path safety, provenance, frozen-source,
  window, replay, metric, cohort, evidence, and viewer-payload services.
- `research/studies/<study>` owns study-specific protocol and evidence
  semantics. Eight canonical studies exist: Baseline Trial, ATR Calibration,
  Cohort Readiness, Geometry Sensitivity, Baseline Adequacy, Context Audit,
  Lifecycle Utility, and Candidate Reinforcement Audit.
- `tools` consumes payload APIs. It does not provide computation to research.

## Import and compatibility rules

- Active SR code never imports `libs.sr`.
- Core packages never import research.
- Shared research packages never import studies, runtime services, providers,
  databases, network clients, or viewer tooling.
- Canonical studies never import sibling studies or historical `scripts`
  packages.
- Research never imports `tools`; viewer tools consume canonical payload
  builders instead.
- Active module-scope import graph has no cycles. Exact
  `domain.factory.create_initial_state()` type validation imports
  `config.models` only at function execution, not package import time.
- Root `libs.models.sr` exports configuration and `SREngine` lazily, so a
  domain-only import does not load configuration.

Historical `scripts/<study>` modules, `domain.contracts`,
`evaluation.contracts`, and selected tool exports remain compatibility facades.
They contain imports, `__all__`, docstrings, and needed CLI forwarding only;
canonical implementations own business logic.

Remove a facade only through separately approved change after all public
callers migrate, exact export identity is no longer promised, historical CLI
compatibility has approved replacement, and focused/full regression evidence
passes. This refactor does not remove facades.

## Determinism boundary

Ordering, arithmetic, event construction, state/snapshot identities, replay,
and checkpoint behavior are contracts. `SREngine.step()` remains ordered as:

1. validate inputs;
2. advance existing zones;
3. detect and sort candidates;
4. associate/create candidate zones;
5. build next state;
6. build snapshot and return events.

Refactors must preserve validation ordering, candidate/association visibility,
same-batch behavior, capacity accounting, terminal handling, event ordering,
and canonical payload hashes.
