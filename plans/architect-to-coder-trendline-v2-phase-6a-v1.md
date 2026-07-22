# Architect To Coder: Trendline V2 Phase 6A

Authorization: `PHASE_6A_PROVIDER_CONTRACTS_AUTHORIZED`

Stop state: `PHASE_6B_PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED`

Base:

```text
commit: d460d1858c016bf843c3c4e7099367c40d71d538
worktree: /Users/aloobhujia/flipperAgent-trendline-v2-extrema-contract-v1
branch: feature/trendline-v2-extrema-contract-v1
```

## Objective

Implement Phase 6A contracts only for the approved provider:

```text
provider_name: confirmed_extrema_pair
provider_version: v1
provider_identity: trendline_v2.confirmed_extrema_pair.v1
```

Add typed provider configuration, field policies, semantic request binding,
typed provider evidence, strict identity/serialization rules, workload and
history semantics, tests, and the architecture-only TVLC document.

## Explicit decisions

### History horizon

Evaluate all three plan alternatives in the Phase 6A architecture document and
select timestamp-based duration for provider v1:

```text
history_horizon: lookback_duration_seconds_v1
lookback_duration_seconds: required explicit positive value
```

Reason: timestamp-space geometry and irregular bars make bar-count lookback
physically ambiguous; full-prefix processing is unbounded. The duration value
has unresolved scope and must not enter canonical YAML. No algorithm may be
implemented in this phase.

### Body validation

Select an exact side-validation policy:

```text
body_validation_policy: exact_side_v1
body_clearance_tolerance: absent
```

Support rejects a line strictly above the candle body floor; resistance rejects
a line strictly below the body ceiling. Equality is valid. No raw-price,
basis-point, ATR, epsilon, or hidden numerical tolerance field is allowed.
Any future tolerance requires a new explicit provider contract decision.

### Workload limits

`max_hypotheses` and `max_output_candidates` are semantic because they can
change candidate membership, status, or result. Make both required explicit
provider-config fields, include both in provider-config and request identity,
and never silently truncate. Runtime emergency limits are outside model
configuration and must terminate as operational failure, not return a valid
different result.

### Provider config seam

Use one typed immutable `ProviderConfig` protocol/contract carried directly by
`ProviderRequest`:

```text
ProviderInput
foundation ResolvedTrendlineV2Config
typed provider config
-> combined request identity
```

No constructor state, globals, environment variables, optional mappings,
`dict.get()` fallbacks, or Python semantic defaults. Existing fixture providers
and tests must construct an explicit typed fixture config.

### Provider evidence

Keep universal `CandidateEvidence` unchanged. Add immutable typed
`ConfirmedExtremaPairEvidence` with only:

```text
schema_version
candidate_id association or explicit record identity
extrema_kind
anchor_source_positions
confirmation_positions
validated_intermediate_count
body_violation_count
coordinate_system_version
plateau_policy_version
```

Use tuples, strict scalar validation, canonical serialization, and a validation
method against `ProviderInput` for source/confirmation bounds and future-row
rejection. Do not use free-form metadata. Evidence schema version must
participate in provider identity. Keep provider evidence separate from
universal candidate evidence; do not add quality, score, confidence, rank,
weight, residual, or tolerance fields.

## Required provider config fields

All fields are required constructor arguments. No dataclass defaults:

```text
provider_name
provider_version
plateau_policy
history_horizon
lookback_duration_seconds
left_confirmation_bars
right_confirmation_bars
min_extrema_per_role
body_validation_policy
pair_enumeration_order
candidate_order_version
structural_validation_version
max_hypotheses
max_output_candidates
provider_evidence_schema_version
```

Use immutable enums/version strings where semantics are fixed. Unresolved
semantic values remain fixture-only and `yaml_participation=False`.

## Allowed files

```text
src/libs/models/trendline_v2/configuration/
src/libs/models/trendline_v2/discovery/contracts.py
src/libs/models/trendline_v2/discovery/provider_evidence.py
src/libs/models/trendline_v2/domain/
tests/models/trendline_v2/
plans/
```

Required plan outputs:

```text
plans/trendline-v2-extrema-pair-contract-v1.md
plans/trendline-v2-extrema-pair-config-policy-v1.md
plans/trendline-v2-tvlc-viewer-contract-v1.md
plans/coder-to-orchestrator-trendline-v2-phase-6a-v1.md
```

The final coder handoff must record exact files, decisions, tests, and stop
state. This architect handoff may remain as coordination evidence.

## Forbidden scope

Do not create or modify provider algorithm, registry, kernel, tracking,
interaction, MTF, storage, research, optimization, API, viewer source, YAML
provider values, or old trendline code. Specifically no:

```text
discovery/providers/
discovery/kernels/
src/apps/trendline_v2_viewer/
configs/trendline_v2.yaml provider section
```

No extrema scanner, pair enumeration, candidate generation, Numba, TVLC
dependency, browser code, or chart payload implementation.

## Required tests

Configuration:

- all provider fields appear exactly once in provider field policy;
- no defaults are present for provider config;
- unresolved fields cannot enter canonical YAML;
- semantic workload limits alter provider config and request hashes;
- field reordering does not alter identity;
- missing/unknown/incompatible fields fail closed.

Request:

- explicit typed provider config is required;
- provider config changes request identity;
- input identity remains derived from actual `ProviderInput`;
- mappings and hidden constructor state are rejected.

Evidence:

- universal evidence unchanged;
- provider evidence round-trips canonically;
- immutable tuples/fields;
- invalid source and confirmation positions fail;
- evidence cannot validate against future positions;
- evidence schema participates in provider identity.

Boundaries:

- no provider implementation, registry, Numba, or chart code;
- AST dependency matrix remains clean;
- runtime has no old trendline, SR, RegimeV2, research, or optimization import.

## Validation

Run focused new tests, existing V2 tests, protected family tests, Ruff,
compileall, `git diff --check`, and codebase-memory indexing. Preserve baseline
counts from `d460d18` and report all changed paths. Stop after Phase 6A.
