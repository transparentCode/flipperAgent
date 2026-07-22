# Trendline V2 First Provider Hyperparameters V1

Status: `DESIGN_ONLY`

Authorization: `PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED`

This inventory belongs to the Phase 5 provider-selection study. It records the
parameters that each candidate technique would need and the evidence required
before any field becomes an active V2 configuration value. No value in this
document is a canonical YAML default.

## Classification rules

The allowed classifications are:

```text
INVARIANT
DERIVED
GLOBAL
TIMEFRAME
ASSET
ASSET_TIMEFRAME
RUNTIME_NON_SEMANTIC
RESEARCH_OVERRIDE
UNRESOLVED
```

The scope decision order is protocol invariant, deterministic derivation,
global normalization, timeframe dependence, asset microstructure, and finally
asset-timeframe dependence. Every semantic tunable below is `UNRESOLVED`
until that order is tested. An unresolved field cannot be added to canonical
YAML.

The following are protocol invariants already owned by the foundation and are
not provider hyperparameters:

| Field | Owner | Type and units | Role | Classification | Source |
| --- | --- | --- | --- | --- | --- |
| `input_data.asset` | provider boundary | non-empty string | market identity | INVARIANT | `ProviderInput` |
| `input_data.timeframe` | provider boundary | non-empty string | bar identity | INVARIANT | `ProviderInput` |
| `input_data.confirmed_through` | provider boundary | UTC instant | causal cutoff | INVARIANT | `ProviderInput` |
| `input_data.timestamps` | provider boundary | strictly increasing epoch ns | physical x-coordinate | INVARIANT | `ProviderInput` |
| `input_data.open/high/low/close/volume` | provider boundary | finite numeric arrays | causal observations | INVARIANT | `ProviderInput` |
| `coordinate_system` | provider | elapsed UTC seconds | line geometry | INVARIANT | `LineGeometry` contract |
| `candidate_order_version` | provider | version string | deterministic ordering | INVARIANT | provider identity |
| `evidence_schema_version` | provider | version string | evidence identity | INVARIANT | provider evidence contract |

## Candidate A inventory: confirmed extrema pairs

The selected provider is `trendline_v2.confirmed_extrema_pair.v1`. The
following fields are required to make its semantics explicit.

| Field | Owner | Type and units | Mathematical role | Valid domain | Expected effect and interactions | Classification | Derivation/source | Sensitivity test and evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `provider_name` | provider identity | string | selects technique | exact `confirmed_extrema_pair` | Changing it selects a different provider, not a stage parameter | INVARIANT | Phase 5 decision | identity test; exact provider selection |
| `provider_version` | provider identity | string | freezes algorithm semantics | non-empty version | Any semantic algorithm change must change version | INVARIANT | Phase 5 decision | identity and serialization parity |
| `plateau_policy` | extrema stage | enum/version | chooses equal-value representative | exact `leftmost_strict_left_nonstrict_right_v1` | Changes pivot membership and IDs; interacts with both confirmation windows | INVARIANT | causal prefix requirement | rolling-prefix high/low plateau test |
| `left_confirmation_bars` | extrema stage | integer bars | strict prior neighborhood | positive integer | Larger value reduces extrema density; interacts with right window and input length | UNRESOLVED | provider semantics, no approved value | global -> timeframe effect and density audit |
| `right_confirmation_bars` | extrema stage | integer bars | delayed causal confirmation | positive integer | Larger value delays publication and reduces usable extrema; interacts with observed cutoff | UNRESOLVED | causal requirement, no approved value | prefix causality and confirmation-delay audit |
| `min_extrema_per_role` | hypothesis stage | integer count | minimum available low/high anchors before pair generation | integer >= 2 | Raising it increases abstention; must not silently change pair scoring | UNRESOLVED | provider semantics, no approved value | boundary counts, abstention and cross-scope stability |
| `body_clearance_tolerance` | structural validation | finite price or normalized-price scalar | tolerance for line/body contact | non-negative, units must be fixed before activation | Larger tolerance admits more lines and can increase false structure; interacts with price normalization | UNRESOLVED | provider contract must define units | irregular timestamp body tests and near-boundary sweep |
| `max_hypotheses` | workload boundary | integer count | upper bound before pair materialization | positive bounded integer | Must only bound workload; exhaustion must be explicit and deterministic | RUNTIME_NON_SEMANTIC | DoS protection, measured later | workload bound, no semantic candidate-ranking effect |
| `max_output_candidates` | workload boundary | integer count | upper bound on emitted results | positive bounded integer | Must not silently truncate; return typed provider failure/abstention when exceeded | RUNTIME_NON_SEMANTIC | output safety, measured later | bounded-output and deterministic overflow tests |
| `pair_enumeration_order` | hypothesis stage | enum/version | stable traversal of role pairs | exact canonical chronological order | Changing it must not change output after canonical sorting | INVARIANT | deterministic contract | permutation and repeatability tests |
| `structural_validation_version` | validation stage | version string | freezes body-crossing rules | non-empty version | Any rule change changes provider version or evidence schema | INVARIANT | provider identity | exact geometry and violation audit |

No `min_quality` field is selected for Candidate A at Phase 5. The V2
foundation has no provider-neutral quality definition. Adding such a field
before a provider evidence contract exists would create a hidden technique
parameter. If later required, it must be introduced as a provider-owned field
with explicit units and a parameter-effect test.

### Candidate A scope protocol

`left_confirmation_bars`, `right_confirmation_bars`, and
`min_extrema_per_role` are not assumed global or asset/timeframe-specific.
Later evidence must compare:

```text
global -> timeframe -> asset -> asset-timeframe only when needed
```

The comparison must include fold stability, cross-asset and cross-timeframe
consistency, coverage, abstention rate, candidate density, metric variance,
parameter stability, and complexity. A higher in-sample mean is not sufficient
to justify a more specific scope.

## Candidate B inventory: deterministic point-Hough

Candidate B is not selected, but its complete parameter surface is recorded so
that a later challenger cannot hide quantization choices.

| Field | Owner | Type and units | Mathematical role | Valid domain | Expected effect and interactions | Classification | Derivation/source | Sensitivity test and evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `point_source` | point extraction | enum | chooses wick/extrema points | confirmed high/low only | Changing source changes evidence population | INVARIANT | candidate definition | source-boundary and prefix tests |
| `time_normalization` | coordinate stage | enum | maps UTC timestamps to x coordinates | elapsed UTC seconds only | Index-space alternative is forbidden | INVARIANT | irregular timestamp gate | missing-bar geometry test |
| `price_normalization` | coordinate stage | enum/version | scales price before voting | explicit deterministic rule | Changes accumulator occupancy and peak identity | UNRESOLVED | no approved scale | scale invariance and cross-asset audit |
| `time_bin_width` | accumulator | finite seconds | x quantization width | positive | Larger bins merge structures; interacts with price bins and peak neighborhood | UNRESOLVED | Hough design | boundary and irregular-spacing sweep |
| `price_bin_width` | accumulator | finite price/normalized units | y quantization width | positive | Larger bins merge lines; interacts with normalization | UNRESOLVED | Hough design | boundary and cross-asset sweep |
| `vote_threshold` | accumulator | integer votes | minimum support for a peak | positive count | Larger value reduces multiplicity and increases abstention | UNRESOLVED | Hough design | support frontier and null-data test |
| `peak_neighborhood` | peak selector | integer bins | non-maximum suppression radius | non-negative integer | Larger value reduces nearby candidates; interacts with bin widths | UNRESOLVED | Hough design | candidate identity and density sweep |
| `max_peaks_per_role` | output boundary | integer count | output bound | positive bounded integer | Workload-only if overflow is explicit | RUNTIME_NON_SEMANTIC | DoS protection | bounded-output test |
| `max_accumulator_bins` | workload boundary | integer count | memory cap | positive bounded integer | Must abstain/fail explicitly before allocation | RUNTIME_NON_SEMANTIC | DoS protection | allocation-bound test |
| `body_clearance_tolerance` | structural validation | finite price/normalized scalar | validates emitted peaks | non-negative | Larger value admits more lines | UNRESOLVED | provider contract | body validation sweep |
| `accumulator_version` | accumulator | version string | freezes vote semantics | non-empty | Any quantizer change changes version | INVARIANT | provider identity | serialization parity |

Point-Hough cannot be activated until a deterministic price/time normalization
is defined. No Hough values are proposed here.

## Candidate C inventory: robust fitted lines

The family contains deterministic least-squares, Theil-Sen, and a possible
deterministic exhaustive RANSAC-like implementation. A random seed is not an
acceptable implementation parameter for the V2 reference provider.

| Field | Owner | Type and units | Mathematical role | Valid domain | Expected effect and interactions | Classification | Derivation/source | Sensitivity test and evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fit_method` | fitter | enum | selects LS, Theil-Sen, or exhaustive robust fit | explicit deterministic method | Changes residual and line identity semantics | INVARIANT per provider version | candidate definition | method parity and identity tests |
| `point_source` | fitter input | enum | selects confirmed extrema/wicks | confirmed points only | Changes fit population | INVARIANT | causal gate | source and prefix tests |
| `coordinate_system` | fitter | enum | physical x coordinate | elapsed UTC seconds only | Index-space fit is forbidden | INVARIANT | geometry gate | irregular-spacing regression |
| `residual_tolerance` | fit validation | finite price or normalized scalar | inlier/fit acceptance radius | non-negative | Larger value admits more inliers and lines | UNRESOLVED | no approved units | residual boundary and cross-asset audit |
| `residual_scale` | fit validation | enum/version | price, ATR, or normalized scale | explicit deterministic scale | Changes comparability and interactions with tolerance | UNRESOLVED | no approved scale | scale-effect and invariance audit |
| `min_inliers` | fit validation | integer count | minimum support evidence | integer >= 2 | Larger value increases abstention | UNRESOLVED | provider semantics | support and null-data test |
| `min_anchor_span_seconds` | fit validation | finite seconds | minimum physical span | positive | Larger value rejects short structures; interacts with timeframe | UNRESOLVED | no approved value | boundary and scope study |
| `wrong_side_tolerance` | structural validation | finite price/normalized scalar | permits bounded body-side error | non-negative | Larger value weakens structural rejection | UNRESOLVED | provider contract | wrong-side adversarial test |
| `outlier_policy` | fitter | enum/version | defines ignored points | deterministic only | Changes support and residual evidence | INVARIANT per method version | provider semantics | outlier fixture and identity test |
| `max_hypotheses` | workload boundary | integer count | bounds pair/fit work | positive bounded integer | Must not silently truncate | RUNTIME_NON_SEMANTIC | DoS protection | workload test |
| `max_trials` | robust fitter | integer count | only for a prescribed deterministic search | positive bounded integer | More trials can increase candidates; no random sampling | UNRESOLVED | algorithm choice unresolved | boundary and determinism test |
| `hypothesis_order` | robust fitter | enum/version | deterministic pair traversal | canonical order | Must not depend on hash/random order | INVARIANT | deterministic contract | permutation test |
| `fit_version` | provider identity | version string | freezes numerical semantics | non-empty | Any fit rule change changes version | INVARIANT | provider identity | byte and ID parity |

`seed` is intentionally absent. A seed-dependent algorithm is not a V2
reference provider. A future deterministic pseudo-random search would need an
explicit protocol decision, but that is not authorized by this study.

## Fields explicitly outside this inventory

`birth_quality_threshold` belongs to Phase C family tracking and must not be
used to select or score a discovery provider. Tracking, interaction, MTF,
RegimeV2, optimization, and trading policy fields are outside Phase 5.

The current foundation `model.name`, `model.version`, and `model.schema_version`
remain configuration invariants. No provider-specific field is added to the
existing YAML in this phase.

## Sensitivity-study design

Phase 5 defines a later study rather than running one. For each field approved
in Phase 6A, use the following protocol.

### Parameter effect

For one field at a time, hold the causal input, provider version, and all other
resolved values fixed. Verify that the field changes only its owned stage:

```text
extrema fields -> extrema membership/confirmation only
pair fields -> hypothesis membership only
validation fields -> rejection/evidence only
workload fields -> explicit workload outcome only
```

If a field has no measurable owned effect, remove it. If it changes an
unrelated identity or ordering field, stop for contract review.

### Boundary behavior

Every later sensitivity report must identify:

- best behavior at a search boundary;
- sudden candidate-density discontinuities;
- abstention collapse or explosion;
- unstable candidate IDs or order;
- workload cap activation;
- changes caused only by irregular timestamp spacing.

No threshold is selected by this design document.

### Scope comparison

For each semantic field, compare scopes in this order:

```text
global -> timeframe -> asset -> asset-timeframe only when needed
```

The report must contain fold stability, cross-asset consistency,
cross-timeframe consistency, coverage, abstention rate, candidate density,
metric variance, parameter stability, and a complexity description. The most
specific scope is not preferred merely because it improves an in-sample mean.

### Evidence required before activation

Before a value can enter canonical YAML, require all of the following:

```text
causal synthetic tests
irregular timestamp tests
null and malformed-input tests
parameter-effect test
scope comparison
deterministic identity test
bounded workload test
independent orchestrator approval
```

The Phase 5 plan does not define minimum sample counts, quality deltas,
promotion thresholds, latency budgets, or holdout gates. Those remain
unresolved rather than being invented here.

## Handoff constraints

The provisional Phase 6A handoff must not create semantic defaults in Python,
placeholder fields, or YAML values. It must stop before algorithm code if any
selected-provider parameter remains unresolved. All provider-specific evidence
must remain separate from universal candidate evidence.
