# Trendline V2 First Provider Selection V1

Status: `READY_FOR_ORCHESTRATOR_REVIEW`

Decision: `OUTCOME_A_SELECTED_PROVISIONALLY`

Authorization: `PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED`

This document records the Phase 5 first-provider study required by the
Trendline V2 next-phase execution plan. It selects a small causal discovery
baseline for review. It does not implement a provider, add configuration, or
change the approved foundation.

## Evidence boundary

The comparison was made against the approved foundation at commit
`31324c601b39978e5e643e6eae209a8076509b99` in the isolated research worktree:

```text
/Users/aloobhujia/flipperAgent-trendline-v2-provider-selection
branch: research/trendline-v2-first-provider-selection-v1
```

The V2 contracts inspected were:

```text
src/libs/models/trendline_v2/domain/provider_input.py
src/libs/models/trendline_v2/discovery/contracts.py
src/libs/models/trendline_v2/domain/candidates.py
src/libs/models/trendline_v2/domain/geometry.py
src/libs/models/trendline_v2/configuration/contracts.py
src/libs/models/trendline_v2/configuration/field_policy.py
src/libs/models/trendline_v2/input/frame.py
tests/models/trendline_v2/test_input.py
tests/models/trendline_v2/test_provider.py
```

The old-model review was read-only and was limited to the approved reference
trees:

```text
src/libs/models/trendline/
src/libs/trendlines/
```

The old implementations and their tests are lessons about failure modes only.
They are not V2 evidence, defaults, or implementation sources. The invalid
saturating-quality evidence bundle was not used.

The current V2 boundary already provides the relevant safety properties for a
provider study:

- `ProviderRequest` binds an immutable `ProviderInput` to a resolved config.
- `ProviderInput` contains the complete normalized causal OHLCV arrays and
  rejects bars after `confirmed_through`.
- `LineGeometry` evaluates in UTC timestamp space.
- `ProviderReason` is a typed abstention/failure code.
- `LineCandidate` and provider results have deterministic semantic identity
  and immutable fields.

## Candidate inventory

### Candidate A: confirmed-extrema anchored discovery

Conceptual sequence:

```text
ProviderInput
  -> confirmed low/high extrema
  -> causal anchor sets
  -> timestamp-space two-anchor line hypotheses
  -> structural body validation
  -> universal evidence and provider evidence
  -> deterministic ordering
```

The proposed first implementation is a direct pair construction, not a copy of
the existing family pathfinding fitter. It uses one pair of same-role extrema
for each line hypothesis. A later path-selection provider can be compared
against this reference without changing the candidate boundary.

The selected causal plateau policy is
`leftmost_strict_left_nonstrict_right_v1`:

- a high must be strictly greater than its configured left neighborhood and
  greater than or equal to its configured right neighborhood;
- a low must be strictly less than its configured left neighborhood and less
  than or equal to its configured right neighborhood;
- the first eligible member of an equal plateau is the representative;
- the pivot is published only after the complete configured right confirmation
  window is present;
- the pivot ID, timestamp, price, and confirmation time are immutable across
  later prefixes.

This is a provider-versioned semantic rule, not a hidden Python default. Its
prefix stability must be proven in Phase 6C.

### Candidate B: deterministic point-Hough discovery

Conceptual sequence:

```text
confirmed wick points
  -> normalized timestamp/price coordinates
  -> deterministic accumulator
  -> deterministic peak selection
  -> support/resistance validation
```

This remains a useful challenger. It is not selected first because the
timestamp and price quantization rules would become semantic parameters before
there is evidence for their scale. No accumulator or quantization was
implemented in this phase.

### Candidate C: robust fitted-line discovery

The candidate family includes:

- least-squares with strict structural gates;
- Theil-Sen pairwise robust fitting;
- a deterministic RANSAC-like exhaustive or prescribed hypothesis search.

Random or seed-dependent RANSAC is inadmissible for the V2 reference provider.
Even deterministic variants require residual units, inlier definitions,
outlier policy, and hypothesis budgets that are not yet approved.

This family is a later challenger, not the first provider.

### Optional fourth candidate

No fourth technique is justified. Adding another fitter would repeat the
robust-fit inductive bias without resolving the first-provider contract or
parameter questions.

## Mandatory gate analysis

The statuses below are design-gate assessments, not market-performance claims.
Phase 6C must turn each selected-provider requirement into executable tests.

### Causality

Candidate A consumes only `ProviderRequest`, and therefore only the explicit
`ProviderInput` and resolved config. It can use a pivot only after its right
confirmation bars are present in the causal input. No row after
`confirmed_through` is visible. A fixed causal prefix must produce exactly the
same candidate payload when future rows are appended.

Candidate B can satisfy the same rule, but a future-aware smoothing or
post-hoc accumulator peak rule would be an easy failure mode. Candidate C can
satisfy the rule when fitting only confirmed points, but robust-fit preprocessing
must be audited for future dependence.

### Irregular timestamps

Candidate A defines every line using the actual UTC epoch timestamps supplied by
`ProviderInput.timestamps`. Intermediate body checks evaluate that same line at
the intermediate candle timestamps. Bar indices may identify array positions,
but cannot determine slope, span, or physical distance.

Candidate B has a higher risk because quantization must choose a time scale for
nonuniform bars. Candidate C is geometrically suitable only if every fit and
residual calculation uses elapsed UTC time rather than an implicit bar index.

### Determinism

Candidate A has no random state. Equal candidates are ordered by an explicit
canonical tuple: role, descending universal quality, descending anchor span,
ordered anchor timestamps, ordered anchor IDs, then candidate ID. A canonical
serialization of the request/config and candidate evidence is used for identity.

Candidate B requires deterministic accumulator traversal, peak suppression, and
tie rules. Candidate C requires deterministic hypothesis enumeration and tie
rules; random RANSAC is rejected.

### Explicit abstention

Candidate A maps outcomes to the existing typed codes:

| Condition | Provider result |
| --- | --- |
| invalid ProviderInput boundary | `FAILED / INVALID_INPUT` |
| invalid or incompatible resolved config | `ABSTAINED / CONFIGURATION_ERROR` |
| too little causal input for the extrema window | `ABSTAINED / INSUFFICIENT_INPUT` |
| fewer than two usable extrema for both roles | `ABSTAINED / INSUFFICIENT_INPUT` |
| no pair survives structural validation | `ABSTAINED / NO_CANDIDATES` |
| unexpected internal provider error | `FAILED / PROVIDER_FAILURE` |

No structure-free line is forced. Operational detail text remains optional and
is excluded from deterministic semantic identity.

### Technique isolation

The provider must live under `libs.models.trendline_v2` and depend only on the
approved V2 domain, configuration, input, and discovery contracts. It must not
import `libs.trendlines`, `app.trendlines`,
`libs.models.trendlines_old`, support/resistance code, RegimeV2, research, or
optimization modules. A provider registry or fallback provider would be a
separate design decision and is not part of this selection.

### Complexity and bounded output

Direct pair construction has a finite but potentially quadratic hypothesis set
in the number of confirmed extrema. Phase 6A must define a validated workload
budget and Phase 6B must reject before unbounded allocation. The budget is a
runtime safety control, not an invented research quality gate; its value remains
unresolved until the implementation workload is measured. The implementation
must expose an explicit abstention rather than silently truncating candidates.

## Qualitative comparison matrix

No weighted numeric score was used.

| Dimension | Candidate A: extrema pairs | Candidate B: point-Hough | Candidate C: robust fit |
| --- | --- | --- | --- |
| Causality | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Geometry | PASS | HIGH_RISK | PASS |
| Determinism | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Interpretability | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Abstention | PASS | ACCEPTABLE_RISK | PASS |
| Candidate multiplicity | ACCEPTABLE_RISK | HIGH_RISK | ACCEPTABLE_RISK |
| Parameter count | ACCEPTABLE_RISK | HIGH_RISK | HIGH_RISK |
| Parameter sensitivity | ACCEPTABLE_RISK | HIGH_RISK | HIGH_RISK |
| Provider evidence | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Runtime | ACCEPTABLE_RISK | HIGH_RISK | ACCEPTABLE_RISK |
| Numba suitability | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Implementation size | PASS | HIGH_RISK | HIGH_RISK |
| Null-data behavior | ACCEPTABLE_RISK | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Extension suitability | PASS | ACCEPTABLE_RISK | ACCEPTABLE_RISK |
| Technique leakage | PASS | PASS | PASS |

The matrix describes engineering risk. It does not claim that Candidate A has
better trading utility or better line quality in unseen data.

## Selected provider

### Decision

Select exactly one provisional first provider:

```text
provider name: confirmed_extrema_pair
provider version: v1
provider identity: trendline_v2.confirmed_extrema_pair.v1
```

This is a selection of an implementation target only. It does not authorize
implementation, configuration activation, runtime use, optimization, or
promotion.

### Algorithm sequence

1. Accept a `ProviderRequest` and validate the request/config identity.
2. Read only the causal arrays in `ProviderInput`.
3. Extract high and low extrema using the fixed, versioned plateau policy.
4. Retain only extrema whose confirmation timestamp is no later than
   `observed_at` and whose source row is in the input prefix.
5. Build ordered same-role pairs with distinct UTC timestamps.
6. Construct exact two-anchor `LineGeometry` in elapsed UTC seconds.
7. Validate intermediate candle bodies at their actual timestamps. A support
   line must not cross the confirmed body floor; a resistance line must not
   cross the confirmed body ceiling. The tolerance contract must be explicit in
   Phase 6A and cannot be a hidden constant.
8. Emit universal evidence from the exact declared anchors. Provider-specific
   extrema and body-validation evidence is retained in a separate typed
   provider-evidence boundary.
9. Apply explicit output bounds and typed abstention if the workload budget is
   exceeded.
10. Sort and serialize candidates with the deterministic ordering contract.

### Identity scope

Candidate identity is asset/timeframe/observation scoped. The canonical
candidate payload includes asset, timeframe, role, timestamp-space geometry,
ordered anchor identity, universal evidence, observation time, provider name,
and provider version. Request identity separately includes the complete input
and resolved configuration identity. This means a structurally identical line
can retain the same candidate identity across equivalent configuration
provenance, while the provider result remains distinguishable by request
identity. Cross-market collisions are not permitted because asset and
timeframe are part of the candidate payload.

### Raw and technique-specific evidence

The universal candidate contract remains limited to evidence that every
provider can define:

```text
anchor_count
distinct_anchor_timestamps
anchor_span_seconds
```

The selected provider additionally needs a typed evidence record containing:

```text
extrema_kind
anchor_source_positions
confirmation_positions
validated_intermediate_count
body_violation_count
geometry_coordinate_system = elapsed_utc_seconds
```

The provider-specific record must not be smuggled into universal fields such as
residual error, inlier ratio, or effective touch count. Those fields are not
defined by the V2 foundation and remain out of scope until a provider contract
gives them units and a causal calculation protocol.

### Expected kernels

The pure Python reference should isolate, but not yet implement, these numeric
loops:

```text
confirmed_extrema_scan
timestamp_space_line_projection
body_clearance_validation
candidate_order_key
```

The first three are suitable for later Numba profiling. Domain contracts,
identity, and abstention decisions must remain Python-owned.

## Why the alternatives are deferred

Point-Hough has a strong multi-line discovery bias, but its accumulator bins,
normalization, peak neighborhood, and suppression rules would dominate the
first experiment. Those choices are difficult to interpret on irregular time
spacing and create high candidate multiplicity.

Robust fitting can be useful when extrema are noisy, but it adds residual
scales, inlier thresholds, outlier handling, hypothesis limits, and possibly a
random process. Least squares is deterministic but not robust; Theil-Sen has a
quadratic pair surface; RANSAC is inadmissible unless fully deterministic. None
is the smallest contract validator.

Candidate A gives the narrowest interpretable baseline against which those
methods can later be compared.

## Later implementation modules

Only after explicit Phase 5 approval, the provisional Phase 6 work may use
modules of this shape:

```text
src/libs/models/trendline_v2/discovery/providers/extrema_pair.py
src/libs/models/trendline_v2/discovery/kernels/extrema.py
src/libs/models/trendline_v2/discovery/kernels/geometry.py
src/libs/models/trendline_v2/discovery/provider_evidence.py
tests/models/trendline_v2/test_extrema_pair_provider.py
```

Phase 6A must happen first and stop for review if any semantic value remains
unresolved. Phase 6B is a pure Python reference; Numba is not part of the
initial implementation.

## Acceptance tests for later authorization

The following are required before the selected provider can be considered for
review:

- future rows cannot change a fixed-prefix result;
- no pivot is emitted before right-side confirmation;
- equal high and low plateaus preserve pivot identity across rolling prefixes;
- irregular and missing UTC bars produce timestamp-space, not index-space,
  geometry;
- identical request/config bytes produce identical result bytes, candidate
  IDs, ordering, diagnostics, and abstention code;
- support candidates use confirmed low extrema and resistance candidates use
  confirmed high extrema;
- intermediate candle-body validation uses the emitted geometry;
- invalid input, insufficient input, no candidates, configuration errors, and
  provider failures use typed result semantics;
- workload bounds prevent unbounded pair allocation;
- universal evidence and provider-specific evidence remain separate;
- no runtime import reaches old trendline packages, SR, RegimeV2, research, or
  optimization;
- parameter-effect tests show each active field changes only its owned stage.

Synthetic recovery and null-data tests are implementation checks only. They do
not establish market utility.

## Explicit non-goals

Phase 5 does not implement or authorize:

- any provider or registry;
- provider-specific config or canonical YAML values;
- Hough accumulators or quantization;
- robust fitting, RANSAC, or Theil-Sen;
- tracking, family state, lifecycle, interactions, MTF, or RegimeV2;
- optimization, promotion, trading signals, or PnL analysis;
- Numba kernels;
- runtime fallback between providers.

## Review disposition

The provisional decision is `OUTCOME_A_SELECTED_PROVISIONALLY`. The required
orchestrator review must confirm the matrix, unresolved parameter list,
identity scope, and provider-specific evidence boundary before any Phase 6
handoff becomes active.

Final phase state:

```text
READY_FOR_ORCHESTRATOR_REVIEW
PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED
PHASE_6_NOT_AUTHORIZED
```
