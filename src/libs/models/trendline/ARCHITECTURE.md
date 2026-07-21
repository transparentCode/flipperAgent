# Canonical Trendline Model Architecture

`libs.models.trendline` is the sole runtime owner of the canonical trendline-family
model. This package makeover preserves the existing algorithms, public outputs,
identities, serialization, configuration hashes, and causal state transitions.

## Dependency direction

Runtime dependencies flow in one direction:

```text
api
  -> tracking / interaction / mtf
  -> discovery
  -> domain
```

The parallel low-level boundaries are:

```text
configuration -> domain validation and identity only
storage       -> domain only
kernels       -> NumPy arrays and numeric scalars only
integrations  -> canonical trendline API
```

The canonical runtime package must never import the legacy trendline
implementations, the support/resistance model, RegimeV2, or a trendline
integration. Optimization and research code may consume canonical seams, but
runtime owner modules do not depend on them. The two deprecated ablation
compatibility facades under `optimization` lazily forward to the RegimeV2
integration; they are explicitly outside the runtime dependency graph.

## Ownership target

| Boundary | Owns | Does not own |
| --- | --- | --- |
| `domain` | immutable contracts, enums, identities, primitive serialization and validation | orchestration, persistence, integrations |
| `configuration` | typed semantic profiles, scope policy, resolution, derivation and provenance | market metadata, runtime execution policy |
| `discovery` | confirmed-frame validation, pivots, fitting and complete candidate providers | family state |
| `tracking` | matching, rails, corridors, family lifecycle, ranking and update phases | candidate techniques |
| `interaction` | ATR-normalized contact observations, event lifecycle and features | family persistence |
| `mtf` | downstream projection, freshness, relations, clustering, composition and feature export | single-timeframe mutation |
| `storage` | repository protocol, snapshot serialization and in-memory implementation | model decisions |
| `kernels` | pure deterministic numeric loops | pandas, domain/config objects, storage |

Root modules are transitional compatibility paths. When ownership moves, each
root module becomes an explicit forwarding module whose exports are the same
runtime objects as the owning module. `libs.models.trendline_family` remains a
forwarding-only compatibility package.

Owner packages import direct owner modules. They do not use transitional root
facades internally. Discovery contracts own provider protocols and result types;
provider implementations depend on those contracts.

## Tracker update phases

`TrendlineFamilyTracker.update()` is orchestration over nine explicit phases:

```text
confirmed frame -> prior state -> candidates -> rails/association
-> family lifecycle -> interactions/events -> snapshot -> persistence -> output
```

Frozen phase-result records make each boundary testable without relocating
state-machine policy into domain objects. Phase replay tests compare serialized
snapshot bytes, identities, transitions, events, features, ordering, and repository
writes with the public update path.

## MTF ownership

`mtf/composition.py` validates sources and orchestrates only. Immutable contracts
and validation live in `contracts.py`; projection, freshness, relations,
clustering, serialization, feature projection, and latest-snapshot storage each
live in their named owner module. MTF remains downstream and cannot mutate
single-timeframe state.

## Numeric execution

`kernels/atr.py` owns the shared deterministic true-range loop and accepts only
NumPy arrays plus an integer window. Validated pandas adapters in `interaction.atr`
and `tracking.matching` apply `min(configured_window, row_count)` before dispatch.
Compiled and `.py_func` modes are runtime-only choices and produce identical model
objects and serialized snapshots.

## Locked behaviour

The baseline suite locks candidate-provider payload hashes, snapshot identity,
transition and event identity, serialization, repository lineage, MTF identity,
configuration hashes, compatibility imports, and future-row invariance. The
makeover adds boundaries one subsystem at a time; a changed identity, serialized
payload, resolved semantic value, or causal replay result is a stop condition.

## Migration sequence

1. Lock import and architecture boundaries.
2. Move domain contracts behind forwarding imports.
3. Formalize scoped YAML configuration and provenance.
4. Move candidate discovery.
5. Move tracking and interaction services.
6. Split MTF and storage responsibilities.
7. Extract RegimeV2 ownership into its integration.
8. Add only measured deterministic Numba kernels.
9. Close compatibility paths and record validation evidence.
