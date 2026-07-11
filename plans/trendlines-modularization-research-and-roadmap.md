# Trendlines Model — Deep Research, Modularization, Feature Gap, and Pipeline Roadmap

Date: 2026-07-11
Repo: `/Users/aloobhujia/flipperAgent`
Canonical source: `src/libs/trendlines`
Legacy reference: `src/libs/models/trendlines_old`
Primary downstream consumer reviewed: `src/libs/models/regime_v2/adapters/trendline_feature_producer.py`

## 1. Current Mode

Research + architecture.

This document evaluates the current trendlines model as a market-structure engine, identifies effectiveness gaps in the exposed feature surface, proposes a modular target architecture, and defines a phased implementation and evaluation plan.

No source-code changes are included in this task.

---

## 2. Executive Decision

The current model should not be replaced.

It already has strong reusable foundations:

- pivot extractor and fitter plugin registries,
- multiple fitting methods,
- a public facade,
- boundary/ray contracts,
- normalized geometry features,
- temporal snapshot support,
- native structural/temporal/pattern/fakeout signals,
- walk-forward optimization infrastructure,
- replay/data/workflow contracts,
- an isolated RegimeV2 adapter.

However, the model currently behaves more like a deterministic geometry and annotation engine than a fully calibrated structural-state model.

The correct direction is:

```text
retain the fitting core
  + separate detection, estimation, lifecycle, interaction, feature encoding, and signal policy
  + add uncertainty and event-state semantics
  + align each optimizer with the layer it actually evaluates
  + evaluate downstream utility separately from geometric fit quality
```

The first work should not be deep learning, Hough-transform proliferation, or more pattern labels.

The first work should be:

1. fix optimizer/objective mismatch,
2. introduce stable ray identity and lifecycle tracking,
3. replace exact-line interaction with uncertainty-aware structural zones,
4. implement multi-bar interaction events/state transitions,
5. calibrate feature quality and downstream usefulness,
6. then add multi-scale and optional market-microstructure enrichers.

---

## 3. Core Research Conclusion

A useful trendline model should answer five different questions, and the current package partly mixes them:

1. **What structural candidates exist?**
   - pivots,
   - lines,
   - horizontal levels,
   - zones,
   - channels.

2. **How uncertain and stable is each candidate?**
   - residual dispersion,
   - parameter sensitivity,
   - fitter agreement,
   - perturbation stability,
   - age and decay.

3. **What is the lifecycle state of each structure?**
   - born,
   - active,
   - tested,
   - weakened,
   - breached,
   - confirmed broken,
   - retested,
   - role-reversed,
   - expired.

4. **What event is occurring now?**
   - approach,
   - touch,
   - rejection,
   - pressure,
   - wick breach,
   - body breach,
   - close confirmation,
   - retest,
   - failed breakout.

5. **How should a downstream model use the structure?**
   - raw normalized features,
   - calibrated probabilities,
   - risk annotations,
   - optional trading signals.

The target architecture should make these five concerns explicit.

---

## 4. Existing Capability Inventory

## 4.1 Candidate generation

Current extractors:

- `fractal`
- `rdp_zigzag`

Strengths:

- deterministic,
- simple plugin contract,
- supports local extrema and noise-reduced structural pivots,
- extractor search grids already exist.

Current gaps:

- only physical-time/bar-window and RDP-style pivot semantics,
- no event-driven directional-change extractor,
- no multi-threshold pivot hierarchy,
- no explicit pivot confidence,
- no pivot provenance chain across scales,
- no pivot lifecycle or replacement semantics.

## 4.2 Line estimation

Current fitters:

- `pathfinding`
- `least_squares`
- `ransac`
- `ensemble`

Strengths:

- method diversity,
- deterministic seeding where relevant,
- body-cut rejection,
- residual/inlier metadata,
- registry-based construction,
- ensemble deduplication.

Current gaps:

- fitted output is a point estimate rather than an interval/band,
- no coefficient uncertainty,
- no stability-under-resampling score,
- no systematic endpoint sensitivity score,
- no fitter-consensus score exposed as a first-class feature,
- no explicit reason for line rejection,
- no shared candidate ranking/calibration layer.

## 4.3 Boundary adaptation

Current boundary layer exposes:

- support and resistance rays,
- best support/resistance,
- hull floor and ceiling,
- interaction label,
- structure state,
- market position state,
- ATR-normalized distances,
- hull position,
- compression,
- pressure states,
- normalized quality components.

Strengths:

- good downstream contract isolation,
- one-sided structures are represented,
- normalized context is already suitable for RegimeV2,
- raw fitter metadata remains available.

Current gaps:

- line is treated as an exact scalar boundary,
- latest interaction uses only the latest close and tolerance,
- interaction does not distinguish wick breach from close/body breach,
- no confirmation duration,
- no penetration magnitude/duration state,
- no retest or role-reversal lifecycle in the boundary contract,
- best ray is selected by raw `score`, while normalized quality is maintained separately,
- exact-line crossing can be too brittle in noisy markets.

## 4.4 Temporal context

Current temporal features include:

- previous/current interaction transition,
- previous/current market-position transition,
- hull width change,
- convergence and expansion rate,
- quality deltas,
- support/resistance persistence,
- persistence bias,
- slope deltas and acceleration.

Strengths:

- temporal context is not entirely stateless,
- history is storage-agnostic,
- feature adapter can remain fail-soft.

Current gaps:

- default `record_snapshot=False` can leave temporal features inert unless another component populates the history,
- default history length of five snapshots is short for robust lifecycle inference,
- ray matching uses kernel equality plus absolute raw-slope tolerance only,
- matching does not consider intercept, projected level, overlap, touch anchors, age, or normalized scale,
- no stable `ray_id` or track identity,
- slope acceleration is calculated over potentially changing line identities,
- no structure birth/death/churn metrics.

## 4.5 Native signal layer

Current native extractors:

- structural,
- temporal,
- pattern,
- fakeout/retest.

Strengths:

- native signals are separated from low-level fitting,
- orchestration supports weighted aggregation,
- context can include OHLCV, ATR, and volume trustworthiness.

Current gaps:

- signal thresholds overlap semantically with hardcoded boundary thresholds,
- signal and feature annotations contain fixed heuristic cutoffs,
- signal confidence is not calibrated to future event probabilities,
- feature adapter defaults native signals off,
- no explicit abstention probability or uncertainty output,
- the distinction between descriptive structural state and prescriptive trading signal needs to remain stronger.

## 4.6 Optimization and workflows

Current optimization measures:

- longevity,
- touch accuracy,
- penetration gate,
- pivot density,
- fold stability,
- line-count penalty.

Strengths:

- forward evaluation exists,
- purge-aware walk-forward infrastructure exists,
- trials and benchmark results are persisted,
- promotion and replay contracts exist.

Critical gap:

The optimizer samples:

- `interaction_tolerance_atr`,
- `asymmetry_threshold`,
- `convergence_rate_threshold`,
- `wick_rejection_ratio`,
- `squeeze_threshold`,
- extractor/fitter categorical parameters.

But the optimizer's fold evaluation calls the low-level fitting pipeline and scores only projected `Trendline` objects.

The five continuous values above belong to boundary or signal behavior and do not affect the fitted trendlines used by the objective.

Consequences:

- Optuna can report a best value for parameters that did not affect the score,
- optimized YAML values can look evidence-backed while being effectively random with respect to the objective,
- trial importance can be misleading,
- staged narrowing around those values compounds noise,
- the model risks false confidence before downstream evaluation begins.

This is a P0 architecture/evaluation issue.

---

## 5. Current RegimeV2 Feature Surface

The adapter already exposes a broad feature set.

## 5.1 Validity and identity

- asset/timeframe,
- valid/error,
- history count,
- snapshot-recorded flag.

## 5.2 Interaction classification

- interaction label,
- direction,
- breakout,
- breakdown,
- support bounce,
- resistance bounce.

## 5.3 Structure semantics

- structure state,
- has support,
- has resistance,
- has both sides,
- closed channel,
- one-sided structure.

## 5.4 Price location

- market-position state,
- inside/above/below channel,
- near support/resistance,
- mid-channel noise,
- upper/lower pressure,
- support/resistance levels,
- ATR-normalized distances,
- hull position.

## 5.5 Channel geometry

- hull width in ATR,
- compression flag/score,
- convergence/expansion rate,
- support/resistance slope in ATR,
- slope deltas and acceleration.

## 5.6 Quality and density

- support/resistance raw score,
- support/resistance normalized quality,
- mean normalized quality,
- side-specific mean quality,
- touch counts,
- ray counts,
- mean score,
- mean touch count,
- mean R-squared.

## 5.7 Temporal persistence

- interaction transition,
- market-position transition,
- width delta,
- quality deltas,
- support/resistance persistence,
- persistence bias.

## 5.8 Policy annotations

- no-trade warning,
- low-quality warning,
- reversal context,
- breakout/breakdown context,
- pressure and continuation watches,
- strict breakout-watch components.

## 5.9 Optional native signal aggregation

- composite direction,
- composite confidence.

### Feature-surface verdict

The number of features is not the main limitation.

The model already exposes enough columns to appear feature-rich.

The important missing work is improving the statistical and lifecycle meaning of those features:

- stable identity,
- uncertainty,
- event confirmation,
- decay,
- calibration,
- multi-scale consistency,
- objective alignment.

Adding another twenty boolean annotations before fixing these foundations would increase feature count without reliably increasing effectiveness.

---

## 6. Priority Gap Matrix

| Priority | Gap | Why it matters | Recommended action |
|---|---|---|---|
| P0 | Optimizer searches parameters unused by its objective | Best values can be arbitrary | Split geometry, interaction, and signal optimizers |
| P0 | Exact line instead of uncertainty zone | False touches/breaks around noisy estimates | Add structural band contract and calibrated width |
| P0 | No stable ray identity | Persistence/deltas can compare different structures | Add tracker with `ray_id`, lineage, birth/death |
| P0 | Latest-bar interaction only | Breakout/bounce labels are brittle | Add multi-bar interaction event state machine |
| P1 | Raw score selects best ray, normalized quality is separate | Selected line may not be highest-quality line | Centralize ranking policy |
| P1 | Mean ATR for interaction, latest ATR for context | Same snapshot can use inconsistent tolerances | Resolve one volatility-scale contract |
| P1 | Hardcoded and config threshold duplication | Boundary and signal semantics can disagree | Centralize threshold policy/config |
| P1 | Temporal features often inert by default | RegimeV2 may receive zeros rather than history | Make stateful feature mode explicit and observable |
| P1 | Persistence matching is raw-slope-only | False matches across scales/levels | Match normalized geometry + overlap + anchors |
| P1 | Quality score uses fixed heuristic weights | Scores are not calibrated across methods/assets | Separate raw diagnostics from calibrated quality |
| P1 | Geometry objective not tied to downstream event utility | Long-lived lines may not improve decisions | Add event and downstream evaluation tracks |
| P2 | No multi-scale structural hierarchy | Single scale misses nested market geometry | Add scale ensemble/MTF aggregation |
| P2 | No explicit structural decay/hazard | Old lines can remain overvalued | Add age, recency, decay, survival features |
| P2 | No change-point reset | Old regimes contaminate current fit window | Optional online change-point segmentation |
| P2 | No horizontal zone generator | Diagonal lines alone miss price-memory zones | Add zone candidate plugin family |
| P2 | Limited microstructure enrichment | Breakout quality lacks liquidity evidence | Optional volume/OI/funding/order-book enrichers |
| Research | Deep attention/clustering SR model | High complexity and validation burden | Keep isolated experimental branch |
| Research | TDA structural features | Interesting regime context, weak direct need | Do not place in core trendline pipeline initially |

---

## 7. Proposed Target Architecture

```text
trendlines/
  contracts/
    pivots.py
    candidates.py
    estimates.py
    zones.py
    tracks.py
    events.py
    snapshots.py
    features.py

  scales/
    normalization.py
    timeframe.py
    volatility.py
    intrinsic_time.py

  pivots/
    base.py
    fractal.py
    rdp_zigzag.py
    directional_change.py          # new optional extractor
    multiscale.py                   # new composition layer

  candidates/
    line_candidates.py              # candidate construction
    horizontal_zones.py             # optional price-memory zones
    channel_candidates.py

  fitting/
    base.py
    pathfinding.py
    least_squares.py
    ransac.py
    ensemble.py
    diagnostics.py                  # common residual/cut/coverage metrics
    uncertainty.py                  # bands and coefficient stability

  ranking/
    policy.py
    consensus.py
    calibration.py

  tracking/
    matcher.py
    lifecycle.py
    store.py

  boundary/
    projector.py
    zone_builder.py
    context.py
    quality.py

  interactions/
    observations.py
    state_machine.py
    role_reversal.py
    labels.py

  features/
    geometry.py
    lifecycle.py
    interaction.py
    multiscale.py
    microstructure.py
    encoder.py

  signals/
    base.py
    structural.py
    temporal.py
    patterns.py
    fakeout.py
    orchestrator.py

  optimization/
    geometry/
    interaction/
    signal/
    downstream/
    validation/

  workflows/
    replay/
    evaluation/
    promotion/
    monitoring/

  api.py
```

This does not require moving every file immediately.

It defines bounded responsibilities and can be introduced incrementally.

---

## 8. Proposed Core Contracts

## 8.1 `PivotCandidate`

Suggested fields:

```python
@dataclass(frozen=True)
class PivotCandidate:
    index: int
    timestamp: pd.Timestamp
    price: float
    side: Literal["high", "low"]
    scale_id: str
    extractor: str
    prominence_atr: float
    confirmation_bars: int
    confidence: float
    metadata: dict[str, Any]
```

Why:

- current `PivotSet` is compact but loses per-pivot diagnostics,
- multi-scale extraction needs provenance,
- confirmation delay is important for avoiding repaint-like assumptions,
- prominence helps compare pivots across volatility regimes.

Compatibility:

- retain `PivotSet` as a dense numeric transport,
- optionally attach `pivot_candidates` in metadata or introduce `PivotCollection` later.

## 8.2 `LineEstimate`

Suggested fields:

```python
@dataclass(frozen=True)
class LineEstimate:
    line: Trendline
    slope_std: float
    intercept_std: float
    residual_scale_atr: float
    lower_band_offset_atr: float
    upper_band_offset_atr: float
    perturbation_stability: float
    fitter_consensus: float
    diagnostics: dict[str, Any]
```

Why:

- exact lines overstate certainty,
- residual scale and parameter stability should travel with the estimate,
- downstream interaction detection should operate on a band/zone.

## 8.3 `StructuralZone`

Suggested fields:

```python
@dataclass(frozen=True)
class StructuralZone:
    center_ray: Ray
    lower_offset_atr: float
    upper_offset_atr: float
    zone_kind: Literal["support", "resistance"]
    confidence: float
    calibration_source: str
```

The zone width can initially be:

```text
max(
  minimum ATR floor,
  robust residual quantile,
  parameter-instability projection
)
```

A later phase can add adaptive conformal calibration.

## 8.4 `RayTrack`

Suggested fields:

```python
@dataclass
class RayTrack:
    ray_id: str
    parent_ids: tuple[str, ...]
    current: StructuralZone
    lifecycle_state: str
    born_at: pd.Timestamp
    last_matched_at: pd.Timestamp
    first_touch_at: pd.Timestamp | None
    last_touch_at: pd.Timestamp | None
    touch_count_raw: int
    touch_count_effective: int
    breach_count: int
    age_bars: int
    missing_bars: int
    confidence: float
```

Required lifecycle states:

```text
CANDIDATE
ACTIVE
TESTED
WEAKENING
WICK_BREACHED
BODY_BREACHED
BREAK_CONFIRMED
RETEST_PENDING
ROLE_REVERSED
EXPIRED
```

## 8.5 `InteractionObservation`

This is the per-bar evidence, not the final event label.

Suggested fields:

```python
@dataclass(frozen=True)
class InteractionObservation:
    timestamp: pd.Timestamp
    ray_id: str
    close_distance_atr: float
    high_penetration_atr: float
    low_penetration_atr: float
    body_penetration_atr: float
    wick_penetration_atr: float
    volume_zscore: float | None
    spread_bps: float | None
    close_side: int
```

## 8.6 `InteractionEvent`

Suggested event states:

```text
APPROACH
TOUCH
REJECTION
PRESSURE
WICK_BREACH
BODY_BREACH
BREAKOUT_CONFIRMED
BREAKDOWN_CONFIRMED
RETEST
ROLE_REVERSAL
FAILED_BREAKOUT
FAILED_BREAKDOWN
```

Suggested event output:

```python
@dataclass(frozen=True)
class InteractionEvent:
    event_type: str
    direction: float
    stage: str
    confidence: float
    evidence_bars: int
    max_penetration_atr: float
    close_confirmation_bars: int
    ray_id: str
    metadata: dict[str, Any]
```

## 8.7 `TrendlineStructureSnapshot`

The public downstream payload should be richer than `BoundaryResult` while preserving compatibility.

Suggested shape:

```python
@dataclass
class TrendlineStructureSnapshot:
    asset: str
    timeframe: str
    timestamp: datetime
    tracks: list[RayTrack]
    active_support_zones: list[StructuralZone]
    active_resistance_zones: list[StructuralZone]
    channel: ChannelGeometry | None
    latest_events: list[InteractionEvent]
    diagnostics: StructureDiagnostics
    is_valid: bool
    degraded_reason: str | None
```

`BoundaryResult` can remain as a compatibility view generated from this snapshot.

---

## 9. Proposed Pipeline Flows

## 9.1 Stateless snapshot pipeline

Use for backfills, simple consumers, and compatibility.

```text
OHLCV
  -> normalize/validate
  -> resolve scales
  -> extract pivots per scale
  -> construct candidates
  -> fit line estimates
  -> compute diagnostics and uncertainty
  -> rank/deduplicate
  -> build structural zones
  -> build latest snapshot
  -> encode stateless features
```

## 9.2 Stateful live pipeline

Use for RegimeV2 live/shadow inference.

```text
new OHLCV bar
  -> update pivot candidates
  -> update line estimates
  -> match estimates to existing ray tracks
  -> update lifecycle state
  -> produce interaction observation
  -> update event state machine
  -> create structure snapshot
  -> encode lifecycle + event + geometry features
  -> optional native signal policy
```

## 9.3 Research/evaluation pipeline

```text
immutable dataset manifest
  -> temporal split manifest
  -> geometry candidate search
  -> geometry OOS evaluation
  -> freeze geometry config
  -> interaction threshold search on event labels
  -> freeze interaction config
  -> downstream feature ablation in RegimeV2
  -> promotion decision
```

## 9.4 Multi-timeframe pipeline

```text
base timeframe data
  -> construct canonical bars for each requested timeframe
  -> run independent structure pipeline per timeframe
  -> align snapshots causally to base timestamp
  -> build cross-timeframe structural graph
  -> encode agreement/conflict features
```

Do not simply copy higher-timeframe values forward without tracking when the higher-timeframe bar became complete.

---

## 10. Features to Add

## 10.1 Must-have: uncertainty and stability

Recommended features:

- `trendline_support_band_width_atr`
- `trendline_resistance_band_width_atr`
- `trendline_support_slope_std_atr`
- `trendline_resistance_slope_std_atr`
- `trendline_support_endpoint_sensitivity`
- `trendline_resistance_endpoint_sensitivity`
- `trendline_support_perturbation_stability`
- `trendline_resistance_perturbation_stability`
- `trendline_support_fitter_consensus`
- `trendline_resistance_fitter_consensus`
- `trendline_structure_uncertainty`

Perturbation stability can initially be measured by refitting after:

- removing one pivot at a time,
- changing the lookback by a small percentage,
- changing pivot-window parameters locally,
- using adjacent completed bars.

Do not run expensive bootstrap logic on every live bar initially.

Cache and refresh it on structural-change events.

## 10.2 Must-have: lifecycle and decay

Recommended features:

- `trendline_support_age_bars`
- `trendline_resistance_age_bars`
- `trendline_support_bars_since_last_touch`
- `trendline_resistance_bars_since_last_touch`
- `trendline_support_touch_interval_mean`
- `trendline_resistance_touch_interval_mean`
- `trendline_support_touch_interval_cv`
- `trendline_resistance_touch_interval_cv`
- `trendline_support_survival_score`
- `trendline_resistance_survival_score`
- `trendline_support_decay_score`
- `trendline_resistance_decay_score`
- `trendline_track_churn_rate`
- `trendline_structure_birth_rate`
- `trendline_structure_expiry_rate`

A practical initial decay model:

```text
recency_weight = exp(-age_since_last_touch / half_life_bars)
```

This should be a feature, not a hardcoded universal truth.

Calibrate half-life by asset, timeframe, structure type, and regime.

## 10.3 Must-have: richer touch/breach evidence

Recommended features:

- `trendline_support_wick_penetration_atr`
- `trendline_resistance_wick_penetration_atr`
- `trendline_support_body_penetration_atr`
- `trendline_resistance_body_penetration_atr`
- `trendline_support_close_penetration_atr`
- `trendline_resistance_close_penetration_atr`
- `trendline_break_confirmation_bars`
- `trendline_break_max_penetration_atr`
- `trendline_rejection_wick_ratio`
- `trendline_rejection_close_recovery_atr`
- `trendline_pressure_duration_bars`
- `trendline_touch_cluster_density`
- `trendline_effective_touch_count`

This removes the need to compress all current evidence into one four-class interaction label.

## 10.4 Must-have: event-state features

Recommended features:

- `trendline_event_type`
- `trendline_event_stage`
- `trendline_event_direction`
- `trendline_event_confidence`
- `trendline_event_age_bars`
- `trendline_retest_pending`
- `trendline_retest_confirmed`
- `trendline_failed_breakout`
- `trendline_failed_breakdown`
- `trendline_role_reversal_active`

Keep the old interaction one-hots as compatibility aliases.

## 10.5 Must-have: stable track identity

Recommended features:

- `trendline_best_support_track_id_hash`
- `trendline_best_resistance_track_id_hash`
- `trendline_support_track_changed`
- `trendline_resistance_track_changed`
- `trendline_support_lineage_depth`
- `trendline_resistance_lineage_depth`

The model does not need to expose raw UUID strings to every ML consumer.

It should expose stable change/continuity semantics.

## 10.6 Should-have: channel geometry

Recommended features:

- `trendline_channel_mid_slope_atr`
- `trendline_channel_slope_spread_atr`
- `trendline_channel_parallelism_score`
- `trendline_channel_symmetry_score`
- `trendline_channel_apex_bars`
- `trendline_channel_divergence_rate`
- `trendline_channel_asymmetry_atr`
- `trendline_channel_width_percentile`
- `trendline_hull_position_velocity`
- `trendline_hull_position_acceleration`

The current width/compression surface is useful but incomplete.

## 10.7 Should-have: multi-scale and MTF structure

Recommended features:

- `trendline_scale_count`
- `trendline_support_scale_consensus`
- `trendline_resistance_scale_consensus`
- `trendline_nearest_support_confluence_count`
- `trendline_nearest_resistance_confluence_count`
- `trendline_mtf_direction_agreement`
- `trendline_mtf_channel_position_agreement`
- `trendline_mtf_conflict_score`
- `trendline_dominant_structure_scale`
- `trendline_cross_scale_breakout_confirmation`

A structural model is naturally hierarchical.

Do not collapse all scales into one ensemble before preserving scale identity.

## 10.8 Should-have: regime-conditioned calibration

Recommended features:

- `trendline_quality_percentile_regime`
- `trendline_band_width_percentile_regime`
- `trendline_event_base_rate_regime`
- `trendline_touch_success_probability_regime`
- `trendline_break_success_probability_regime`

RegimeV2 should consume trendline features.

Trendlines may also consume a coarse lagged/previous regime state for calibration, but avoid circular same-bar dependency.

Safe dependency:

```text
previous confirmed regime state
  -> select calibration bucket
  -> compute current trendline calibrated features
  -> current RegimeV2 inference
```

Unsafe dependency:

```text
current RegimeV2 output
  -> current trendline feature generation
  -> same current RegimeV2 output
```

## 10.9 Optional: market-microstructure enrichers

Optional enrichers should remain plugins:

- volume z-score around touch,
- taker buy/sell imbalance,
- open-interest change,
- funding-rate state,
- spread and depth quality,
- liquidation intensity,
- anchored VWAP confluence,
- volume-profile node distance.

Suggested rule:

```text
geometry core must work with OHLCV only
microstructure enrichers improve confidence but must not be mandatory
```

## 10.10 Optional research: horizontal structural zones

Diagonal trendlines should be one candidate family, not the entire concept of market structure.

Add a plugin family for horizontal or slowly varying zones based on:

- clustered pivot prices,
- robust price-density modes,
- time-at-price,
- volume-at-price where available,
- repeated rejection zones.

Return the same `StructuralZone` contract so downstream components remain agnostic.

## 10.11 Optional research: directional-change pivots

A directional-change extractor is attractive because it defines pivots by price movement rather than fixed bar distance.

Potential benefits:

- more comparable behavior across volatility states,
- natural multi-threshold hierarchy,
- reduced dependence on timeframe bar density,
- event-based structural timing.

Risks:

- threshold calibration,
- multiple nearby scales,
- live confirmation delay,
- duplication with RDP if poorly differentiated.

Treat it as a new extractor plugin and benchmark against fractal/RDP.

---

## 11. Features Not Recommended Yet

Do not immediately add:

- a transformer/attention model inside the core trendline package,
- image-based chart-pattern recognition,
- reinforcement learning for line selection,
- topological data analysis in the runtime path,
- dozens of named classical patterns,
- sentiment or news directly inside trendline fitting,
- order-book-only mandatory dependencies,
- a universal learned score trained across all assets without calibration buckets.

Reasons:

- the current core objective is not yet aligned,
- identity and uncertainty are unresolved,
- complex models would learn instability in the labels/contracts,
- evaluation complexity would rise faster than structural reliability.

Deep models can be revisited after a deterministic event dataset and stable contracts exist.

---

## 12. Ranking and Quality Redesign

## 12.1 Current issue

Current ray selection often uses raw fitter `score`.

Normalized quality is separately derived from:

- coverage,
- touches,
- residual/inlier quality,
- no-cut score,
- recency.

A ray can therefore be selected as `best_support` by raw score while another ray has higher normalized quality.

## 12.2 Proposed separation

Maintain three concepts:

### A. Raw diagnostics

Method-specific, never forced into identical meaning:

- R-squared,
- inlier ratio,
- path score,
- cut fraction,
- residual dispersion,
- pivot count.

### B. Comparable structural quality

A calibrated score for comparing candidates across methods.

Suggested initial components:

- effective touch evidence,
- robust residual quality,
- coverage,
- recency/age,
- penetration history,
- perturbation stability,
- fitter consensus.

### C. Selection utility

Context-specific ranking:

- nearest reliable support,
- strongest support,
- nearest reliable resistance,
- channel-defining pair,
- most persistent line,
- breakout-relevant boundary.

There should not be only one universal `best_support`.

Suggested public selectors:

```python
boundary.nearest_support
boundary.highest_quality_support
boundary.most_persistent_support
boundary.channel_support
```

Keep `best_support` as a compatibility alias with a documented ranking policy.

---

## 13. Volatility and Tolerance Contract Redesign

Current behavior has a consistency risk:

- interaction detection uses mean ATR,
- boundary context tolerance uses latest ATR.

Proposed contract:

```python
@dataclass(frozen=True)
class VolatilityScale:
    latest_atr: float
    robust_atr: float
    atr_percentile: float
    source_window: int
    scale_used_for_interaction: float
    scale_policy: str
```

Recommended initial policy:

```text
interaction_scale = max(latest_atr, rolling_median_atr * floor_ratio)
```

This avoids:

- very small latest ATR causing hyper-sensitive breaks,
- old mean ATR suppressing valid current-volatility interactions.

The exact policy must be evaluated, not assumed.

All interaction, band width, distances, and penetration features should declare the same scale source.

---

## 14. Interaction State Machine

A robust interaction model should not emit `STRUCTURAL_BREAKOUT` from a single point comparison alone.

Suggested state transitions:

```text
FAR
  -> APPROACH
  -> IN_ZONE
  -> REJECTED

IN_ZONE
  -> PRESSURE
  -> WICK_BREACH
  -> BODY_BREACH

WICK_BREACH
  -> REJECTED
  -> BODY_BREACH

BODY_BREACH
  -> BREAK_PENDING
  -> FAILED_BREAK

BREAK_PENDING
  -> BREAK_CONFIRMED
  -> FAILED_BREAK

BREAK_CONFIRMED
  -> RETEST_PENDING
  -> CONTINUATION

RETEST_PENDING
  -> ROLE_REVERSAL_CONFIRMED
  -> FAILED_BREAK
```

Evidence knobs:

- close vs zone,
- body fraction beyond zone,
- wick-only penetration,
- consecutive completed closes,
- maximum adverse recovery,
- ATR-normalized penetration,
- optional volume and spread quality.

Output both:

- descriptive stage,
- calibrated event confidence.

Do not force a trade direction at the event detector layer.

---

## 15. Structural Decay and Survival

Research on support/resistance behavior motivates representing both repeated evidence and time decay.

The current model includes touch count and recency inside a fixed quality formula, but it does not expose a structural survival process.

Suggested diagnostics:

- age since creation,
- age since last validated touch,
- number of effective touches,
- mean and variance of touch spacing,
- penetration count,
- failed-test count,
- current survival probability estimate,
- hazard of invalidation within horizon.

Initial non-ML model:

```text
survival_score =
    touch_evidence
    * recency_decay
    * penetration_penalty
    * stability_score
```

Later model:

- discrete-time survival model,
- calibrated separately by asset/timeframe/regime,
- target: line remains valid for the next H bars.

This target is more directly useful than a generic raw quality score.

---

## 16. Optimizer Redesign

## 16.1 Geometry optimizer

Search only parameters that affect pivots and fitted geometry:

- extractor choice,
- left/right window,
- RDP epsilon/ATR scale,
- pivot prominence,
- fitter choice,
- pathfinding pivot window,
- pathfinding refit mode,
- RANSAC tolerance/iterations,
- least-squares residual threshold,
- lookback length,
- deduplication thresholds.

Objective components:

- OOS survival,
- effective touch precision,
- penetration severity and duration,
- coverage,
- stability under adjacent windows,
- candidate-count regularization,
- compute cost.

Output:

```text
GeometryOptimizationResult
```

Do not output signal thresholds.

## 16.2 Interaction optimizer

Search parameters that affect structural event detection:

- zone width/tolerance,
- wick/body breach thresholds,
- confirmation bars,
- pressure duration,
- retest window,
- failed-break recovery threshold.

Required input:

- frozen geometry config,
- event labels generated causally,
- explicit horizon/outcome definitions.

Possible objective:

- event precision/recall,
- Brier score or log loss for calibrated probability,
- expected favorable/adverse excursion conditional on event,
- false-break rate,
- detection delay.

Output:

```text
InteractionOptimizationResult
```

## 16.3 Signal-policy optimizer

Search:

- signal extractor weights,
- abstention thresholds,
- confluence requirements,
- optional microstructure gates.

Required input:

- frozen geometry and interaction configs.

Objective:

- downstream strategy utility after costs,
- stability across regimes/assets,
- event-level calibration,
- turnover and exposure constraints.

Output:

```text
SignalPolicyOptimizationResult
```

## 16.4 Downstream feature evaluation

RegimeV2 feature usefulness must be evaluated independently.

Run feature groups as ablations:

1. geometry only,
2. + quality,
3. + lifecycle,
4. + events,
5. + multi-scale,
6. + optional microstructure,
7. + native signals.

Measure:

- OOS probability/log-loss improvements,
- calibration,
- regime classification stability,
- final playbook decision activation,
- strategy-level performance after costs,
- feature drift and missingness.

Do not promote a feature merely because its standalone trendline benchmark improved.

---

## 17. Validation and Backtest Controls

Required controls:

- immutable dataset manifest,
- causal completed-bar semantics,
- explicit pivot confirmation delay,
- fit/test projection index validation,
- purging based on label/event horizon,
- embargo where overlapping outcomes exist,
- walk-forward evaluation,
- untouched final holdout,
- all-trial persistence,
- multiple-testing-aware reporting,
- asset/timeframe stratification,
- regime stratification,
- missing/invalid snapshot accounting.

Important reports:

- trial parameter sensitivity,
- no-op parameter detection,
- per-fold event counts,
- confidence intervals around low-count metrics,
- worst-fold and tail metrics,
- feature ablation table,
- calibration curves,
- drift report,
- selected-vs-all-trials comparison.

A geometry model should not be approved based only on the best aggregate scalar objective.

---

## 18. Suggested Evaluation Labels

## 18.1 Line survival label

```text
Y_survive(H) = 1
if the line is not invalidated by a confirmed body/close breach within H bars
```

## 18.2 Touch reaction label

For support:

```text
favorable_excursion = max(high[t+1:t+H]) - touch_price
adverse_excursion = touch_price - min(low[t+1:t+H])
```

For resistance, reverse direction.

Label based on ATR-normalized favorable vs adverse excursion.

## 18.3 Breakout success label

```text
break_success =
  confirmed close outside zone
  + no recovery back inside within failure_window
  + minimum favorable excursion reached
```

## 18.4 Retest success label

```text
retest_success =
  price revisits broken zone
  + rejects in breakout direction
  + does not close through invalidation boundary
```

## 18.5 Role-reversal label

```text
role_reversal =
  former resistance behaves as support after confirmed breakout
  or former support behaves as resistance after confirmed breakdown
```

These labels should be explicit, versioned contracts.

---

## 19. Multi-Scale Design

Recommended scales:

- extractor parameter scales within one timeframe,
- multiple completed timeframes,
- optional directional-change thresholds.

Do not pool candidates immediately.

Pipeline:

```text
scale-specific pivots
  -> scale-specific estimates
  -> scale-specific zones/tracks
  -> cross-scale confluence graph
  -> final selectors/features
```

Confluence edge criteria:

- projected level distance in ATR,
- slope similarity in ATR/bar,
- overlapping active time interval,
- support/resistance role compatibility,
- shared pivot anchors,
- lifecycle compatibility.

Cross-scale output should expose:

- agreement,
- conflict,
- dominant scale,
- nearest confluence cluster,
- cluster quality dispersion.

---

## 20. Change-Point Integration

Trendline fits are vulnerable when the lookback spans structurally different regimes.

A change-point module can be used as a fit-window adviser, not as a mandatory replacement for the existing lookback system.

Suggested interface:

```python
class SegmentationPolicy(Protocol):
    def fit_start_index(self, df: pd.DataFrame) -> int: ...
```

Implementations:

- fixed lookback,
- volatility-shift heuristic,
- Bayesian online change-point detector,
- previous RegimeV2 boundary,
- hybrid minimum/maximum window.

Safe initial use:

```text
fit_start = max(
  fixed_lookback_start,
  latest_high-confidence_change_point
)
```

Guardrails:

- minimum bars,
- change-point confidence threshold,
- fallback to fixed lookback,
- separate evaluation by regime.

---

## 21. API Evolution

Maintain current APIs:

- `fit_trendlines`
- `fit_trendlines_to_boundary`
- `fit_and_signal`

Add a richer API:

```python
analyze_structure(
    df,
    *,
    asset,
    timeframe,
    state=None,
    config=None,
) -> TrendlineAnalysisOutput
```

Suggested output:

```python
@dataclass
class TrendlineAnalysisOutput:
    fit_result: TrendlineFitResult
    structure_snapshot: TrendlineStructureSnapshot
    boundary_result: BoundaryResult
    features: Mapping[str, Any]
    native_signals: Sequence[AlphaSignal]
    composite_direction: float
    composite_confidence: float
    diagnostics: Mapping[str, Any]
```

Stateful entry point:

```python
update_structure(
    previous_state,
    new_bar,
    *,
    config,
) -> tuple[TrendlineStructureState, TrendlineAnalysisOutput]
```

This avoids repeatedly rebuilding all history in live mode.

---

## 22. Configuration Redesign

Suggested config groups:

```yaml
trendlines:
  scales:
  pivots:
  candidate_generation:
  fitting:
  uncertainty:
  ranking:
  tracking:
  zones:
  interactions:
  features:
  signals:
  optimization:
  monitoring:
```

Rules:

- each parameter must have one owner,
- each optimized parameter must influence the objective being optimized,
- hardcoded market thresholds should be named constants only when truly invariant,
- boundary and signal thresholds must not silently duplicate meanings,
- resolved config should include provenance:
  - default,
  - asset override,
  - timeframe override,
  - derived,
  - optimized,
  - runtime override.

Add validation:

```text
parameter_effect_registry
```

Each optimizable parameter declares which pipeline stages it affects.

A dry-run test should fail if a searched parameter does not change any evaluated output across controlled inputs.

---

## 23. Monitoring Redesign

Current drift monitoring focuses on boundary quality snapshots.

Add monitoring for:

- valid snapshot rate,
- support/resistance availability rate,
- one-sided structure rate,
- ray count distribution,
- track churn,
- zone width distribution,
- interaction/event frequency,
- confirmed-break success rate,
- touch success rate,
- event calibration error,
- feature missingness,
- fitter mix and consensus,
- geometry compute latency,
- RegimeV2 feature attribution drift.

Drift should be evaluated by:

- asset,
- timeframe,
- volatility bucket,
- regime bucket,
- structure type.

---

## 24. Handling `trendlines_old`

`src/libs/models/trendlines_old` is mostly a snapshot of the active package and imports through `app.trendlines.*`.

It should not participate in runtime, tests, codebase-memory indexing, or symbol discovery.

Recommended treatment:

1. preserve optimization result artifacts separately if still needed,
2. generate a manifest of historical result files,
3. move archival evidence outside importable Python source paths,
4. remove the duplicate package,
5. reindex codebase-memory,
6. rerun canonical-symbol/import-boundary tests.

Do not use `trendlines_old` as a second implementation branch.

Use Git history or an explicit non-importable archive instead.

---

## 25. Recommended Phases

## Phase 0 — Correctness and ownership cleanup

Scope:

- remove/archive `trendlines_old`,
- clean canonical symbol duplication,
- document canonical imports,
- add optimizer no-op parameter test,
- split optimization result contracts conceptually.

Exit criteria:

- import-boundary tests pass,
- codebase-memory no longer resolves old duplicates,
- no optimizer searches a parameter that cannot affect its objective.

## Phase 1 — Geometry diagnostics and ranking

Scope:

- centralize line diagnostics,
- add method-independent quality components,
- expose fitter consensus,
- centralize ray ranking policy,
- fix raw-score vs normalized-quality selection ambiguity,
- unify volatility/tolerance contract.

Exit criteria:

- selectors have documented semantics,
- all candidates expose comparable diagnostics,
- boundary/context interaction uses the same resolved volatility scale.

## Phase 2 — Stable tracking and lifecycle

Scope:

- implement ray matcher,
- add stable track identity,
- add birth/death/churn,
- replace slope-only persistence,
- make RegimeV2 temporal state mode explicit,
- increase configurable history horizon.

Exit criteria:

- slope deltas/acceleration compare the same tracked structure,
- persistence tests include intercept/level and temporal overlap,
- stateful replay is deterministic.

## Phase 3 — Structural zones and uncertainty

Scope:

- residual-based band,
- minimum ATR width,
- endpoint/perturbation stability,
- `StructuralZone` contract,
- compatibility `BoundaryResult` projection.

Exit criteria:

- interactions operate on zones,
- band width is exposed and tested,
- uncertainty features are causal and stable.

## Phase 4 — Interaction event state machine

Scope:

- per-bar observations,
- wick/body/close penetration,
- confirmation bars,
- pressure duration,
- retest/failure/role reversal,
- event contract and compatibility labels.

Exit criteria:

- no single-close-only breakout classification in the primary path,
- event labels are versioned,
- state-machine replay tests pass.

## Phase 5 — Optimizer split and calibrated event evaluation

Scope:

- geometry optimizer,
- interaction optimizer,
- signal-policy optimizer,
- event outcome datasets,
- calibration and count-aware reports.

Exit criteria:

- parameter-effect tests pass,
- interaction probabilities are evaluated by Brier/log-loss or equivalent,
- trial selection reports all-trial context.

## Phase 6 — RegimeV2 feature ablation

Scope:

- geometry baseline,
- lifecycle group,
- uncertainty group,
- event group,
- multi-scale group,
- microstructure group,
- native-signal group.

Exit criteria:

- each promoted group adds OOS value or improves calibration/stability,
- no feature group is promoted only from in-sample importance.

## Phase 7 — Multi-scale structures

Scope:

- multiple extractor scales,
- causal MTF snapshots,
- confluence graph,
- conflict and dominant-scale features.

Exit criteria:

- no higher-timeframe leakage,
- scale identity is preserved,
- MTF ablation improves downstream metrics.

## Phase 8 — Optional research branches

Candidates:

- directional-change extractor,
- horizontal-zone candidates,
- change-point fit-window adviser,
- attention/clustering support model,
- advanced adaptive conformal calibration.

Promote only after deterministic core and labels are stable.

---

## 26. Minimal High-Impact Feature Set

If implementation scope must remain small, add these first:

1. stable support/resistance track identity,
2. bars since last touch,
3. line age,
4. effective/declustered touch count,
5. body penetration ATR,
6. wick penetration ATR,
7. confirmation bars,
8. zone/band width ATR,
9. perturbation stability,
10. fitter consensus,
11. structure churn,
12. event stage,
13. role-reversal state,
14. calibrated survival score,
15. multi-scale confluence count.

These add more real structural information than adding many new named pattern booleans.

---

## 27. Tests Required

## 27.1 Contract tests

- serialization round trips,
- stable IDs,
- compatibility boundary projection,
- invalid/degraded output semantics.

## 27.2 Parameter-effect tests

For every optimizable parameter:

- construct a controlled input,
- run lower and upper parameter values,
- assert a stage owned by that parameter changes,
- assert the evaluated objective observes the change.

## 27.3 Tracking tests

- small slope change preserves ID,
- large projected-level change creates new ID,
- split/merge lineage,
- missing snapshots and expiry,
- support/resistance role changes.

## 27.4 Interaction tests

- exact touch,
- near-zone touch,
- wick breach and recovery,
- body breach without close confirmation,
- confirmed breakout,
- failed breakout,
- retest,
- role reversal,
- low-volume optional evidence,
- missing volume fallback.

## 27.5 Causality tests

- pivot not available before confirmation,
- higher-timeframe feature only available after bar completion,
- no future touch in current quality,
- event outcomes only used during evaluation,
- history excludes current snapshot.

## 27.6 Calibration tests

- reliability by confidence bucket,
- expected calibration error,
- Brier score,
- coverage of structural bands,
- distribution shift/drift scenarios.

---

## 28. Research Evidence and Design Implications

### Support/resistance evidence, repeated touches, and decay

Chung and Bellotti's empirical study of support/resistance levels reports that levels with more prior bounces were more likely to bounce again, while level effectiveness decayed over time.

Design implication:

- preserve effective touch count,
- add age and bars-since-last-touch,
- model decay/survival explicitly,
- do not treat touch count as monotonically valuable without recency.

Reference:

- Ken Chung and Anthony Bellotti, *Evidence and Behaviour of Support and Resistance Levels in Financial Time Series*, arXiv:2101.07410.

### Online change-point detection

Bayesian online change-point detection models the posterior distribution of the current run length, while later autoregressive variants address temporal dependence and time-varying parameters.

Design implication:

- use change-point probability as an optional fit-window adviser,
- reset or downweight structures crossing high-confidence regime boundaries,
- keep a fixed-lookback fallback.

References:

- Ryan P. Adams and David J. C. MacKay, *Bayesian Online Changepoint Detection*, arXiv:0710.3742.
- Ioanna-Yvonni Tsaknaki, Fabrizio Lillo, and Piero Mazzarisi, *Bayesian Autoregressive Online Change-Point Detection with Time-Varying Parameters*, arXiv:2407.16376.

### Adaptive uncertainty under distribution shift

Adaptive conformal work addresses uncertainty intervals for dependent or shifting time series, and newer work combines change-point state estimation with online conformal prediction.

Design implication:

- begin with robust residual/perturbation bands,
- later calibrate zone coverage online,
- monitor empirical coverage by regime and volatility bucket.

References:

- Margaux Zaffran et al., *Adaptive Conformal Predictions for Time Series*, arXiv:2202.07282.
- Sophia Sun and Rose Yu, *Conformal Prediction for Time-series Forecasting with Change Points*, arXiv:2509.02844.

### Event-based/intrinsic-time structure

Directional-change intrinsic time represents market movement using threshold events rather than equal physical-time intervals and has been used to expose multi-scale behavior in financial data.

Design implication:

- add directional change as an optional pivot extractor,
- compare event-threshold scales with fractal/RDP pivots,
- preserve scale identity.

Reference:

- James B. Glattfelder and Anton Golub, *Bridging the Gap: Decoding the Intrinsic Nature of Time in Market Data*, arXiv:2204.02682.

### Dynamic support detection with learned representations

DeepSupp proposes attention-based representation learning and clustering for dynamic support identification, including market-microstructure relationships.

Design implication:

- learned support-zone models may be valuable later,
- use them as independent candidate generators returning the same zone contract,
- do not entangle them with the deterministic core before labels and evaluation are stable.

Reference:

- Boris Kriuk, Logic Ng, and Zarif Al Hossain, *DeepSupp: Attention-Driven Correlation Pattern Analysis for Dynamic Time Series Support and Resistance Levels Identification*, arXiv:2507.01971.

### Alternative nonlinear structural diagnostics

Topological data analysis has been used to identify changing multidimensional structure around financial stress episodes.

Design implication:

- TDA may complement regime detection,
- it is not a priority feature for line fitting or boundary interaction,
- keep it outside the core trendline runtime path.

Reference:

- Marian Gidea and Yuri Katz, *Topological Data Analysis of Financial Time Series: Landscapes of Crashes*, arXiv:1703.04385.

### Backtest selection bias

Research on trading-rule selection and post-selection Sharpe estimation emphasizes that searching many alternatives and then reporting the selected result creates optimistic bias.

Design implication:

- record all trials,
- separate research holdout from tuning folds,
- report selected-vs-trial-population behavior,
- avoid optimizing parameters that do not influence the evaluated objective.

References:

- Peter Carr and Marcos López de Prado, *Determining Optimal Trading Rules without Backtesting*, arXiv:1408.1159.
- Steven E. Pav, *Post Selection Estimation of Sharpe Ratios*, arXiv:2606.01650.

---

## 29. Final Architecture Recommendation

The model should become a **structural inference system**, not merely a line fitter or annotation generator.

Recommended conceptual stack:

```text
Candidate Detection
  -> Robust Estimation
  -> Uncertainty Bands
  -> Candidate Ranking
  -> Stable Tracking/Lifecycle
  -> Interaction Event State Machine
  -> Normalized Feature Encoding
  -> Optional Signal Policy
  -> Layer-Specific Evaluation and Promotion
```

The current implementation already provides most of the candidate detection, robust estimation, basic ranking, feature encoding, and workflow scaffolding.

The missing center of gravity is:

```text
uncertainty + identity + lifecycle + event confirmation + calibrated evaluation
```

That is where the next phases should focus.

---

## 30. Recommended Immediate Next Handoff

Architecture handoff for Phase 0 and Phase 1 only.

Scope:

1. archive/remove `trendlines_old` from importable source,
2. add optimizer parameter-effect audit tests,
3. split geometry-only search space from boundary/signal thresholds,
4. introduce a centralized `RayRankingPolicy`,
5. unify volatility/tolerance scale,
6. define but do not yet fully implement `StructuralZone`, `RayTrack`, and `InteractionEvent` contracts,
7. produce coder-ready file-level changes and migration compatibility plan.

Do not begin multi-scale, directional-change, deep-learning, or conformal implementation until the above foundation is approved.
