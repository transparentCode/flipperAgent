# Trendline V2 Extrema Pair Contract V1

Status: `PHASE_6A_READY_FOR_REVIEW`

Authorization boundary:

```text
PHASE_6A_PROVIDER_CONTRACTS_AUTHORIZED
PHASE_6B_PROVIDER_IMPLEMENTATION_NOT_AUTHORIZED
```

## Provider identity

```text
provider_name: confirmed_extrema_pair
provider_version: v1
provider_identity: trendline_v2.confirmed_extrema_pair.v1
evidence_schema: v1
```

Provider-specific configuration is immutable, typed, and supplied directly in
`ProviderRequest`. It is not read from YAML, environment variables, globals, or
constructor state.

## Provider configuration

`ConfirmedExtremaPairConfig` has no Python defaults. Every field is required in
fixtures and future provider requests:

| Field | Owner | Type/units | Classification | YAML | Hash | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `provider_name` | identity | string | INVARIANT | no | yes | exact `confirmed_extrema_pair` |
| `provider_version` | identity | string | INVARIANT | no | yes | exact `v1` |
| `plateau_policy` | extrema | enum | INVARIANT | no | yes | `leftmost_strict_left_nonstrict_right_v1` |
| `history_horizon` | input horizon | enum | UNRESOLVED | no | yes | duration mode selected; scope unresolved |
| `lookback_duration_seconds` | input horizon | positive float seconds | UNRESOLVED | no | yes | explicit fixture value only |
| `left_confirmation_bars` | extrema | positive integer bars | UNRESOLVED | no | yes | scope unresolved |
| `right_confirmation_bars` | extrema | positive integer bars | UNRESOLVED | no | yes | causal delay; scope unresolved |
| `min_extrema_per_role` | hypothesis | integer count >= 2 | UNRESOLVED | no | yes | scope unresolved |
| `body_validation_policy` | structural validation | enum | INVARIANT | no | yes | exact-side policy |
| `pair_enumeration_order` | hypothesis | enum | INVARIANT | no | yes | chronological v1 |
| `candidate_order_version` | ordering | version string | INVARIANT | no | yes | explicit version |
| `structural_validation_version` | validation | version string | INVARIANT | no | yes | explicit version |
| `max_hypotheses` | workload | integer count >= 1 | UNRESOLVED | no | yes | semantic, never truncate |
| `max_output_candidates` | workload | integer count >= 1 | UNRESOLVED | no | yes | semantic, never truncate |
| `provider_evidence_schema_version` | evidence | version string | INVARIANT | no | yes | typed evidence version |

`body_clearance_tolerance` is intentionally absent. No raw-price, basis-point,
ATR, epsilon, or hidden numerical tolerance is authorized.

## History horizon

Alternatives reviewed:

| Alternative | Causal meaning | Irregular timestamps | Timeframe sensitivity | Extrema density/pair count | Candidate identity | Scope/classification | Required effect test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lookback_bars` | latest N supplied bars | bar count ignores elapsed gaps | high | changes with bar duration; bounded by N | horizon must be hashed | deferred, UNRESOLVED | vary N; compare density and prefix identity |
| `lookback_duration_seconds` | rows within physical elapsed duration | preserves elapsed-time meaning | explicit duration still needs scope study | density varies with observed bar availability; bounded by duration | duration must be hashed | selected mode, value UNRESOLVED | vary duration; compare density, pairs, IDs |
| full supplied causal prefix | all rows through cutoff | preserves supplied timestamps | history grows with asset/timeframe | unbounded extrema/pair work | input identity changes with prefix | rejected for v1 | append history; prove workload bound |

`lookback_duration_seconds_v1` is selected as the only v1 horizon mode. Its
numeric value remains fixture/request-only until scope evidence exists.

Duration value and scope remain unresolved. They cannot enter canonical YAML
until global, timeframe, asset, and asset-timeframe evidence is reviewed in
that order.

## Body validation

Alternatives reviewed:

| Alternative | Units | Monotonic effect | Cross-asset/timeframe | Required input | Numerical risk | Scope | Candidate membership | Quality interaction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact side with precision guard only | candle price representation | stricter than any positive tolerance | comparable because no scale is introduced | OHLC bodies and emitted geometry | exact floating comparison must be versioned | invariant | rejects only strict side crossings | does not add quality |
| raw-price tolerance | raw price units | larger value admits more lines | not comparable across assets | OHLC and tolerance | scale-dependent | unresolved | changes membership | changes later density |
| basis-point tolerance | relative price units | larger value admits more lines | more comparable across assets | OHLC, anchor/reference price | reference selection affects result | unresolved | changes membership | changes later density |
| ATR-normalized tolerance | ATR price units | larger value admits more lines | requires causal ATR policy | OHLC, ATR history | ATR window/availability | unresolved | changes membership | couples provider to volatility feature |
| evidence-only recording | no rejection units | no membership effect | comparable | OHLC only for evidence | cannot enforce structure | rejected for v1 | admits invalid lines | shifts burden to later policy |

Selected contract: `exact_side_v1`.

- support line crossing strictly above body floor is invalid;
- resistance line crossing strictly below body ceiling is invalid;
- equality is valid;
- validation uses emitted timestamp-space geometry;
- no tolerance field exists in provider v1.

This policy is invariant. Any tolerance-based policy requires a new contract,
units, identity version, and parameter-effect evidence.

## Field provenance and effect tests

Every provider field is required in an explicit request and participates in
provider configuration identity. Values originate from the typed fixture or
future provider resolver, never from Python defaults or canonical YAML.

| Field group | Value source | Owned effect test |
| --- | --- | --- |
| identity/version/policy version fields | approved provider contract | changed version changes provider contract identity and serialization |
| history horizon and duration | explicit fixture/request; scope unresolved | change only causal input window, density, pair count, and request identity |
| confirmation bars | explicit fixture/request; scope unresolved | change only extrema confirmation/membership and evidence positions |
| minimum extrema count | explicit fixture/request; scope unresolved | change only insufficient-input/hypothesis eligibility |
| body validation policy | approved invariant enum | unsupported policy fails; selected policy changes no unrelated identity |
| pair enumeration order | approved invariant enum | traversal changes cannot alter canonical final ordering |
| workload limits | explicit fixture/request; scope unresolved | changing either changes only semantic workload result/identity; no silent truncation |
| evidence schema version | approved typed evidence contract | version changes provider contract identity and rejects incompatible evidence |

## Request binding

`ProviderRequest` contains:

```text
input_data: ProviderInput
config: ResolvedTrendlineV2Config
provider_config: ProviderConfig
```

Combined config identity hashes foundation config identity and provider config
identity. Request identity hashes actual input identity and combined config
identity. Callers cannot supply input identity independently. Untyped mappings
are rejected.

## Provider evidence

`CandidateEvidence` remains unchanged and provider-neutral:

```text
anchor_count
distinct_anchor_timestamps
anchor_span_seconds
```

`ConfirmedExtremaPairEvidence` is a separate immutable record:

| Field | Type/units | Validation |
| --- | --- | --- |
| `candidate_id` | lowercase SHA-256 | canonical candidate association |
| `extrema_kind` | `high` or `low` | closed enum |
| `anchor_source_positions` | ordered pair of non-negative bar positions | exactly two, unique |
| `confirmation_positions` | ordered pair of non-negative bar positions | exactly two, after source positions |
| `validated_intermediate_count` | integer count | non-negative |
| `body_violation_count` | integer count | non-negative; valid candidate path records zero |
| `coordinate_system_version` | version string | exact elapsed UTC seconds v1 |
| `plateau_policy_version` | version string | exact selected plateau policy |
| `schema_version` | version string | exact evidence v1 |

Evidence validates source and confirmation positions against actual
`ProviderInput`; out-of-range or future positions fail. Serialization is
canonical, immutable, and content-addressed. Evidence schema participates in
provider contract identity.

No free-form metadata is allowed.

## Determinism and workload

Pair enumeration order and candidate order are versioned invariants. Output
affecting workload limits are semantic config fields and participate in hashes.
No silent truncation is allowed. An operational emergency limit, if added
later, must fail execution rather than return a semantically different valid
result.

## Forbidden Phase 6A behavior

No extrema scanner, pair construction, candidate generation, provider class,
registry, kernel, Numba, canonical YAML provider value, viewer source, or
runtime integration belongs in this phase.
