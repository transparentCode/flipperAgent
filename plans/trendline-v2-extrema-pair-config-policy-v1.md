# Trendline V2 Extrema Pair Config Policy V1

Status: `PHASE_6A_READY_FOR_REVIEW`

## Ownership

Provider fields are registered through `provider_field_policies()`. Foundation
fields remain owned by `field_policies()`. `all_field_policies()` combines both
registries for audit. Provider fields are not part of canonical YAML resolution.

Every provider field is unique, required, semantic where marked, hash-bound,
and has explicit owner, type, scope, derivation source, and evidence status.

## Policy table

| Field | Owner | Type | Allowed scope | Class | Required | Semantic/hash | YAML |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `provider.name` | identity | string | global | INVARIANT | yes | yes | no |
| `provider.version` | identity | string | global | INVARIANT | yes | yes | no |
| `provider.plateau_policy` | extrema | enum | global | INVARIANT | yes | yes | no |
| `provider.history_horizon` | horizon | enum | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.lookback_duration_seconds` | horizon | positive seconds | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.left_confirmation_bars` | extrema | positive bars | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.right_confirmation_bars` | extrema | positive bars | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.min_extrema_per_role` | hypothesis | count >= 2 | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.body_validation_policy` | validation | enum | global | INVARIANT | yes | yes | no |
| `provider.pair_enumeration_order` | hypothesis | enum | global | INVARIANT | yes | yes | no |
| `provider.candidate_order_version` | ordering | version string | global | INVARIANT | yes | yes | no |
| `provider.structural_validation_version` | validation | version string | global | INVARIANT | yes | yes | no |
| `provider.max_hypotheses` | workload | count >= 1 | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.max_output_candidates` | workload | count >= 1 | global/timeframe/asset/asset-timeframe | UNRESOLVED | yes | yes | no |
| `provider.provider_evidence_schema_version` | evidence | version string | global | INVARIANT | yes | yes | no |

## Resolution rules

- Provider config is constructed explicitly; no resolver reads it from YAML.
- Canonical `trendline_v2.yaml` remains foundation-only.
- Unknown provider fields fail closed.
- Missing provider fields fail at typed construction.
- Boolean values are not accepted as integer counts.
- Numeric values must be finite and positive where specified.
- Field ordering cannot affect semantic identity.
- Unresolved fields are fixture-only and cannot become production values.
- Workload limits are semantic because they can change result membership/status.
- `birth_quality_threshold` belongs to tracking and is not provider config.

## Required future evidence

Before any unresolved field becomes YAML-active, run scope comparison in order:

```text
global -> timeframe -> asset -> asset-timeframe only when needed
```

Report fold stability, cross-asset/timeframe consistency, candidate density,
abstention, metric variance, parameter stability, and complexity. Add one
parameter-effect test per active field. No values or gates are selected here.

## Phase boundary

This policy adds no provider implementation, registry, numerical kernel,
viewer, YAML provider section, or runtime integration.
