---
goal: Implement RegimeProbV1 — probabilistic regime/playbook overlay built on top of deterministic RegimeV2
stage: architect-to-coder
date_created: 2026-07-06
owner: Quant Research Architect
status: Revised and ready for phased implementation
tags: [handoff, quant, regime-v2, probabilistic-regime, calibration, hmm, bcpd, moe, mtf, optimization]
source_agent: ChatGPT GPT-5.5 Thinking
target_agent: Codex Agent
---

# Architect-to-Coder: RegimeProbV1

## 0. Executive Summary

Build `RegimeProbV1` as an additive probabilistic overlay on top of the existing deterministic `RegimeV2` module.

The key objective is **not** to add HMMs again. The repo already has older probabilistic/HMM regime work in:

- `src/libs/regime/`
- `src/libs/models/regime_classification/`

The new objective is to move from **latent state probability** to **calibrated playbook / edge probability**.

Old regime model answered:

```text
P(market latent state = TRENDING / NON_TRENDING / CRISIS)
```

RegimeProbV1 must answer:

```text
P(state = trend/range/chop/breakout/vol_shock/transition)
P(trend_following_edge > fees)
P(breakout_edge > fees)
P(mean_reversion_edge > fees)
P(scalping_edge > fees)
P(countertrend_edge > fees)
```

RegimeV2 remains the deterministic evidence and policy engine. RegimeProbV1 consumes RegimeV2 evidence/policy outputs, optional kernel features, optional cross-asset context, and forward outcome labels to train calibrated probability heads.

The first milestone is not an HMM rebuild. The first milestone is:

```text
point-in-time feature frame
leakage-safe forward labels
purge-aware train/calibration/validation/OOS protocol
empirical edge calibration report
```

An explicit state-probability head is optional later, only if it adds incremental OOS value beyond the edge-calibration layer.

---

## 1. Core Design Decisions

### 1.1 Keep RegimeV2 deterministic

Do not mutate `src/libs/models/regime_v2/` into a giant probabilistic model.

RegimeV2 currently emits:

- deterministic normalized evidence scores
- confidence / uncertainty
- policy playbook scores
- boolean allow gates
- playbook state machine / orchestration context

Those outputs are useful and interpretable. Keep them stable.

### 1.2 Add a separate probabilistic wrapper

Add new package:

```text
src/libs/models/regime_prob_v1/
```

This package should call/use:

- `RegimeV2Orchestrator.analyze_series()`
- old BCPD/Hurst/Hilbert kernels via adapters where useful
- optional old `RegimeClassificationModel` outputs as baseline/adaptor features
- optional TV/index/cross-asset context
- optional trendline/market-geometry features

### 1.3 Do not equate normalized score with probability

Wrong:

```text
regime_v2.confidence = 0.72 => P(edge > 0) = 0.72
```

Correct:

```text
regime_v2.confidence is an input feature.
Calibrated edge head learns P(edge > fees) from forward outcomes.
```

### 1.4 Use probabilities only after calibration/audit

Every probability head must provide:

- Brier score
- log loss
- calibration bins / reliability report
- top-bottom bucket spread
- OOS lift vs deterministic RegimeV2
- support count
- rolling stability

No probability output should be promoted to runtime gating without these audits.

---

## 2. Existing Repo Context

### 2.1 Existing RegimeV2 module

Main path:

```text
src/libs/models/regime_v2/
```

Important existing files:

```text
src/libs/models/regime_v2/contracts.py
src/libs/models/regime_v2/config.py
src/libs/models/regime_v2/orchestrator.py
src/libs/models/regime_v2/features/trend.py
src/libs/models/regime_v2/features/volatility.py
src/libs/models/regime_v2/features/mean_reversion.py
src/libs/models/regime_v2/features/breaks.py
src/libs/models/regime_v2/features/market_context.py
src/libs/models/regime_v2/fusion/rule_fusion.py
src/libs/models/regime_v2/policy/playbook_policy.py
src/libs/models/regime_v2/policy/playbook_state_machine.py
src/libs/models/regime_v2/optimization/
```

RegimeV2 optimizer already exists and should remain separate:

```text
src/libs/models/regime_v2/optimization/optimizer.py
src/libs/models/regime_v2/optimization/validation.py
src/libs/models/regime_v2/optimization/threshold_sweep.py
src/libs/models/regime_v2/optimization/optimize.py
src/libs/models/regime_v2/optimization/batch_optimize.py
```

### 2.2 Existing old regime/HMM stack

Older stack paths:

```text
src/libs/regime/
src/libs/models/regime_classification/
```

Notable components:

```text
src/libs/regime/hmm_classifier.py
src/libs/regime/change_detector.py
src/libs/regime/kernels/changepoint/core.py
src/libs/regime/kernels/hurst.py
src/libs/regime/kernels/hilbert_cycle.py
src/libs/models/regime_classification/kernels/hmm.py
src/libs/models/regime_classification/kernels/bcpd.py
src/libs/models/regime_classification/kernels/hurst.py
src/libs/models/regime_classification/kernels/hilbert.py
src/libs/models/regime_classification/optimization/probability_ladder.py
```

Reuse these concepts/adapters, but do not copy the entire old orchestrator.

### 2.3 Existing TV/index context

Config:

```text
configs/tradingview.yaml
```

Already includes:

```text
CRYPTOCAP:TOTAL2
CRYPTOCAP:TOTAL3
CRYPTOCAP:TOTAL3ES
CRYPTOCAP:BTC.D
```

Also includes derivatives context for:

```text
BTCUSDT OI / funding
ETHUSDT OI / funding
BNBUSDT OI / funding
SOLUSDT OI / funding
```

Use these later as optional cross-asset context features.

---

## 3. Non-Goals

Do not implement these in the first slice:

1. Do not replace RegimeV2.
2. Do not delete `src/libs/regime/` or `src/libs/models/regime_classification/`.
3. Do not force live trading from RegimeProbV1.
4. Do not make TV/index data mandatory for inference.
5. Do not use HMM posterior as final trade probability.
6. Do not add Hilbert cycle in Phase P1 unless trivial.
7. Do not optimize all parameters in one giant search space.
8. Do not let runtime rewrite trained/calibrated parameters.
9. Do not use future HTF/index bars in backtest alignment.
10. Do not use probability layer to force trades when deterministic RegimeV2 says no-trade in early rollout.

---

## 4. Target Architecture

```text
OHLCV / feature_df
   │
   ├── RegimeV2 deterministic engine
   │      ├── trend evidence
   │      ├── volatility evidence
   │      ├── mean-reversion evidence
   │      ├── breakout/break evidence
   │      ├── market context
   │      ├── policy/playbook scores
   │      └── playbook state machine
   │
   ├── Probabilistic kernel adapters
   │      ├── BCPD changepoint probability
   │      ├── Hurst persistence / anti-persistence
   │      ├── optional Hilbert cycle context
   │      ├── optional old RegimeClassification descriptors
   │      └── optional trendline/market-geometry descriptors
   │
   ├── Optional external context
   │      ├── BTC.D
   │      ├── TOTAL2
   │      ├── TOTAL3
   │      ├── TOTAL3ES
   │      ├── BTC/ETH relative context
   │      └── OI/funding where available
   │
   ├── RegimeProbV1 feature frame
   │
   ├── State probability head
   │      ├── HMM / Markov state model
   │      ├── semantic state mapper
   │      └── state entropy / transition risk
   │
   ├── Edge probability heads
   │      ├── trend-following edge calibrator
   │      ├── breakout edge calibrator
   │      ├── mean-reversion edge calibrator
   │      ├── scalping edge calibrator
   │      └── countertrend edge calibrator
   │
   ├── MoE playbook router
   │      ├── soft expert weights
   │      ├── deterministic safety gates
   │      └── MTF/cross-asset adjustment
   │
   └── ProbabilisticRegimeOutput
```

---

## 5. Proposed File Layout

Create:

```text
src/libs/models/regime_prob_v1/
  __init__.py
  contracts.py
  config.py
  feature_builder.py
  orchestrator.py

  kernels/
    __init__.py
    bcpd_adapter.py
    hurst_adapter.py
    hilbert_adapter.py
    regime_classification_adapter.py
    trendline_adapter.py

  context/
    __init__.py
    external_context.py
    cross_asset_features.py
    staleness.py

  profile/
    __init__.py
    asset_tf_profile.py
    derive.py
    reports.py

  state/
    __init__.py
    hmm_state_model.py
    semantic_mapper.py
    transition_risk.py

  edge/
    __init__.py
    labels.py
    empirical_calibrator.py
    playbook_edge_models.py
    calibration_report.py

  moe/
    __init__.py
    router.py
    experts.py
    policy_overlay.py

  mtf/
    __init__.py
    align.py
    fusion.py
    conflict.py

  optimization/
    __init__.py
    params.py
    objective.py
    validation.py
    optimize.py
    batch_optimize.py
    reports.py
    threshold_sweep.py

  scripts/
    train_prob_model.py
    evaluate_prob_model.py
    report_probability_audit.py
```

Tests:

```text
tests/test_regime_prob_v1_feature_builder.py
tests/test_regime_prob_v1_bcpd_adapter.py
tests/test_regime_prob_v1_hurst_adapter.py
tests/test_regime_prob_v1_state_model.py
tests/test_regime_prob_v1_edge_labels.py
tests/test_regime_prob_v1_empirical_calibrator.py
tests/test_regime_prob_v1_moe_router.py
tests/test_regime_prob_v1_mtf_align.py
tests/test_regime_prob_v1_external_context.py
tests/test_regime_prob_v1_optimization.py
```

---

## 6. Contracts

### 6.1 Feature Builder Config

```python
@dataclass(frozen=True)
class RegimeProbFeatureFrameConfig:
    include_regime_v2_evidence: bool = True
    include_policy_scores: bool = True
    include_raw_break_features: bool = True
    include_bcpd: bool = True
    include_hurst: bool = True
    include_hilbert: bool = False
    include_regime_classification: bool = False
    include_trendlines: bool = False
    include_external_context: bool = False
    include_mtf: bool = False
```

`feature_builder.py` is point-in-time only. It must not create forward returns, labels, or any field that depends on unseen future bars.

### 6.2 Label Builder Config

```python
@dataclass(frozen=True)
class RegimeProbLabelConfig:
    horizons: tuple[int, ...] = (3, 6, 12, 24)
    fee_bps: float = 5.0
    purge_bars: int = 24
    min_support_count: int = 20
    require_directional_breakout: bool = True
```

Forward labels are built offline in `edge/labels.py` and never in the live/runtime feature-builder path.

### 6.3 Output Contract

```python
@dataclass(frozen=True)
class ProbabilisticRegimeOutput:
    timestamp: Any
    asset: str
    timeframe: str

    p_trend_state: float
    p_range_state: float
    p_chop_state: float
    p_breakout_state: float
    p_vol_shock_state: float
    p_transition_state: float

    state_entropy: float
    dominant_state: str
    dominant_state_prob: float

    p_trend_following_edge: float
    p_breakout_edge: float
    p_mean_reversion_edge: float
    p_scalping_edge: float
    p_countertrend_edge: float

    moe_weights: dict[str, float]
    recommended_playbook: str | None

    mtf_context: dict[str, Any]
    external_context: dict[str, Any]
    diagnostics: dict[str, Any]
```

Calibration quality belongs in artifacts/reports, not per-bar runtime output. Runtime may carry artifact/version references in `diagnostics`, but not dataset-level quality metrics.

### 6.4 Training Report Contract

```python
@dataclass(frozen=True)
class RegimeProbTrainingReport:
    asset: str
    timeframe: str
    profile: str
    purge_bars: int
    train_range: tuple[str, str]
    calibration_range: tuple[str, str]
    validation_range: tuple[str, str]
    oos_range: tuple[str, str]

    state_model_metrics: dict[str, Any]
    edge_model_metrics: dict[str, Any]
    calibration_metrics: dict[str, Any]
    downstream_lift: dict[str, Any]
    gates: dict[str, Any]
    rejection_reasons: tuple[str, ...]
    artifacts: dict[str, Any]
    decision: str
```

### 6.5 Asset/Timeframe Profile Contract

```python
@dataclass(frozen=True)
class AssetTimeframeProfile:
    asset: str
    timeframe: str

    liquidity_tier: str
    volatility_tier: str
    trend_persistence_tier: str
    mean_reversion_tier: str
    breakout_followthrough_tier: str
    false_breakout_tier: str

    btc_beta_tier: str
    eth_beta_tier: str
    total2_beta_tier: str
    total3_beta_tier: str

    funding_sensitivity_tier: str
    oi_sensitivity_tier: str
    recommended_profile: str
```

---

## 7. Feature Plan

### 7.1 RegimeV2 features to consume

From `RegimeEvidence`:

```text
trend_direction
trend_strength
trend_persistence
trend_confidence
volatility_percentile
volatility_state
compression_score
shock_risk
mean_reversion_score
range_quality
chop_risk
structural_break_risk
breakout_quality
false_breakout_risk
market_context_score
breadth_confirmation
liquidity_stress
confidence
uncertainty
summary_label
pre_breakout_setup_score
displacement_breakout_score
post_breakout_retest_score
```

From `RegimePolicy`:

```text
allow_trend_following
allow_breakout
allow_mean_reversion
allow_scalping
allow_countertrend
max_position_scale
stop_multiplier
target_multiplier
holding_period_prior
trend_score
breakout_score
mean_reversion_score
scalping_score
countertrend_score
breakout_setup_score
displacement_breakout_score
retest_breakout_score
no_trade_reason
reasons
```

### 7.1 Additional raw feature pass-through

Preserve selected raw RegimeV2 kernel outputs that are useful for offline labeling or directional conditioning even if they are not part of the stable `RegimeEvidence` contract.

Minimum pass-through fields for early phases:

```text
breakout_direction
range_expansion_z
volume_confirmation
row_quality_warmup_complete
row_quality_usable
```

`breakout_direction` is required for directional breakout labels. Do not fall back to absolute-move breakout labels in the default directional breakout head.

### 7.2 Old kernels to reuse via adapters

#### BCPD — high priority

Outputs:

```text
changepoint_prob
run_length
cp_entropy
cp_recent_max
cp_decay_score
transition_risk_raw
```

Use for:

- transition probability
- HMM refit trigger metadata
- no-trade / reduce-size gate
- false-breakout suppression
- MTF conflict risk

#### Hurst — medium-high priority

Outputs:

```text
hurst
hurst_trend_bias
hurst_mr_bias
hurst_stability
```

Use as supporting feature only. Do not hard-gate solely on Hurst.

#### Hilbert — optional, later

Outputs:

```text
hilbert_period
hilbert_confidence
cycle_stability
cycle_mr_bias
```

Use later for MR/scalping context. Do not include in P1 unless trivial.

#### Old RegimeClassification adapter — optional baseline

Use available outputs if already produced:

```text
hmm_p_state_*
hmm_crisis_prob
hmm_transition_prob
changepoint_prob
run_length
cp_entropy
vol_percentile
hurst
hilbert_period
hilbert_confidence
condition_scale
```

This is a baseline/bridge only, not the main model.

### 7.3 Trendline/market geometry features

Use later as optional features:

```text
structure_state
has_support
has_resistance
has_closed_channel
is_one_sided_structure
support_distance_atr
resistance_distance_atr
channel_width_atr
channel_slope
channel_quality
line_touch_count
breakout_side
breakout_distance_atr
retest_distance_atr
false_break_geometry_risk
```

High impact for breakout/MR edge probabilities.

---

## 8. External Context / Cross-Asset Data

### 8.1 Requirement

Cross-asset/index data should be optional, quality-scored, and as-of aligned.

The model must still work with asset-local OHLCV only.

### 8.2 Initial external context sources

Use existing `configs/tradingview.yaml` symbols:

```text
CRYPTOCAP:BTC.D
CRYPTOCAP:TOTAL2
CRYPTOCAP:TOTAL3
CRYPTOCAP:TOTAL3ES
```

Also use BTC/ETH OHLCV as market leaders if easily available.

### 8.3 Later external context sources

Add only after local + current TV context proves useful:

```text
USDT.D
DXY
NASDAQ / NQ
SPX
VIX
US10Y
Gold
```

### 8.4 Derivatives context

Use existing OI/funding symbols for BTC/ETH/BNB/SOL when available:

```text
oi_zscore
oi_change_zscore
funding_zscore
funding_extreme_flag
price_up_oi_up
price_up_oi_down
price_down_oi_up
```

### 8.5 Cross-asset features

Compute:

```text
asset_return_corr_btc
asset_return_corr_eth
asset_return_corr_total2
asset_return_corr_total3
asset_beta_btc
asset_beta_eth
asset_beta_total2
asset_beta_total3
relative_strength_vs_btc
relative_strength_vs_eth
relative_strength_vs_total3
btc_d_trend
btc_d_momentum
total2_trend
total3_trend
alt_market_alignment
asset_vs_total3_divergence
asset_vs_btc_divergence
asset_breakout_without_market_confirmation
market_breakout_without_asset_confirmation
```

### 8.6 Alignment rules

For every asset bar at time `t`:

```text
Use latest external/index bar where external.close_time <= t
```

Never use partial/future higher timeframe or index bars in historical evaluation.

If external data is stale:

```text
external_context_available = false
external_context_staleness_bars = N
market_alignment_score = neutral
btc_d_conflict_score = neutral
total3_confirmation = neutral
probability_quality reduced
```

No hard failure.

---

## 9. MTF Handling

### 9.1 Requirement

MTF is required eventually, but not in P1.

MTF should adjust probabilities and MoE weights, not replace lower-timeframe predictions.

### 9.2 Initial timeframe map

```text
30m execution -> 1h, 4h context
1h execution  -> 4h, 1d context
4h execution  -> 1d context
```

Avoid 1d context for short-history assets unless enough data exists.

### 9.3 MTF features

For each HTF context:

```text
htf_p_trend_state
htf_p_range_state
htf_p_chop_state
htf_p_breakout_state
htf_p_vol_shock_state
htf_p_transition_state
htf_state_entropy
htf_p_trend_edge
htf_p_breakout_edge
htf_p_mr_edge
```

Derived:

```text
mtf_trend_confirmation
mtf_breakout_confirmation
mtf_mr_confirmation
mtf_conflict_score
mtf_entropy_max
mtf_transition_max
```

### 9.4 MTF fusion rules

Examples:

```text
If LTF wants trend and HTF p_trend_state high -> boost trend expert.
If LTF wants MR and HTF p_trend_state high -> reduce MR/countertrend.
If LTF wants breakout but HTF p_vol_shock_state high -> reduce breakout.
If HTF p_transition_state high -> global risk reduction.
```

---

## 10. Optional State Probability Head

### 10.1 Purpose

This section is optional for the first milestone. Implement it only after the edge-calibration layer proves stable and incrementally useful.

Answer:

```text
P(current market state = trend/range/chop/breakout/vol_shock/transition)
```

### 10.2 Implementation

Use HMM over RegimeV2 evidence + selected kernel features.

Initial observations should include:

```text
trend_strength
trend_persistence
trend_confidence
volatility_percentile
compression_score
shock_risk
mean_reversion_score
range_quality
chop_risk
structural_break_risk
breakout_quality
false_breakout_risk
confidence
uncertainty
changepoint_prob
hurst
```

### 10.3 Outputs

```text
p_state_0..N
p_trend_state
p_range_state
p_chop_state
p_breakout_state
p_vol_shock_state
p_transition_state
state_entropy
dominant_state
dominant_state_prob
transition_matrix_self_prob
```

### 10.4 Semantic mapping

Map latent HMM states to semantic names by state-level means:

```text
high trend_strength + low chop -> trend
high range_quality/chop -> range/chop
high breakout_quality/displacement -> breakout
high shock_risk/volatility -> vol_shock
high changepoint_prob/cp_entropy -> transition
```

Store mapping metadata with model artifact.

---

## 11. Edge Probability Heads

### 11.1 Purpose

Answer:

```text
P(playbook edge after fees is positive)
```

### 11.2 Playbook heads

```text
trend_following
breakout
mean_reversion
scalping
countertrend
```

### 11.3 Horizon targets

Start with:

```text
3 bars
6 bars
12 bars
24 bars
```

Per timeframe, interpret carefully:

```text
30m h=12 -> 6h
1h h=12  -> 12h
4h h=6   -> 24h
```

### 11.4 Labels

Generic label:

```text
edge_positive_hN = forward_playbook_return_after_fees_hN > 0
```

Additional labels:

```text
edge_strong_hN = forward_playbook_return_after_fees_hN > min_edge_threshold
adverse_fail_hN = max_adverse_excursion_hN > allowed_threshold
```

Playbook-specific directional returns:

- trend-following: use `trend_direction` for side
- breakout: use raw `breakout_direction` from the underlying break features; if direction is missing/neutral, drop from directional breakout-label support instead of silently converting to absolute move
- mean-reversion: define reversion toward rolling center / band center
- scalping: short horizon absolute/conditioned micro edge
- countertrend: opposite stretched trend/range setup direction

### 11.5 Initial calibrator

Start simple:

```text
empirical bucket calibrator
or logistic regression if sklearn is available/added
```

Current repo does not explicitly declare scikit-learn in `pyproject.toml`; avoid adding new dependency unless necessary. Empirical/bin calibrator can be implemented with pandas/numpy first.

### 11.6 Calibration metrics

For each playbook/horizon:

```text
brier_score
log_loss
expected_calibration_error
bucket_count
bucket_predicted_prob
bucket_actual_rate
top_bottom_bucket_spread
support_count
oos_lift
```

---

## 12. MoE Router

### 12.1 Purpose

Select or weight playbook experts using calibrated edge probabilities first, plus optional state probabilities, RegimeV2 deterministic gates, external context, and MTF.

Experts:

```text
trend_following expert
breakout expert
mean_reversion expert
scalping expert
countertrend expert
```

### 12.2 First implementation: deterministic soft router

Do not train a complex router first.

Initial base weights:

```text
base_w_trend = p_trend_following_edge
base_w_breakout = p_breakout_edge
base_w_mr = p_mean_reversion_edge
base_w_scalping = p_scalping_edge
base_w_countertrend = p_countertrend_edge
```

Then apply:

```text
RegimeV2 allow_* gates
minimum edge probability threshold
transition risk penalty
state entropy penalty
liquidity stress penalty
shock risk penalty
MTF confirmation/conflict adjustment
external context adjustment
optional soft state prior adjustment
```

Normalize surviving weights to sum to 1.

Do not multiply deterministic policy scores and calibrated edge probabilities in V1. Current RegimeV2 policy scores already encode confidence, threshold, shock, and liquidity structure; multiplying them directly by calibrated edge probabilities would double-count the same evidence. Policy scores may still be used as threshold features, tie-breakers, or later soft priors.

### 12.3 Safety behavior

If no expert survives:

```text
recommended_playbook = None
all weights = 0
```

The probability layer must not force a playbook when deterministic RegimeV2 blocks it in early rollout.

---

## 13. Hyperparameter Strategy

Use five categories.

### 13.1 Fixed safety constants

Rare/manual changes only:

```text
purge_bars
minimum train bars
minimum OOS bars
minimum support count
max staleness
max missing ratio
probability clipping range
```

### 13.2 Timeframe-scaled params

Derived from timeframe:

```text
rolling windows
BCPD windows
Hurst lookback
HMM retrain window
calibration window
```

Follow the style in `regime_v2/config.py`.

### 13.3 Asset/timeframe behavior profile

Compute offline weekly/monthly:

```text
volatility tier
trend persistence tier
MR tier
breakout follow-through tier
false breakout tier
BTC/ETH/TOTAL3 beta tier
funding sensitivity tier
OI sensitivity tier
```

Use this to choose default profile before optimization.

### 13.4 Runtime-adaptive state variables

Calculated every bar, never optimized live:

```text
ATR
volatility percentile
liquidity stress
spread stress
shock risk
BCPD changepoint probability
state entropy
external context staleness
current beta drift
```

### 13.5 Optimizable params

Optimized offline:

```text
min_edge_probability
max_state_entropy
max_transition_probability
MTF confirmation boost
MTF conflict penalty
MoE expert temperature
BCPD hazard lambda
BCPD signal threshold
HMM n_states
feature set selection
calibration bin count
```

---

## 14. Optimization Plan

### 14.1 Do not optimize everything together

Avoid one giant search space.

Use profiles.

### 14.2 Profiles

Default execution order for optimization work:

```text
edge_calibration
moe_router
mtf_overlay / external_context
state_core (optional later)
```

#### `state_core`

Tune state model only:

```text
hmm_n_states
hmm_covariance_type
hmm_retrain_window
feature_set
state_entropy_threshold
semantic_mapping_method
```

Objective:

```text
state persistence
state entropy usefulness
downstream return separation by state
transition stability
OOS state-feature lift
```

#### `transition`

Tune BCPD/transition features:

```text
bcpd_hazard_lambda
bcpd_hazard_shape
bcpd_signal_threshold
cp_decay_halflife
transition_suppression_threshold
```

Objective:

```text
avoid bad windows
reduce false breakouts
reduce adverse excursion
preserve support count
```

#### `edge_calibration`

Tune edge heads/calibration:

```text
playbook target kind
horizon
fee_bps
calibration method
probability bin count
min_support_count
```

Objective:

```text
Brier score
log loss
ECE
top-bottom bucket spread
OOS lift
default-vs-probability lift
```

#### `moe_router`

Tune router thresholds:

```text
min_edge_probability
min_state_probability
max_state_entropy
max_transition_probability
expert_temperature
confirmation_boost
conflict_penalty
```

Objective:

```text
downstream lift
OOS degradation
support count
turnover
drawdown/tail penalty
```

#### `mtf_overlay`

Tune MTF adjustment:

```text
higher_tf_weight
confirmation_boost
conflict_penalty
transition_max_penalty
entropy_max_penalty
```

Objective:

```text
improved OOS edge after MTF adjustment
reduced false positives
stable rolling windows
```

#### `external_context`

Tune cross-asset/index context weights:

```text
btc_d_conflict_weight
total3_confirmation_weight
btc_beta_weight
eth_beta_weight
context_staleness_penalty
```

Objective:

```text
OOS lift improvement vs local-only
calibration not worse
support remains sufficient
rolling stability preserved
```

### 14.3 Optimizer choice

Initial:

```text
TPE single-objective
+ threshold sweep
```

Later:

```text
NSGA-II for Pareto research
```

Use NSGA-II only when balancing competing objectives such as:

```text
maximize OOS lift
minimize tail loss
minimize turnover
minimize calibration error
maximize support count
```

### 14.4 Promotion gates

A candidate cannot be promoted unless:

```text
all splits use purge gaps at every boundary
OOS calibrated probability beats default RegimeV2 gate
OOS downstream lift > 0
OOS Brier/logloss not worse than baseline
positive bucket separation exists
support count above minimum
rolling windows pass stability floor
MTF/context does not degrade OOS
no extreme playbook turnover
```

---

## 15. Data Flow

### 15.1 Offline training flow

```text
1. Load asset OHLCV.
2. Optionally load TV/index/external context.
3. Asof-align external context with completed bars only.
4. Run RegimeV2Orchestrator.analyze_series().
5. Build point-in-time RegimeProb feature frame.
6. Preserve raw directional/context columns needed for labeling, especially breakout_direction.
7. Add BCPD/Hurst kernel features.
8. Add optional trendline/context/MTF features.
9. Build forward labels in a separate offline label-builder step.
10. Drop rows without a complete forward horizon for the requested label.
11. Split chronologically with purge gaps at every boundary:
    train | purge | calibration | purge | validation | purge | OOS
12. Fit edge models on train.
13. Fit calibrators on calibration split only.
14. Tune thresholds/router on validation using rolling-window stability metrics.
15. Audit on untouched OOS.
16. Optional later: fit state probability model only after edge-first stack proves incremental value.
17. Write JSON + Markdown report.
18. Save model artifact only if promotion gates pass.
```

### 15.2 Live/shadow inference flow

```text
1. Asset bar closes.
2. Load rolling OHLCV window.
3. Load latest optional TV/index context snapshot.
4. Validate context freshness.
5. Run RegimeV2 latest/analyze_series path.
6. Build current point-in-time RegimeProb feature row only.
7. Optionally compute state probabilities if enabled.
8. Compute calibrated edge probabilities.
9. Apply MTF/context adjustment if enabled.
10. Apply MoE router.
11. Emit ProbabilisticRegimeOutput.
12. Log shadow decision and later outcome.
13. Downstream uses output only if mode allows.
```

---

## 16. Runtime Modes

Support modes:

```text
disabled
shadow
paper_filter_only
paper_sizing
live_filter_only
live_sizing
```

Initial default:

```text
shadow
```

Early rollout rule:

```text
RegimeProbV1 can filter/reduce/annotate only.
It cannot force trades when RegimeV2 says no-trade.
```

Fallback:

```text
If RegimeProbV1 artifact missing/stale/fails -> use RegimeV2 deterministic policy.
```

---

## 17. Configuration Sketch

Add later to config after initial module exists:

```yaml
regime_prob_v1:
  enabled: false
  mode: shadow

  external_context:
    enabled: true
    required: false
    staleness_ttl_bars: 2
    indices:
      - CRYPTOCAP:BTC.D
      - CRYPTOCAP:TOTAL2
      - CRYPTOCAP:TOTAL3
      - CRYPTOCAP:TOTAL3ES

  feature_builder:
    include_bcpd: true
    include_hurst: true
    include_hilbert: false
    include_regime_classification: false
    include_trendlines: false
    include_external_context: false
    include_mtf: false

  profile:
    source: derived
    refresh_days: 7
    fallback_profile: balanced

  runtime_adaptation:
    use_vol_percentile: true
    use_liquidity_stress: true
    use_state_entropy: true
    use_changepoint_prob: true
    use_context_staleness: true

  optimization:
    cadence: weekly
    sampler: tpe
    nsga_enabled: false
    min_oos_windows: 3
    min_support_count: 30
    require_default_vs_tuned_lift: true

  mtf:
    enabled: false
    mode: asof_completed_bars
    map:
      30m: [1h, 4h]
      1h: [4h, 1d]
      4h: [1d]

  deployment:
    can_force_trade: false
    can_only_filter_or_size: true
    fallback_to_regime_v2: true
```

---

## 18. Phase-by-Phase Implementation

## Phase P0 — Planning file only

Deliverable:

```text
plans/architect-to-coder-regime-prob-v1.md
```

No runtime changes.

---

## Phase P1 — Core contracts and feature builder

Add:

```text
src/libs/models/regime_prob_v1/__init__.py
src/libs/models/regime_prob_v1/contracts.py
src/libs/models/regime_prob_v1/config.py
src/libs/models/regime_prob_v1/feature_builder.py
```

Feature builder responsibilities:

```text
call RegimeV2Orchestrator.analyze_series()
flatten evidence/policy fields
preserve timestamps/index
add row_quality/warmup flags
preserve breakout_direction and other required raw pass-through columns
avoid future leakage in features
do not build forward returns or labels
```

Tests:

```text
tests/test_regime_prob_v1_feature_builder.py
```

Validation:

```bash
.venv/bin/python -m pytest tests/test_regime_prob_v1_feature_builder.py -q
```

---

## Phase P2 — BCPD and Hurst adapters

Add:

```text
src/libs/models/regime_prob_v1/kernels/__init__.py
src/libs/models/regime_prob_v1/kernels/bcpd_adapter.py
src/libs/models/regime_prob_v1/kernels/hurst_adapter.py
```

Reuse old kernels where possible.

Responsibilities:

```text
align output length to input frame
return neutral values on insufficient data
avoid future leakage
surface diagnostics
```

Tests:

```text
tests/test_regime_prob_v1_bcpd_adapter.py
tests/test_regime_prob_v1_hurst_adapter.py
```

---

## Phase P3 — Optional state probability head

Add:

```text
src/libs/models/regime_prob_v1/state/__init__.py
src/libs/models/regime_prob_v1/state/hmm_state_model.py
src/libs/models/regime_prob_v1/state/semantic_mapper.py
src/libs/models/regime_prob_v1/state/transition_risk.py
```

Responsibilities:

```text
run only after edge-calibration stack proves useful
fit HMM on train split only
predict state probabilities for validation/OOS
map latent states to semantic labels
compute state entropy
compute transition risk
return artifact metadata
```

Tests:

```text
tests/test_regime_prob_v1_state_model.py
```

---

## Phase P4 — Edge labels and empirical calibrator

Add:

```text
src/libs/models/regime_prob_v1/edge/__init__.py
src/libs/models/regime_prob_v1/edge/labels.py
src/libs/models/regime_prob_v1/edge/empirical_calibrator.py
src/libs/models/regime_prob_v1/edge/calibration_report.py
```

Start with empirical/bin calibrator to avoid new dependencies.

Responsibilities:

```text
create forward outcome labels in a separate offline path
enforce purge-aware train/calibration/validation/OOS boundaries
preserve directional breakout-label support from breakout_direction
fit probability bins on calibration split
evaluate Brier/logloss/ECE/top-bottom spread
support playbook + horizon combinations
```

Tests:

```text
tests/test_regime_prob_v1_edge_labels.py
tests/test_regime_prob_v1_empirical_calibrator.py
```

---

## Phase P5 — MoE router

Add:

```text
src/libs/models/regime_prob_v1/moe/__init__.py
src/libs/models/regime_prob_v1/moe/router.py
src/libs/models/regime_prob_v1/moe/experts.py
src/libs/models/regime_prob_v1/moe/policy_overlay.py
```

Responsibilities:

```text
consume edge probabilities first
apply safety gates
optionally apply state priors as soft penalties/boosts later
produce normalized expert weights
produce recommended_playbook
never force trade in initial modes
```

Tests:

```text
tests/test_regime_prob_v1_moe_router.py
```

---

## Phase P6 — External context feature builder

Add:

```text
src/libs/models/regime_prob_v1/context/__init__.py
src/libs/models/regime_prob_v1/context/external_context.py
src/libs/models/regime_prob_v1/context/cross_asset_features.py
src/libs/models/regime_prob_v1/context/staleness.py
```

Responsibilities:

```text
asof-align completed external bars
compute BTC.D/TOTAL2/TOTAL3 context features
compute beta/correlation/relative strength
handle stale/missing context neutrally
```

Tests:

```text
tests/test_regime_prob_v1_external_context.py
```

---

## Phase P7 — MTF alignment/fusion

Add:

```text
src/libs/models/regime_prob_v1/mtf/__init__.py
src/libs/models/regime_prob_v1/mtf/align.py
src/libs/models/regime_prob_v1/mtf/fusion.py
src/libs/models/regime_prob_v1/mtf/conflict.py
```

Responsibilities:

```text
asof-align completed HTF probability bars
compute MTF confirmation/conflict
adjust MoE weights/probability confidence
avoid future HTF leakage
```

Tests:

```text
tests/test_regime_prob_v1_mtf_align.py
```

---

## Phase P8 — Asset/timeframe profile

Add:

```text
src/libs/models/regime_prob_v1/profile/__init__.py
src/libs/models/regime_prob_v1/profile/asset_tf_profile.py
src/libs/models/regime_prob_v1/profile/derive.py
src/libs/models/regime_prob_v1/profile/reports.py
```

Responsibilities:

```text
compute volatility/trend/MR/breakout/beta/funding/OI tiers
recommend default profile
produce JSON/Markdown profile report
```

---

## Phase P9 — Optimization scaffold

Add:

```text
src/libs/models/regime_prob_v1/optimization/__init__.py
src/libs/models/regime_prob_v1/optimization/params.py
src/libs/models/regime_prob_v1/optimization/objective.py
src/libs/models/regime_prob_v1/optimization/validation.py
src/libs/models/regime_prob_v1/optimization/optimize.py
src/libs/models/regime_prob_v1/optimization/batch_optimize.py
src/libs/models/regime_prob_v1/optimization/reports.py
src/libs/models/regime_prob_v1/optimization/threshold_sweep.py
```

Profiles:

```text
state_core
transition
edge_calibration
moe_router
mtf_overlay
external_context
full_shadow_only
```

Start with TPE and local threshold sweep. Add NSGA-II only later.

Tests:

```text
tests/test_regime_prob_v1_optimization.py
```

---

## Phase P10 — Scripts and reports

Add:

```text
src/libs/models/regime_prob_v1/scripts/train_prob_model.py
src/libs/models/regime_prob_v1/scripts/evaluate_prob_model.py
src/libs/models/regime_prob_v1/scripts/report_probability_audit.py
```

Reports:

```text
research/regime_prob_v1_state_report.json/md
research/regime_prob_v1_calibration_report.json/md
research/regime_prob_v1_moe_router_report.json/md
research/regime_prob_v1_mtf_context_report.json/md
research/regime_prob_v1_shadow_outcome_report.json/md
```

---

## 19. Initial Implementation Order Recommendation

Do this first:

```text
P1 -> P2 -> P4 -> P5
```

Meaning:

```text
1. Build RegimeProbV1 feature frame from RegimeV2.
2. Add BCPD + Hurst adapters.
3. Add leakage-safe edge labels and empirical calibration report.
4. Add edge-first router with deterministic safety gates.
```

Do not start with:

```text
HMM state head
MTF
TV context
NSGA-II
runtime integration
```

Those come after the local edge-probability layer proves useful. If a state head is added later, it must prove incremental OOS value beyond the edge-first stack.

---

## 20. Validation Checklist

Each phase must include tests.

Minimum validation after the first implementation batch (P1, P2, P4, P5):

```bash
.venv/bin/python -m pytest \
  tests/test_regime_prob_v1_feature_builder.py \
  tests/test_regime_prob_v1_bcpd_adapter.py \
  tests/test_regime_prob_v1_hurst_adapter.py \
  tests/test_regime_prob_v1_edge_labels.py \
  tests/test_regime_prob_v1_empirical_calibrator.py \
  tests/test_regime_prob_v1_moe_router.py \
  -q
```

If P3 is implemented later, add:

```bash
.venv/bin/python -m pytest \
  tests/test_regime_prob_v1_state_model.py \
  -q
```

Regression tests for existing optimizer should still pass:

```bash
.venv/bin/python -m pytest \
  tests/test_regime_v2_optimizer.py \
  tests/test_regime_v2_optimization_params.py \
  -q
```

No Docker build required.

---

## 21. Blast Radius

### Low blast radius

New package only:

```text
src/libs/models/regime_prob_v1/
```

New tests only:

```text
tests/test_regime_prob_v1_*.py
```

### Medium blast radius later

Only when integrating into runtime selection/risk:

```text
configs/models.yaml
configs/selection.yaml
src/apps/strategy_app/
src/apps/signal_app/
src/libs/selection/
src/libs/risk/
```

Do not touch runtime pipeline until shadow reports pass.

---

## 22. Expected First Milestone Output

After the first implementation batch (P1, P2, P4, P5), Codex should produce a report like:

```text
RegimeProbV1 local probability audit
Asset: ETHUSDT
Timeframe: 4h
Rows: N
Trend edge Brier: A
Breakout edge Brier: B
MR edge Brier: C
Top-bottom bucket spread: D
OOS probability lift vs RegimeV2 deterministic: E
Router support / turnover: F
Decision: continue / reject / needs more data
```

Promotion is not allowed yet. This is research/shadow only.

---

## 23. Critical Safety Rules

1. All feature generation must be point-in-time.
2. Forward returns/labels must never leak into features.
3. Train/calibration/validation/OOS boundaries must use purge gaps.
4. External/index/HTF data must use completed bars only.
5. Missing external data must degrade gracefully.
6. Calibrators must be fit on calibration split, not OOS.
7. OOS/test must remain untouched for final audit.
8. Runtime must fall back to RegimeV2 if probability layer fails.
9. Early RegimeProbV1 can filter/size only; it cannot force trades.
10. Optimization must require default-vs-probability lift.
11. Any promoted config must include report/artifact metadata.

---

## 24. Summary for Codex Agent

Implement `RegimeProbV1` as a new additive module.

Start with local-only probability:

```text
RegimeV2 evidence + breakout_direction + BCPD + Hurst -> empirical edge calibration report -> edge-first router
```

Then add:

```text
optional state head -> external TV context -> MTF -> optimization -> shadow runtime
```

Do not rebuild the old regime model. Reuse old kernels/adapters where valuable, but make the new layer calibrated to forward playbook outcomes.
