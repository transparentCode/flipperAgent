# Architect to Coder: Trendline V2 Foundation V1

## Objective

Implement only the authorized Trendline V2 foundation assignment from the
Trendline V2 Clean Development Program:

- Phase 0: program contract and repository reconnaissance;
- Phase 1: domain contracts and identity;
- Phase 2: causal confirmed-OHLCV input boundary;
- Phase 3: strict configuration foundation;
- Phase 4: technique-independent provider protocol.

The new implementation is independently owned under
`src/libs/models/trendline_v2/`. Existing trendline packages are read-only
references and runtime dependencies are forbidden.

## Base and Worktree

- Base branch: `main`
- Base commit: `0180def936b8bf90cf2793db4ce8920aaa80d56e`
- Worktree: `/Users/aloobhujia/flipperAgent-trendline-v2-foundation`
- Branch: `feature/trendline-v2-foundation-v1`
- Original checkout: `/Users/aloobhujia/flipperAgent`, must remain clean and on
  `main`.

The canonical v1 suite baseline on the clean base is:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
399 passed in 133.49s
```

## Reconnaissance Evidence

The indexed repository contains the established v1 stateful implementation at
`src/libs/models/trendline/`, its explicit compatibility namespace at
`src/libs/models/trendline_family/`, and separate legacy namespaces at
`src/libs/trendlines/` and `src/libs/models/trendlines_old/`. No
`src/libs/models/trendline_v2/` package exists on the base.

The v1 scoped graph contains domain, discovery, tracking, interaction, MTF,
optimization and research modules. Existing v1 and downstream consumers must
not be changed by this foundation assignment. In particular, do not edit the
v1 RegimeV2 trendline producers, signal projections, research scripts, YAML,
runtime workers, or legacy trees.

## Approved Runtime Dependency Direction

```text
api -> input, configuration, discovery, domain
discovery -> domain, configuration, kernels (only if a later approved kernel exists)
input -> domain validation only
configuration -> domain validation and identity only
kernels -> NumPy and primitive numeric types only
domain -> Python standard library only
```

For this foundation there is no `kernels/` package and no provider registry.
Do not create either merely for future extensibility.

Forbidden imports anywhere under `src/libs/models/trendline_v2/`:

```text
libs.models.trendline
libs.models.trendline_family
libs.trendlines
libs.models.trendlines_old
app.trendlines
RegimeV2, signal, selection, runtime, research, optimization, storage,
tracking, interaction, mtf, visualization
```

Domain modules must not import pandas, NumPy, configuration, discovery, API,
or kernels. Input may use pandas and NumPy, but must expose only its own typed
boundary and domain-safe values. Research/integration code is not part of this
package.

## Phase 1 Contract

Add only `trendline_v2/domain/` modules:

- `enums.py`: closed role/status/reason enums;
- `geometry.py`: finite UTC timestamp-space `LineGeometry` with deterministic
  primitive serialization and exact point projection;
- `candidates.py`: immutable `AnchorRef`, immutable common candidate evidence,
  and immutable `LineCandidate`;
- `snapshots.py`: immutable `DiscoverySnapshot` containing a deterministic,
  stably ordered candidate tuple and explicit status/reason;
- `identity.py`: canonical primitive serialization plus content-addressed IDs;
- `serialization.py`: deterministic JSON-safe primitive conversion;
- `validation.py`: domain-only validation errors and finite/UTC checks.

Minimum evidence fields must be explicit common fields only: anchor count,
distinct anchor timestamps, anchor span, wrong-side violation count, residual
error, and effective touch count. Do not create a free-form metadata or
provider-evidence dump. Provider-specific evidence belongs to a later provider
contract after provider selection.

Every published candidate must bind `observed_at`, role, geometry, at least two
causal anchors, provider identity, and deterministic candidate ID. Anchor
confirmation time must not be later than candidate observation time. Candidate
ordering and snapshot identity must be independent of input mapping order.

Do not add pivots, fitting, pathfinding, Hough, tracking or interaction fields.

## Phase 2 Contract

Add only `trendline_v2/input/` and its frame boundary. It must:

- require a non-empty pandas DataFrame;
- require canonical `open`, `high`, `low`, `close`, `volume` columns;
- require a UTC `DatetimeIndex`, monotonic increasing and duplicate-free;
- reject non-finite and invalid OHLCV values;
- require explicit `observed_at` and explicit `confirmed_through` (or an
  equivalent named confirmation boundary); never infer final-row confirmation;
- include only rows known and confirmed at the requested boundary;
- preserve irregular timestamps without inferred resampling;
- expose stable float64 NumPy arrays from the validated copied frame;
- derive one content-addressed input identity from canonical timestamp/value
  bytes and boundary metadata.

Future rows, duplicate rows, timezone-naive input, non-monotonic input,
non-finite values, and invalid OHLC relationships must fail explicitly. A
fixed observed boundary must produce byte-identical output when future rows are
appended.

## Phase 3 Contract

Add only the configuration foundation and `configs/trendline_v2.yaml`.

Requirements:

- typed immutable resolved config;
- strict schema/unknown-field/type validation;
- complete canonical YAML for fields actually required by Phases 1–4;
- no semantic dataclass defaults and no invented algorithm parameters;
- field policy with exactly one classification per field from
  `INVARIANT`, `DERIVED`, `GLOBAL`, `TIMEFRAME`, `ASSET`,
  `ASSET_TIMEFRAME`, `RUNTIME_NON_SEMANTIC`, `RESEARCH_OVERRIDE`,
  `UNRESOLVED`;
- provenance for every resolved field;
- semantic configuration identity/hash;
- separate runtime non-semantic config excluded from semantic hash;
- deterministic derivation module only for approved protocol derivations;
- fail closed on incomplete canonical YAML and disallowed scopes.

Only protocol identity/invariant fields needed by the foundation may be
present. Provider parameters, pivot windows, fit thresholds, quality gates,
weights, maximum candidates, timeframe defaults, asset defaults and search
spaces are unresolved and must not be invented or enabled. If implementation
requires any such value, stop with `BLOCKED` and identify the choice.

Research overrides must remain outside production resolution and must be
explicitly provenance-recorded if represented at all.

## Phase 4 Contract

Add only `trendline_v2/discovery/contracts.py` and package exports.

Define a small protocol and immutable contracts:

- `CandidateProvider` protocol;
- `ProviderRequest` bound to asset, timeframe, observed/confirmation boundary,
  input identity and resolved configuration identity;
- closed `ProviderStatus` distinguishing success, expected abstention and
  provider failure;
- typed provider result containing canonical candidate tuples and typed
  diagnostics/reason fields;
- deterministic, versioned provider identity.

Do not implement a provider, provider registry, provider-specific fields,
fallback provider, fallback config, or provider selection. Provider failure
must not be converted into a normal abstention and unexpected exceptions must
not be swallowed.

## Required Tests

Add tests under `tests/models/trendline_v2/` for:

- immutable domain objects and recursive value validation;
- UTC, finite geometry and causal anchor checks;
- deterministic primitive serialization, IDs and stable ordering;
- domain import boundary;
- input validation, explicit confirmation boundary, future-row invariance,
  irregular timestamps, duplicate/non-monotonic/timezone/non-finite/OHLC
  rejection, and input identity round trip;
- complete strict config/policy ownership, unknown/type/scope/incomplete YAML
  rejection, deterministic resolution, provenance, semantic-vs-runtime hash,
  and derived-field non-overridability;
- provider protocol conformance, invalid result rejection, deterministic
  provider identity, success versus abstention versus failure, and absence of
  technique-specific fields;
- no `trendline_v2` runtime import of any old trendline namespace;
- no provider implementation, registry, tracker, interaction, MTF, research,
  optimization or downstream integration.

Run focused tests first, then the full new suite, then the v1 baseline suite.

## Explicit Non-Goals

Do not implement or modify:

- fractal, Hough, pathfinding, robust regression, or any provider;
- provider selection study;
- Numba or numeric kernels;
- candidate quality or scoring;
- family matching/tracking/lifecycle;
- interactions/events/MTF/channels;
- storage/replay history;
- research artifacts/optimization;
- RegimeV2, signal, selection, runtime or TVLC integration;
- v1 or legacy implementation/consumers;
- compatibility imports into Trendline V2.

## Acceptance and Stop Rules

Stop as `BLOCKED` rather than inventing a semantic value, weakening a
contract, adding a future placeholder package, or hiding an exception.

Required validation:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
ruff check src/libs/models/trendline_v2 tests/models/trendline_v2
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2
git diff --check
```

Also report import-boundary scan, exact pass/skip/failure counts, protected
v1/legacy files unchanged, and original checkout clean. Do not commit or merge
from the coder worktree unless explicitly requested.

## Required Coder Return

Create `plans/coder-to-orchestrator-trendline-v2-foundation-v1.md` in the
isolated worktree. Include objective, branch/worktree/base, scope and
non-goals, changed files, import graph, contracts, configuration fields and
classifications, unresolved assumptions, parameter-effect evidence, causality
and determinism evidence, exact validation, protected-scope confirmation,
commit status, residual risks, unauthorized next phase, and final marker:

```text
READY_FOR_ORCHESTRATOR_REVIEW
```

or:

```text
BLOCKED
```

Stop after Phase 4. Do not begin Phase 5.
