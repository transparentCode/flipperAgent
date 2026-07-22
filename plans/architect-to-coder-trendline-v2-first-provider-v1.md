# Architect To Coder: Trendline V2 First Provider V1

## Authorization gate

```text
PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED
PHASE_6_NOT_AUTHORIZED
```

This is a provisional handoff for orchestrator review. Do not implement from
this document until the orchestrator explicitly approves the Phase 5 provider
selection and issues a separate Phase 6 authorization.

## Approved source boundary

The design targets the foundation at:

```text
commit: 31324c601b39978e5e643e6eae209a8076509b99
package: src/libs/models/trendline_v2/
branch: research/trendline-v2-first-provider-selection-v1
```

The intended first provider is:

```text
name: confirmed_extrema_pair
version: v1
identity: trendline_v2.confirmed_extrema_pair.v1
```

The selection is not a claim about market utility. It is a choice of the
smallest causal, deterministic reference technique for later contract and
implementation review.

## Work that may be authorized later

If Phase 5 is approved, split the work as follows and stop after each review
boundary.

### Phase 6A: provider-specific contracts and configuration

Add only the contracts needed to make the selected provider explicit:

```text
provider-specific configuration contract
provider-specific evidence contract
field policies and scope metadata
strict validation and semantic identity
```

The contract must define, without Python defaults:

- the versioned leftmost plateau policy;
- the left and right confirmation fields and their units;
- the minimum extrema count semantics;
- timestamp-space body validation and tolerance units;
- workload/output bounds and explicit overflow semantics;
- provider evidence separate from universal `CandidateEvidence`;
- identity treatment for request/config and candidate payloads.

Any unresolved semantic value stops Phase 6A before algorithm implementation.
No canonical YAML value is allowed until the field has an approved scope and
parameter-effect test.

### Phase 6B: pure Python reference provider

Only after Phase 6A approval, implement the clear Python reference. The
proposed algorithm is:

1. Accept one immutable `ProviderRequest`.
2. Use only its causal `ProviderInput` arrays and resolved config.
3. Extract confirmed high and low extrema using
   `leftmost_strict_left_nonstrict_right_v1`.
4. Build same-role two-anchor hypotheses in UTC elapsed-time space.
5. Validate intermediate candle bodies using the emitted geometry and actual
   timestamps.
6. Emit universal evidence and a typed provider-evidence record.
7. Apply explicit workload bounds before materializing unbounded pairs.
8. Return typed success, abstention, or failure results.
9. Apply canonical ordering and deterministic serialization.

No Numba is used in the reference implementation.

### Phase 6C: provider validation

Required tests before provider review:

- future rows cannot alter a fixed-prefix result;
- high and low plateau identities remain stable across rolling prefixes;
- no pivot is available before its right confirmation;
- support candidates derive from low extrema;
- resistance candidates derive from high extrema;
- irregular and missing UTC bars use elapsed timestamps, not bar indices;
- emitted geometry is the geometry used for body validation;
- identical request/config produces identical bytes, IDs, order, diagnostics,
  and typed abstention code;
- malformed, insufficient, and structure-free inputs abstain explicitly;
- workload/output limits cannot silently truncate candidates;
- universal and provider-specific evidence remain separate;
- every active parameter has a parameter-effect test;
- no source import reaches old trendline packages, SR, RegimeV2, research, or
  optimization.

Synthetic recovery, noisy-line, outlier, null-data, and workload fixtures are
implementation evidence only. They do not authorize market claims.

## Files proposed after authorization

Do not create these files in Phase 5. They are the expected Phase 6 shape only:

```text
src/libs/models/trendline_v2/discovery/providers/__init__.py
src/libs/models/trendline_v2/discovery/providers/extrema_pair.py
src/libs/models/trendline_v2/discovery/provider_evidence.py
src/libs/models/trendline_v2/discovery/kernels/extrema.py
src/libs/models/trendline_v2/discovery/kernels/geometry.py
tests/models/trendline_v2/test_extrema_pair_provider.py
tests/models/trendline_v2/test_extrema_pair_causality.py
tests/models/trendline_v2/test_extrema_pair_determinism.py
```

The package layout is provisional until Phase 6A confirms the contract
boundary. A registry, fallback provider, or public discovery API is not part of
this handoff.

## Provenance and copying rule

No provider code is copied by this Phase 5 study.

The old reference review found useful lessons in the pathfinding, fractal,
least-squares, and RANSAC modules, including index-space geometry risk,
configuration-heavy search grids, and random RANSAC behavior. Those sources
remain outside the V2 runtime and are not implementation dependencies.

If a future implementation proposes adaptation from an old source, a new
review must name all of:

```text
source commit
source file
source symbol
adaptation required
behavior intentionally retained
behavior intentionally removed
independent tests
```

Without that provenance record, copying is not authorized.

## Explicit non-goals

Do not implement or alter:

- Candidate B point-Hough or any accumulator/quantization;
- Candidate C least-squares, Theil-Sen, or RANSAC;
- tracking, family state, lifecycle, interactions, MTF, or RegimeV2;
- optimization, promotion, runtime configuration, signals, or PnL;
- Numba kernels or performance claims;
- provider fallback, registry, or multi-provider selection;
- old `libs.trendlines`, `app.trendlines`, or
  `libs.models.trendlines_old` consumers.

## Required coder stop condition

The coder must stop and return `BLOCKED` if any of the following is true:

- Phase 5 is not explicitly approved;
- any provider-specific semantic value is unresolved;
- a parameter has no owner, units, domain, or effect test;
- a workload cap would silently change candidate semantics;
- universal contracts need provider-specific fields without an approved
  contract change;
- a proposed implementation needs hidden constructor state or a second input
  path;
- a test requires future rows, centered calculations, index-space geometry, or
  random ordering.

## Expected review result

This handoff remains provisional until the orchestrator confirms:

```text
provider selection: confirmed_extrema_pair v1
parameter inventory: accepted with unresolved values kept inactive
identity scope: accepted
evidence boundary: accepted
Phase 6A: separately authorized or rejected
```

Until then, the only valid state is:

```text
PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED
```
