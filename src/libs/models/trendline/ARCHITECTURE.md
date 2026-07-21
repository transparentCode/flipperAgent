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

The canonical package must never import the legacy trendline implementations,
the support/resistance model, RegimeV2, or a trendline integration. Optimization
and research code may consume canonical seams but runtime modules do not depend on
them.

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
