# Trendline Family Model — Architecture Plan

Date: 2026-07-11
Status: Draft v2 for architecture approval
Repo: `/Users/aloobhujia/flipperAgent`

Revision v2 locks independent code ownership, typed config resolution, and explicit coverage of the previously agreed mental model.

## 1. Current Mode

Architecture planning.

No runtime source code is changed by this document.

This plan converts the agreed mental model into a modular implementation path without attempting a wholesale rewrite of the existing trendline package.

---

## 2. Executive Decision

Build a new, independently owned **stateful trendline-family model** under the canonical models namespace.

Recommended package:

```text
src/libs/models/trendline_family
```

The new package must not depend at runtime on either:

```text
src/libs/trendlines
src/libs/models/trendlines_old
```

Those packages remain reference and benchmark sources only.

When an existing pivot, fitting, scoring, or utility algorithm is judged useful:

1. copy only the required implementation into the new package,
2. replace old imports and contracts with the new model's contracts,
3. add parity tests against recorded fixtures where useful,
4. treat the copied implementation as newly owned canonical code,
5. do not maintain a runtime bridge back to the old package.

This is code independence, not a ban on reusing ideas. The new model may inherit proven algorithms, but it must own its implementation and evolution.

The phrase **previous/old family state** has a different meaning. Previously generated runtime families are intentionally loaded as persisted data and used as priors during the next bar-close update. That state reuse is central to the model and is unrelated to code reuse from old packages.

The new package owns the complete runtime path:

```text
OHLCV
-> causal pivots
-> exact candidate lines
-> candidate diagnostics
+ previous persisted family state
+ latest confirmed bar evidence
-> family association and lifecycle update
-> exact representative lines
-> interaction zones
-> immutable family snapshot and transitions
-> normalized downstream features
```

The model is therefore both:

- a self-contained line-candidate model, and
- a stateful structural-family tracker.

---

## 3. Locked Mental Model

The following design choices are considered agreed unless later evidence invalidates them.

1. A trendline is an exact straight line.
2. Interaction zones and estimation/projection uncertainty are separate contracts around a line.
3. Previously generated runtime families are active priors for the next bar-close computation.
4. Fresh discovery must remain independent from prior-family continuation.
5. Geometry identity persists while support/resistance role may change.
6. Family updates follow predict -> observe -> associate -> update.
7. Memory has active, dormant, and archived tiers.
8. Family lifecycle includes birth, continuation, strengthening, weakening, dormancy, reactivation, break, role reversal, and expiry.
9. Exact line geometry, structural interpretation, and trading-policy interpretation remain separate layers.
10. Candidate generation and tracking are configured independently.
11. The model must be able to abstain when no stable geometry exists.
12. Every family update is event-sourced and replayable.
13. Single-timeframe tracking must work before MTF composition is implemented.
14. Each timeframe updates only on its own confirmed bar close.
15. MTF output is a unified structural view with provenance, not one averaged synthetic line.
16. Structural importance and current relevance are separate scores.
17. Human annotations are reference/weak supervision, not absolute ground truth.
18. The first version prefers deterministic, auditable rules over complex learned tracking.
19. The new model owns its own code and does not runtime-import old trendline implementations.
20. Hyperparameters are loaded through typed configuration resolution rather than scattered constants.

### 3.1 Included in the implementation plan

The plan explicitly includes:

- exact line contracts,
- interaction-zone contracts,
- persisted prior-family state,
- discovery candidates,
- stable family identity,
- mutable support/resistance role,
- active/dormant/archive memory,
- deterministic association,
- lifecycle transitions,
- abstention semantics,
- immutable snapshots and transition audit,
- bar-close-only structural updates,
- asynchronous future MTF composition,
- config-driven global and asset/timeframe overrides,
- layer-specific optimization and parameter-effect tests.

### 3.2 Designed now but implemented in later phases

The architecture remains capable of supporting, but does not put into the MVP:

- dedicated continuation candidate generation,
- multi-rail/channel families,
- split and merge lineage,
- calibrated line uncertainty,
- full breakout/retest/failed-break event state machine,
- survival and invalidation probabilities,
- horizontal structural zones,
- MTF confluence/conflict graphs,
- directional-change pivots,
- change-point-assisted memory decay,
- human-annotation ranking datasets.

These are part of the roadmap, not forgotten ideas. They are deferred to avoid overcomplicating the first working tracker.

---

## 4. Model Objective

The model should answer four questions on every confirmed bar close.

### 4.1 What exact line hypotheses exist now?

Output exact line geometry with:

- slope,
- reference timestamp and price,
- anchors,
- support/resistance role,
- fitter/provider provenance,
- diagnostics.

### 4.2 Which hypotheses are continuations of previously known structures?

Output stable family IDs and explain:

- matched candidate,
- match score,
- projected price difference,
- normalized slope difference,
- anchor overlap,
- lifecycle transition.

### 4.3 How is price interacting with the active structures?

Output:

- distance from exact line,
- derived interaction-zone bounds,
- touch/approach/penetration evidence,
- current event stage,
- role-change evidence.

### 4.4 Which structures are relevant to downstream consumers?

Output separate scores for:

- structural importance,
- current relevance,
- confidence,
- stability.

Do not reduce all use cases to one universal quality score.

---

## 5. Goals

### 5.1 Initial goals

- Preserve family identity across bar closes.
- Implement a self-owned causal pivot and exact-line candidate pipeline inside the new model.
- Copy/refactor only selected proven algorithms from reference packages when justified; never runtime-import them.
- Keep trendlines exact and renderable.
- Produce a derived volatility-aware interaction zone.
- Support family birth, continuation, strengthening, weakening, dormancy, reactivation, break and expiry.
- Load all operational hyperparameters through typed config resolution.
- Provide deterministic replay.
- Run side-by-side with the existing RegimeV2 trendline adapter.
- Keep the package small enough to understand and test end to end.

### 5.2 Later goals

- Multiple rails in one family.
- Robust split and merge lineage.
- Multi-bar breakout/retest/role-reversal state machine.
- Multiple candidate providers.
- Multi-scale and MTF composition.
- Calibrated uncertainty and survival estimates.
- Horizontal-zone and broader market-geometry integration.

---

## 6. Non-Goals for the First Version

Do not include these in the MVP:

- deep learning,
- computer-vision imitation of annotated charts,
- reinforcement learning,
- conformal calibration,
- order-book requirements,
- automatic horizontal-zone modelling,
- full split/merge graph optimisation,
- simultaneous multi-timeframe fitting,
- tick-by-tick geometry refitting,
- a large named-pattern catalogue,
- deleting or modifying the existing trendline packages during initial shadow development,
- runtime reuse/import of either existing trendline package.

These can be evaluated after the single-timeframe tracker is stable.

---

## 7. Package Ownership

## 7.1 Reference packages

The following packages are reference/baseline implementations only:

```text
src/libs/trendlines
src/libs/models/trendlines_old
```

They may be used for:

- reading algorithms and prior design decisions,
- extracting offline fixtures,
- historical result comparison,
- one-time parity studies,
- identifying failure modes.

They must not be imported by runtime modules under the new package.

A copied algorithm must be relocated, adapted to new contracts, independently tested, and maintained only in the new model.

## 7.2 New canonical package: `libs.models.trendline_family`

Own the complete runtime model:

- OHLCV validation and causal input normalization,
- pivot candidate generation,
- exact line fitting,
- candidate diagnostics,
- canonical timestamp-space line representation,
- family grouping,
- prediction of previous persisted families,
- candidate-to-family association,
- state transitions,
- family ranking,
- interaction-zone derivation,
- state repository interface,
- immutable snapshots,
- transition audit records,
- normalized feature encoding,
- configuration loading and resolution,
- later MTF composition.

## 7.3 Configuration ownership

Configuration source of truth:

```text
configs/trendline_family.yaml
```

The package owns typed schemas, loading, validation, and asset/timeframe resolution. Runtime callers pass asset and timeframe; they do not manually assemble parameter dictionaries.

## 7.4 RegimeV2

RegimeV2 should consume the new package only through a dedicated adapter:

```text
TrendlineFamilyFeatureProducer
```

It must not inspect tracker internals or bypass the config resolver.

---

## 8. Initial Package Shape

Keep the first package flat and small.

```text
src/libs/models/trendline_family/
    __init__.py
    api.py
    contracts.py
    config.py
    config_loader.py
    config_resolver.py
    pivots.py
    fitting.py
    provider.py
    matching.py
    tracker.py
    interactions.py
    repository.py
    features.py
```

Tests:

```text
src/libs/models/trendline_family/tests/
    test_contracts.py
    test_config_loader.py
    test_config_resolver.py
    test_pivots.py
    test_fitting.py
    test_provider.py
    test_matching.py
    test_tracker_lifecycle.py
    test_interactions.py
    test_replay.py
    test_features.py
    test_api.py
```

External configuration:

```text
configs/trendline_family.yaml
```

Later, when complexity is justified, modules may become subpackages:

```text
providers/
tracking/
mtf/
evaluation/
```

Do not create those subpackages during the first skeleton unless a file becomes genuinely crowded.

---

## 9. Core Data Contracts

## 9.1 `LineGeometry`

The exact geometric object.

```python
@dataclass(frozen=True)
class LineGeometry:
    reference_time: datetime
    reference_price: float
    slope_per_second: float

    def value_at(self, timestamp: datetime) -> float:
        elapsed = (timestamp - self.reference_time).total_seconds()
        return self.reference_price + self.slope_per_second * elapsed
```

Why timestamp space:

- a line can be projected across timeframes,
- a 4h line is not reinterpreted as a sequence of 15m bars,
- provenance remains unambiguous,
- MTF composition later becomes straightforward.

Adapters convert existing bar-index lines into this representation using the source dataframe index.

## 9.2 `AnchorRef`

```python
@dataclass(frozen=True)
class AnchorRef:
    anchor_id: str
    timestamp: datetime
    price: float
    pivot_kind: Literal["high", "low", "unknown"]
    confirmation_time: datetime
```

The distinction between `timestamp` and `confirmation_time` is necessary for causal testing.

## 9.3 `LineDiagnostics`

```python
@dataclass(frozen=True)
class LineDiagnostics:
    raw_score: float
    normalized_quality: float
    touch_count: int
    effective_touch_count: int
    coverage: float
    r_squared: float | None
    inlier_ratio: float | None
    residual_scale_atr: float | None
    cut_fraction: float | None
    fitter_consensus: float | None
    anchor_stability: float | None
```

All fields are evidence. None should directly encode a trade decision.

## 9.4 `LineCandidate`

```python
@dataclass(frozen=True)
class LineCandidate:
    candidate_id: str
    asset: str
    timeframe: str
    observed_at: datetime

    geometry: LineGeometry
    anchors: tuple[AnchorRef, ...]
    role: str
    method: str
    provider: str
    diagnostics: LineDiagnostics

    source_line_index: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Roles in the first version:

```text
SUPPORT
RESISTANCE
UNCLASSIFIED
```

Role is mutable at family level. Candidate role is merely the current observation.

## 9.5 `InteractionZone`

This is derived around an exact line.

```python
@dataclass(frozen=True)
class InteractionZone:
    line_id: str
    timestamp: datetime
    center_price: float
    lower_price: float
    upper_price: float
    width_atr: float
    policy_name: str
```

MVP policy:

```text
half_width_price = max(
    minimum_tick_width,
    current_atr * configured_tolerance_atr,
)
```

Do not combine statistical uncertainty with interaction tolerance in the first version.

## 9.6 `UncertaintyMetrics`

Optional in the first version, but define the contract early.

```python
@dataclass(frozen=True)
class UncertaintyMetrics:
    anchor_instability: float | None = None
    fitter_disagreement: float | None = None
    projection_horizon_bars: int = 0
    estimated_width_atr: float | None = None
    method: str = "not_calibrated"
```

It should not be interpreted as an interaction zone.

## 9.7 `FamilyMember`

```python
@dataclass(frozen=True)
class FamilyMember:
    member_id: str
    candidate_id: str
    geometry: LineGeometry
    role: str
    diagnostics: LineDiagnostics
    anchors: tuple[AnchorRef, ...]
    first_seen_at: datetime
    last_seen_at: datetime
```

## 9.8 `TrendlineFamilyState`

Mutable tracker state represented as a serializable dataclass.

```python
@dataclass
class TrendlineFamilyState:
    family_id: str
    asset: str
    timeframe: str

    created_at: datetime
    updated_at: datetime
    last_confirmed_at: datetime
    age_bars: int

    representative: LineGeometry
    representative_member_id: str
    members: list[FamilyMember]

    current_role: str
    lifecycle_state: str

    confidence: float
    structural_importance: float
    current_relevance: float

    touch_count: int
    effective_touch_count: int
    breach_count: int
    bars_since_touch: int
    bars_since_match: int

    uncertainty: UncertaintyMetrics

    parent_family_ids: list[str]
    child_family_ids: list[str]
    version: int
```

The representative remains an exact straight line.

For MVP, choose the representative as a deterministic medoid/highest-ranked actual member rather than synthesizing an averaged line.

## 9.9 `FamilyTransition`

```python
@dataclass(frozen=True)
class FamilyTransition:
    transition_id: str
    family_id: str
    timestamp: datetime
    transition_type: str

    previous_version: int | None
    new_version: int

    matched_candidate_ids: tuple[str, ...]
    association_score: float | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, float]
```

Initial transition types:

```text
BIRTH
CONTINUE
STRENGTHEN
WEAKEN
DORMANT
REACTIVATE
BREAK_CONFIRMED
ROLE_REVERSED
EXPIRE
```

Define `SPLIT` and `MERGE` in the enum only when implementation starts. Do not pretend to support them in MVP.

## 9.10 `TrendlineFamilySnapshot`

Immutable published state for one asset/timeframe/bar close.

```python
@dataclass(frozen=True)
class TrendlineFamilySnapshot:
    snapshot_id: str
    asset: str
    timeframe: str
    timestamp: datetime
    previous_snapshot_id: str | None
    model_version: str
    config_hash: str

    active_families: tuple[TrendlineFamilyState, ...]
    dormant_families: tuple[TrendlineFamilyState, ...]
    transitions: tuple[FamilyTransition, ...]

    diagnostics: Mapping[str, Any]
```

## 9.11 `TrendlineFamilyOutput`

Public API output:

```python
@dataclass(frozen=True)
class TrendlineFamilyOutput:
    snapshot: TrendlineFamilySnapshot
    ranked_support_families: tuple[str, ...]
    ranked_resistance_families: tuple[str, ...]
    nearest_support_family_id: str | None
    nearest_resistance_family_id: str | None
    features: Mapping[str, Any]
```

---

## 10. Candidate Provider Boundary

## 10.1 Provider protocol

```python
class LineCandidateProvider(Protocol):
    def generate(
        self,
        df: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        context: Mapping[str, Any] | None = None,
    ) -> list[LineCandidate]: ...
```

## 10.2 First provider

Implement a self-owned provider:

```text
NativeDeterministicLineProvider
```

It runs only code located inside:

```text
src/libs/models/trendline_family
```

Initial algorithm scope should remain deliberately narrow:

- causal fractal pivot extraction,
- one deterministic exact-line fitter selected during Phase B design,
- support/resistance candidate classification,
- exact anchor provenance,
- method-independent diagnostics.

Recommended first fitter: copy and refactor the proven pathfinding implementation into the new package, then verify expected behavior using fixtures. Add RDP, least-squares, RANSAC, and ensemble only as later provider/fitter plugins rather than copying the whole old package at once.

## 10.3 Strict code-isolation rule

Runtime code must not import:

```text
libs.trendlines
libs.models.trendlines_old
```

This rule applies transitively to pivot, fitting, configuration, boundary, and signal utilities.

Historical code/results may be used only to:

- understand an algorithm,
- create frozen comparison fixtures,
- compare outputs offline,
- document provenance.

Copied code must be rewritten against new contracts and cannot retain old package imports.

## 10.4 Future providers

The protocol later allows:

- directional-change candidate provider,
- change-point-window candidate provider,
- horizontal-zone provider in a broader geometry package,
- learned candidate provider.

They must emit canonical contracts rather than modify the tracker.

---

## 11. Two Candidate Streams

The tracker should receive two logical streams.

## 11.1 Discovery candidates

Generated independently from current OHLCV.

Purpose:

- detect new geometry,
- recover after regime shifts,
- avoid anchoring all inference to old families.

In MVP, this is the ordinary full call to `NativeDeterministicLineProvider`.

## 11.2 Continuation candidates

Generated with prior-family context.

Purpose:

- preserve anchors,
- refit around existing geometry,
- reduce unnecessary redraw/churn.

MVP simplification:

Do not create a separate continuation fitter immediately.

Instead:

1. generate discovery candidates,
2. associate them with projected previous families,
3. preserve matched family identity.

Add a dedicated continuation provider only after observing that discovery candidate recall is insufficient.

This is an intentional simplification.

---

## 12. Candidate Grouping into Observation Families

The provider may return several nearly parallel lines.

Before matching against old families, group current candidates into small observation families.

MVP deterministic grouping criteria:

- same asset and timeframe,
- compatible role,
- normalized slope difference below a threshold,
- projected price difference at current timestamp below an ATR threshold.

Use deterministic union-find or ordered agglomeration.

Do not add DBSCAN or probabilistic clustering in MVP.

Singleton families are valid.

Each group selects a representative member using a ranking policy.

---

## 13. Prediction of Existing Families

Before association, project each active and eligible dormant family to the new bar timestamp.

Prediction step:

```text
new projected center = representative.value_at(new_timestamp)
confidence = confidence * decay_factor
projection horizon increases
uncertainty may increase
```

MVP should not alter slope during prediction.

The prediction is a temporary comparison object. State changes only after update decisions.

---

## 14. Association and Matching

## 14.1 Required comparison dimensions

Candidate/family association should use:

1. projected price distance in ATR,
2. normalized slope difference,
3. anchor overlap,
4. role compatibility,
5. temporal recency,
6. optional method/provider agreement.

## 14.2 Normalized measures

Projected distance:

```text
abs(candidate_price - family_price) / current_atr
```

Slope comparison should use a timeframe-normalized representation:

```text
slope_atr_per_hour
```

or equivalent canonical clock-time normalization.

Do not compare raw price-per-bar slopes across different timeframes.

## 14.3 Initial match score

A simple deterministic score is sufficient:

```text
score =
    0.45 * projected_level_similarity
  + 0.30 * normalized_slope_similarity
  + 0.15 * anchor_similarity
  + 0.10 * role_compatibility
```

Exact weights are initial defaults, not optimized truth.

## 14.4 Hard gates

Reject a match when any required condition fails:

- projected distance exceeds maximum ATR threshold,
- slope difference exceeds maximum threshold,
- timestamps are invalid,
- roles are strongly incompatible without a break/role-reversal event.

## 14.5 Assignment algorithm

MVP:

- compute all eligible scores,
- sort descending,
- greedily assign one observation family to one previous family,
- preserve deterministic tie-breaking.

Later:

- evaluate Hungarian assignment only when ambiguous many-to-many matching is shown to be a real issue.

---

## 15. Family Update Rules

## 15.1 Matched family

For an accepted match:

- preserve `family_id`,
- append/update member evidence,
- choose a new representative deterministically,
- increment age and version,
- reset `bars_since_match`,
- update quality/confidence,
- update role only through explicit interaction/event rules,
- emit `CONTINUE`, `STRENGTHEN` or `WEAKEN`.

## 15.2 Unmatched candidate group

Create a new family when:

- candidate quality exceeds birth threshold,
- minimum anchor/touch requirements pass,
- it is not a duplicate of another new group.

Emit `BIRTH`.

## 15.3 Unmatched active family

- increment `bars_since_match`,
- decay confidence,
- remain active for a configured grace period,
- then become `DORMANT`.

Do not immediately delete it.

## 15.4 Dormant family

A dormant family may reactivate when a high-scoring new candidate matches it.

Emit `REACTIVATE`.

## 15.5 Expiry

Expire only when:

- dormant duration exceeds threshold,
- confidence falls below threshold,
- projection horizon becomes unreasonable,
- or a confirmed structural invalidation policy applies.

Expired states remain in transition/audit history.

---

## 16. Representative-Line Policy

The family representative must remain an exact line.

MVP policy:

1. filter eligible active members,
2. calculate structural ranking score,
3. choose the highest-scoring actual member,
4. break ties by stability, recency and deterministic ID.

Do not average slopes/intercepts in the first implementation.

Later research can compare:

- robust medoid,
- weighted-median slope and level,
- state-space estimate,
- family centreline plus rails.

---

## 17. Family Ranking

Keep scores separate.

## 17.1 Structural importance

Initial components:

- normalized quality,
- effective touches,
- coverage,
- family age,
- persistence,
- anchor stability.

## 17.2 Current relevance

Initial components:

- distance to current price,
- current lifecycle state,
- active interaction event,
- projection horizon,
- role compatibility.

## 17.3 Confidence

Confidence measures evidence that the family remains coherent.

It should not be interpreted as a trade win probability.

## 17.4 Named selectors

Expose explicit selectors instead of only `best_support`:

```text
nearest_reliable_support
nearest_reliable_resistance
most_important_support
most_important_resistance
dominant_family
```

---

## 18. Interaction-Zone Policy

## 18.1 Exact line remains canonical

For a family at timestamp `t`:

```text
center = representative.value_at(t)
```

## 18.2 Derived zone

MVP:

```text
half_width = max(
    tick_size * minimum_ticks,
    ATR(t) * interaction_tolerance_atr,
)
```

Output:

```text
lower = center - half_width
upper = center + half_width
```

## 18.3 Keep meanings separate

Do not merge:

- interaction tolerance,
- model-estimation uncertainty,
- family corridor width.

They may all be rendered as shaded areas later, but their contracts and features remain separate.

---

## 19. Initial Interaction Classification

The first implementation should remain modest.

Per family/bar classify:

```text
FAR
APPROACHING
IN_ZONE
WICK_BREACH
BODY_BREACH
CLOSE_BEYOND
```

Capture raw metrics:

- line distance ATR,
- wick penetration ATR,
- body penetration ATR,
- close penetration ATR,
- candle direction,
- close location inside candle.

Do not implement full retest/failed-break/role-reversal sequencing until the tracker and snapshots are stable.

Compatibility labels may still map to:

```text
GEOMETRIC_BOUNCE_SUPPORT
GEOMETRIC_BOUNCE_RESISTANCE
STRUCTURAL_BREAKOUT
STRUCTURAL_BREAKDOWN
NONE
```

but those should be derived outputs, not the internal state model.

---

## 20. Bar-Close and Tick Behaviour

## 20.1 Bar close

Canonical geometry update occurs only on confirmed bar close.

```text
confirmed bar
-> candidate generation
-> family prediction
-> matching
-> lifecycle update
-> interaction classification
-> immutable snapshot
```

## 20.2 Tick path

Do not refit geometry on every tick in MVP.

Optional tick API may:

- project active lines to current timestamp,
- compute provisional distance/zone interaction,
- emit non-persistent provisional observations.

Persistent lifecycle changes remain bar-close owned.

---

## 21. Repository and State Ownership

Define a small repository protocol.

```python
class TrendlineFamilyRepository(Protocol):
    def latest_snapshot(self, asset: str, timeframe: str) -> TrendlineFamilySnapshot | None: ...
    def save_snapshot(self, snapshot: TrendlineFamilySnapshot) -> None: ...
```

First implementation:

```text
InMemoryTrendlineFamilyRepository
```

Next implementation:

```text
JsonlTrendlineFamilyRepository
```

or the repo's established artifact/event store.

Tracker logic must not depend on a database implementation.

---

## 22. Deterministic Identity

## 22.1 Candidate ID

Derived from:

- asset,
- timeframe,
- observed timestamp,
- provider,
- method,
- anchor IDs,
- normalized geometry fingerprint.

## 22.2 Family ID

Created once at birth from:

- asset,
- timeframe,
- birth timestamp,
- representative candidate fingerprint.

Family ID never changes during ordinary continuation or role change.

## 22.3 Snapshot and transition IDs

Use deterministic hashes or UUID5 over canonical serialized inputs.

Deterministic IDs are required for replay parity tests.

---

## 23. Public API

Recommended initial API:

```python
def update_trendline_families(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    repository: TrendlineFamilyRepository,
    config: ResolvedTrendlineFamilyConfig | None = None,
    config_path: str | Path = "configs/trendline_family.yaml",
    runtime_override: Mapping[str, Any] | None = None,
    provider: LineCandidateProvider | None = None,
) -> TrendlineFamilyOutput:
    ...
```

Read-only projection API:

```python
def project_trendline_families(
    snapshot: TrendlineFamilySnapshot,
    *,
    timestamp: datetime,
    current_price: float,
    current_atr: float,
) -> ProjectedFamilyView:
    ...
```

The update API should:

- load and resolve configuration for `(asset, timeframe)` when a resolved config is not injected,
- reject unresolved/raw parameter mappings inside runtime stages,
- fetch previous snapshot,
- perform one deterministic bar-close update,
- attach the config hash and model version,
- save new snapshot,
- return output.

---

## 24. Configuration Architecture

All runtime hyperparameters must enter through a typed loader and resolver.

Source of truth:

```text
configs/trendline_family.yaml
```

Runtime modules must not read YAML directly. They receive one fully resolved immutable config object.

## 24.1 Resolution precedence

Use deterministic precedence:

```text
schema fallback defaults
  < YAML global defaults
  < generic timeframe overrides
  < asset-wide overrides
  < asset + timeframe overrides
  < explicit runtime/research override
```

The resolved object must record the source of every overridden field for auditability.

## 24.2 Configuration layers

### Global defaults

Use for broadly portable behavior:

- enabled provider/fitter names,
- match-score weights,
- lifecycle policy shape,
- minimum numerical safeguards,
- maximum family counts,
- abstention rules,
- serialization/model version.

### Timeframe overrides

Use for bar-count and horizon-sensitive behavior:

- pivot windows,
- candidate lookback bars,
- active grace bars,
- dormancy/expiry bars,
- event confirmation bars,
- projection horizon,
- ATR window.

### Asset-wide overrides

Use only when an asset has persistent characteristics not captured by ATR normalization:

- minimum history,
- candidate quality floor,
- provider enablement,
- liquidity/data-quality restrictions,
- special lifecycle caps.

Tick size and exchange precision should preferably come from market metadata rather than manually duplicated YAML.

### Asset-timeframe overrides

Use for validated optimized values such as:

- candidate lookback,
- pivot scale,
- maximum match distance in ATR,
- normalized slope gate,
- birth threshold,
- interaction tolerance,
- approaching distance,
- dormancy and expiry horizon,
- role-change confirmation.

These values require OOS validation and promotion metadata before becoming production defaults.

## 24.3 Typed config groups

Avoid one giant flat dataclass. Use a small root object containing stage-owned groups:

```python
@dataclass(frozen=True)
class CandidateConfig:
    pivot_provider: str = "fractal"
    fitter: str = "pathfinding"
    lookback_bars: int = 240
    min_bars: int = 40
    min_candidate_quality: float = 0.35
    birth_quality_threshold: float = 0.45


@dataclass(frozen=True)
class MatchingConfig:
    max_distance_atr: float = 0.75
    max_slope_delta_atr_per_hour: float = 0.10
    minimum_match_score: float = 0.60
    level_weight: float = 0.45
    slope_weight: float = 0.30
    anchor_weight: float = 0.15
    role_weight: float = 0.10


@dataclass(frozen=True)
class LifecycleConfig:
    active_grace_bars: int = 3
    dormant_after_bars: int = 6
    expire_after_bars: int = 50
    confidence_decay_per_unmatched_bar: float = 0.05
    reactivation_min_score: float = 0.70
    max_active_families_per_role: int = 8


@dataclass(frozen=True)
class InteractionConfig:
    atr_window: int = 14
    tolerance_atr: float = 0.25
    approaching_distance_atr: float = 0.75
    close_confirmation_bars: int = 1


@dataclass(frozen=True)
class TrendlineFamilyConfig:
    model_version: str
    candidate: CandidateConfig
    matching: MatchingConfig
    lifecycle: LifecycleConfig
    interaction: InteractionConfig
```

The exact field list may evolve during coder handoff, but ownership by stage is mandatory.

## 24.4 YAML shape

```yaml
version: 1

model:
  enabled: true
  model_version: trendline_family_v1

defaults:
  candidate:
    pivot_provider: fractal
    fitter: pathfinding
    lookback_bars: 240
    min_bars: 40
    min_candidate_quality: 0.35
    birth_quality_threshold: 0.45
  matching:
    max_distance_atr: 0.75
    max_slope_delta_atr_per_hour: 0.10
    minimum_match_score: 0.60
    level_weight: 0.45
    slope_weight: 0.30
    anchor_weight: 0.15
    role_weight: 0.10
  lifecycle:
    active_grace_bars: 3
    dormant_after_bars: 6
    expire_after_bars: 50
    confidence_decay_per_unmatched_bar: 0.05
    reactivation_min_score: 0.70
    max_active_families_per_role: 8
  interaction:
    atr_window: 14
    tolerance_atr: 0.25
    approaching_distance_atr: 0.75
    close_confirmation_bars: 1

timeframes:
  15m:
    candidate:
      lookback_bars: 320
    lifecycle:
      expire_after_bars: 96
  4h:
    candidate:
      lookback_bars: 180
    lifecycle:
      expire_after_bars: 60

assets:
  BTCUSDT:
    defaults:
      candidate:
        birth_quality_threshold: 0.50
    timeframes:
      4h:
        matching:
          max_distance_atr: 0.65
        interaction:
          tolerance_atr: 0.22
```

## 24.5 Required config components

```text
config.py
    typed immutable schemas and validation

config_loader.py
    read YAML once and normalize raw mappings

config_resolver.py
    resolve(asset, timeframe, runtime_override) -> ResolvedTrendlineFamilyConfig
```

The resolved config should include:

```text
asset
timeframe
config version
model version
resolved stage configs
field provenance
stable config hash
```

The config hash must be stored in every family snapshot and transition record.

## 24.6 Validation rules

At minimum:

- all weights are non-negative and sum to one,
- distance/tolerance thresholds are non-negative,
- lifecycle horizons are ordered,
- `min_bars <= lookback_bars`,
- enabled providers and fitters exist in registries,
- unknown YAML keys fail closed,
- malformed asset/timeframe overrides fail at startup,
- optimization cannot write directly into production defaults.

## 24.7 Optimization and promotion

Optimized values should first be written to a review artifact or optimized-parameter file with:

- asset,
- timeframe,
- study ID,
- data range,
- objective owner,
- OOS metrics,
- approval status,
- config hash.

Only an explicit promotion step should merge them into `configs/trendline_family.yaml`.

Keep the initial YAML surface compact. A field is added only when its owning stage and parameter-effect test are clear.

---

## 25. Feature Surface for the First Version

Expose a compact set.

### 25.1 State health

```text
trendline_family_valid
trendline_family_count_active
trendline_family_count_dormant
trendline_family_births
trendline_family_updates
trendline_family_dormancies
trendline_family_reactivations
trendline_family_expiries
trendline_family_churn
```

### 25.2 Nearest structures

```text
nearest_support_family_id
nearest_resistance_family_id
distance_to_support_line_atr
distance_to_resistance_line_atr
distance_to_support_zone_atr
distance_to_resistance_zone_atr
```

### 25.3 Family evidence

```text
support_family_age_bars
resistance_family_age_bars
support_family_confidence
resistance_family_confidence
support_structural_importance
resistance_structural_importance
support_current_relevance
resistance_current_relevance
support_effective_touch_count
resistance_effective_touch_count
support_bars_since_match
resistance_bars_since_match
```

### 25.4 Interaction evidence

```text
support_interaction_state
resistance_interaction_state
support_wick_penetration_atr
resistance_wick_penetration_atr
support_body_penetration_atr
resistance_body_penetration_atr
support_close_penetration_atr
resistance_close_penetration_atr
```

### 25.5 Ambiguity

```text
top_support_score_gap
top_resistance_score_gap
family_hypothesis_count
family_abstention_reason
```

Do not immediately duplicate the full existing RegimeV2 trendline feature surface.

---

## 26. RegimeV2 Integration Plan

## 26.1 Shadow-only adapter

Add later:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
```

It should run beside the current:

```text
trendline_feature_producer.py
```

## 26.2 No immediate replacement

For initial experiments:

```text
existing trendline features
new family features
```

are both collected.

Do not feed family features into promotion-sensitive paths until:

- replay is deterministic,
- feature availability is sufficient,
- churn is controlled,
- OOS ablation is complete.

## 26.3 Promotion path

1. collect shadow logs,
2. compare coverage and failure rate,
3. compare structural stability,
4. run RegimeV2 feature ablation,
5. promote individual groups,
6. deprecate duplicate old features only after evidence.

---

## 27. MTF Architecture — Deferred but Contract-Aware

Single-timeframe state must be stable first.

Later each timeframe owns an asynchronous tracker:

```text
15m tracker updates on 15m close
1h tracker updates on 1h close
4h tracker updates on 4h close
1d tracker updates on 1d close
```

The MTF compositor consumes latest confirmed snapshots.

Recommended later file:

```text
src/libs/models/trendline_family/mtf.py
```

MTF flow:

```text
latest confirmed snapshots
-> project exact representative lines to common timestamp
-> preserve source timeframe and family IDs
-> cluster compatible projected structures
-> calculate agreement, conflict and confluence
-> produce one unified MTF view
```

The unified view is not one averaged line.

It contains:

- dominant local family,
- dominant swing family,
- dominant macro family,
- nearest projected support structures,
- nearest projected resistance structures,
- cross-timeframe agreement,
- conflict,
- confluence regions.

---

## 28. Evaluation Principles

The model must be evaluated as a structural tracker, not only as a line fitter.

## 28.1 Candidate recall

Does the provider generate plausible lines that can explain known structure?

## 28.2 Identity stability

- family ID persistence,
- redraw/churn rate,
- unnecessary birth rate,
- unnecessary dormancy rate,
- reactivation correctness.

## 28.3 Geometry accuracy

- projected line distance to future validated touches,
- penetration rate,
- survival duration,
- reaction magnitude after interaction.

## 28.4 Association quality

- matched-family continuity,
- incorrect identity switches,
- missed continuation,
- false continuation across regime changes.

## 28.5 Interaction usefulness

- touch outcome by zone distance,
- wick/body/close breach outcomes,
- break confirmation precision,
- abstention quality.

## 28.6 Downstream utility

RegimeV2 and strategy evaluation occurs only after structural metrics are acceptable.

---

## 29. Optimizer Boundaries

Do not repeat the current optimizer mismatch.

### Candidate-generation optimizer

Owns:

- extractor parameters,
- fitter parameters,
- lookback,
- candidate deduplication.

Scores:

- forward line longevity,
- touch quality,
- penetration,
- candidate recall,
- computation cost.

### Family-tracking optimizer

Owns:

- match gates,
- match weights,
- lifecycle grace/decay,
- birth thresholds.

Scores:

- ID stability,
- churn,
- continuation accuracy,
- future structural utility.

### Interaction optimizer

Owns:

- zone width,
- approach thresholds,
- break confirmation.

Scores:

- event precision/recall,
- calibration,
- detection delay.

No optimizer may search a parameter that cannot change its evaluated stage.

---

## 30. Test Plan

## 30.1 Contract tests

- timestamp projection,
- serialization,
- deterministic IDs,
- role mutation without identity mutation,
- exact-line invariants.

## 30.2 Configuration and import-boundary tests

- global default resolution,
- timeframe override resolution,
- asset override resolution,
- asset-timeframe override precedence,
- explicit runtime override precedence,
- config hash stability,
- unknown keys fail closed,
- invalid lifecycle ordering fails validation,
- new runtime package contains no imports from either old trendline package.

## 30.3 Provider tests

- causal pivot confirmation,
- deterministic candidate generation,
- support/resistance role mapping,
- anchor timestamp mapping,
- diagnostics preservation,
- empty/invalid/abstention handling,
- optional frozen parity fixtures for copied algorithms.

## 30.4 Matching tests

- small level/slope change preserves family,
- large level change rejects match,
- incompatible roles reject unless event permits,
- deterministic tie resolution,
- dormant family can reactivate.

## 30.5 Lifecycle tests

- birth,
- continuation,
- strengthen/weaken,
- grace period,
- dormancy,
- reactivation,
- expiry.

## 30.6 Interaction tests

- far,
- approaching,
- in zone,
- wick breach,
- body breach,
- close beyond,
- support and resistance symmetry.

## 30.7 Causality tests

- unconfirmed pivot cannot become an anchor,
- only confirmed bar triggers state update,
- higher-timeframe snapshot cannot use incomplete bar,
- current snapshot is excluded from previous history.

## 30.8 Replay tests

Given the same:

- input bars,
- config,
- provider output,
- previous snapshot,

produce identical:

- IDs,
- transitions,
- family state,
- rankings,
- features.

## 30.9 Parameter-effect tests

For each configurable parameter, demonstrate a controlled input where changing the parameter changes its owned stage.

---

## 31. Implementation Phases

## Phase A — Foundation, contracts, and config

Scope:

- create the new canonical package skeleton under `src/libs/models/trendline_family`,
- implement exact timestamp-space line geometry,
- implement contracts and serialization,
- implement typed config schemas,
- implement YAML loader and global/asset/timeframe resolver,
- implement config hashing and field provenance,
- implement in-memory repository.

No candidate generation or tracking yet.

Exit gate:

- contract tests pass,
- deterministic IDs pass,
- exact-line projection tests pass,
- config precedence tests pass,
- unknown config keys fail closed,
- snapshots can carry config/model version metadata.

## Phase B — Native candidate model

Scope:

- implement causal fractal pivot extraction inside the new package,
- copy/refactor one selected deterministic fitter into the new package,
- emit canonical `LineCandidate` objects directly,
- map anchors and method-independent diagnostics,
- add provider protocol and registry,
- add empty/invalid/abstention semantics,
- create frozen parity fixtures where old behavior is worth comparing.

Exit gate:

- same OHLCV and resolved config produce a deterministic candidate set,
- no runtime imports from either old trendline package,
- support/resistance roles and timestamps are correct,
- provider/fitter config selection works,
- copied algorithm is fully owned and tested in the new package.

## Phase C — Single-timeframe family tracker MVP

Scope:

- prediction,
- deterministic grouping,
- greedy association,
- birth/continue/weaken/dormant/reactivate/expire,
- representative selection,
- snapshot/transition output.

Exit gate:

- stable IDs across synthetic rolling windows,
- deterministic replay,
- controlled churn,
- no future data use.

## Phase D — Interaction zones and basic event evidence

Scope:

- ATR-derived zones,
- far/approach/in-zone/wick/body/close states,
- distance and penetration features,
- compatibility interaction labels.

Exit gate:

- support/resistance symmetry tests,
- event evidence is auditable,
- zone width parameter-effect test passes.

## Phase E — Shadow RegimeV2 integration

Scope:

- add family feature producer,
- persist snapshot history in shadow runs,
- emit coverage/churn/transition diagnostics,
- do not change active decision policy.

Exit gate:

- no runtime regression,
- sufficient feature availability,
- replay/live parity,
- shadow artifact inspection complete.

## Phase F — Full interaction lifecycle

Scope:

- break pending/confirmed,
- retest pending/success/failure,
- role reversal,
- pressure duration,
- event IDs.

Exit gate:

- event state-machine replay passes,
- role reversal preserves family identity,
- event labels have forward outcome definitions.

## Phase G — Multi-rail families

Scope:

- explicit rail offsets,
- family corridor,
- channel-family semantics,
- robust representative/medoid comparison.

Exit gate:

- repeated parallel structures group correctly,
- unrelated lines do not over-merge,
- corridor is distinct from interaction zone.

## Phase H — MTF composition

Scope:

- asynchronous per-timeframe snapshots,
- timestamp projection,
- MTF agreement/conflict/confluence,
- unified execution-timeframe view.

Exit gate:

- no incomplete-HTF leakage,
- source provenance preserved,
- MTF composition improves OOS utility or stability.

## Phase I — Optimization and promotion

Scope:

- split stage-specific optimizers,
- structural tracker benchmarks,
- RegimeV2 ablation,
- promotion decision.

Exit gate:

- every parameter affects its objective,
- gains survive untouched OOS data,
- operational churn and latency are acceptable.

---

## 32. First Implementation Slice

The recommended first coding slice is **Phase A only**. Phase B follows after the contracts and config hierarchy are reviewed.

Create:

```text
src/libs/models/trendline_family/__init__.py
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_loader.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/repository.py
configs/trendline_family.yaml
```

Tests:

```text
src/libs/models/trendline_family/tests/test_contracts.py
src/libs/models/trendline_family/tests/test_config_loader.py
src/libs/models/trendline_family/tests/test_config_resolver.py
src/libs/models/trendline_family/tests/test_repository.py
```

Do not copy candidate-generation code or implement tracking in the same initial change.

Reason:

- contracts and candidate normalization determine all later state semantics,
- timestamp-space conversion must be correct before association,
- a small first slice is easier to review and roll back.

---

## 33. Compatibility and Migration

- Existing trendline packages remain unchanged during initial phases.
- Existing RegimeV2 adapter remains active.
- The new package is opt-in and self-contained.
- No runtime import bridge is introduced from the new package to old trendline code.
- New snapshots use independent contracts and config hashes.
- A compatibility encoder may later map family output to selected existing feature names.
- Do not delete old feature paths until shadow/OOS promotion is complete.

Both existing trendline trees remain outside the new runtime architecture and are handled as reference/baseline implementations.

---

## 34. Main Risks

### Excessive hysteresis

Old families may survive too long.

Mitigation:

- independent discovery,
- confidence decay,
- hard association gates,
- dormancy/expiry,
- regime-transition adviser later.

### Excessive churn

Small candidate changes may create new IDs.

Mitigation:

- timestamp-space matching,
- ATR-normalized level distance,
- grace period,
- stable deterministic representative selection.

### Over-merging

Several distinct lines may be grouped as one family.

Mitigation:

- conservative slope and level gates,
- singleton families allowed,
- multi-rail logic deferred until evidence.

### Semantic leakage

Trading policy could contaminate geometry.

Mitigation:

- raw evidence, structure and policy remain separate,
- tracker confidence is not trade probability.

### MTF leakage

Incomplete higher-timeframe bars may leak.

Mitigation:

- MTF deferred,
- per-timeframe confirmed snapshots,
- timestamp availability tests.

### State-store inconsistency

Concurrent updates may fork snapshots.

Mitigation:

- first version single-writer,
- previous snapshot ID check,
- deterministic versioning,
- repository compare-and-save later if needed.

---

## 35. Approval Decisions Required Before Coding

Recommended defaults are supplied so planning is not blocked.

1. Package name:
   - recommended: `libs.models.trendline_family`
2. Existing trendline code role:
   - recommended: offline reference/fixture source only; no runtime imports
3. Copied algorithm policy:
   - recommended: copy only selected algorithms, refactor to new contracts, own them in the new package
4. Config source:
   - recommended: `configs/trendline_family.yaml` with typed resolution
5. Config precedence:
   - recommended: global -> timeframe -> asset -> asset/timeframe -> explicit runtime override
6. Representative line:
   - recommended: actual highest-ranked/medoid member, not average
7. State update frequency:
   - recommended: confirmed bar close only
8. First repository:
   - recommended: in-memory plus deterministic serialization
9. Initial candidate source:
   - recommended: self-owned fractal pivots plus copied/refactored pathfinding fitter
10. Initial MTF scope:
   - recommended: deferred until single-TF tracker passes replay
11. Initial coding scope:
   - recommended: Phase A only

---

## 36. Recommended Next Handoff

Coder-ready handoff for **Phase A — Foundation and contracts**.

It should specify:

- exact files,
- complete dataclass fields,
- enum values,
- serialization conventions,
- deterministic ID algorithm,
- timestamp/UTC rules,
- unit tests,
- no integration changes.

After Phase A review and approval, prepare a separate coder handoff for Phase B native pivot/candidate implementation.
