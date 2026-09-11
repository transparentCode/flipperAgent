# RegimeV2 Completion Plan

This plan tracks the remaining work needed to move RegimeV2 from deterministic offline engine to a safe shadow-mode candidate.

## Current State

RegimeV2 is implemented as a standalone deterministic evidence and policy engine under `src/libs/models/regime_v2/`.

Implemented:

- OHLCV data-quality validation.
- Trend, volatility, mean-reversion, structural-break, breakout, and market-context feature kernels.
- Rule-fusion layer that emits normalized evidence.
- Playbook policy layer for trend, breakout, mean-reversion, scalping, countertrend, sizing, stop, target, and holding-period priors.
- Feature-producer adapter for signal-app enrichment.
- Disabled-by-default selection overlay for RegimeV2 trend gating.
- Offline comparison, downstream ablation, trend-family ablation, candidate export, rolling-window validation, and Binance-native scripts.
- Known-issues backlog in `KNOWN_ISSUES.md`.

Current guardrail:

```yaml
RegimeV2:
  enabled: false
```

and:

```yaml
regime_v2_trend_gate:
  enabled: false
```

## Phase 4 — Objective Downstream Proof

Goal: prove that RegimeV2 improves downstream selection before any shadow/live promotion.

### 4A. Matrix-level validation gate — implemented

Added:

- `evaluation/phase4_matrix.py`
- `scripts/phase4_overlay_matrix_binance.py`

Purpose:

- Run rolling-window overlay validation across assets, timeframes, horizons, and fee assumptions.
- Aggregate combo-level pass/fail decisions.
- Emit one conservative decision:
  - `PROMOTE_TO_SHADOW_CANDIDATE`
  - `HOLD_FOR_MORE_EVIDENCE`

Recommended first command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.phase4_overlay_matrix_binance \
  --symbol BTCUSDT --symbol ETHUSDT --symbol SOLUSDT --symbol BNBUSDT \
  --timeframe 1h --timeframe 4h \
  --horizon-bars 6 --horizon-bars 12 \
  --fee-bps 2 --fee-bps 5 \
  --limit 1000 \
  --output-json research/regime_v2_phase4_overlay_matrix.json \
  --output-md research/regime_v2_phase4_overlay_matrix.md
```

Promotion criteria defaults:

- At least 2 valid rolling windows per fee.
- Positive-gated-window rate >= 55%.
- Mean gated lift >= 0 after fees.
- All tested fees must pass for a combo.
- At least 2 combos must pass.
- Overall combo pass rate >= 60%.

### 4B. Candidate-family expansion — in progress

Current built-in candidates:

- Momentum
- TrendFollowing
- PriceAction
- Trendline dataframe exports
- RegimePullbackScorer
- SqueezeBreakout

Implemented in this step:

- Extended `candidate_export.py` so Phase 4 scripts can request `Trendline`, `RegimePullbackScorer`, or `SqueezeBreakout` via `--model`.
- Added lightweight offline indicators needed by pullback/squeeze families while preserving precomputed research/live feature columns when supplied.
- Added playbook-aware offline selection overlay support for trend, breakout, and mean-reversion candidate families.
- Added playbook-aware failure diagnostics so non-trend families are not misclassified as trend failures.
- Added tests for Phase 4B candidate-family export, playbook-aware overlay, and playbook-aware diagnostics.
- Added offline matrix CLI knobs for trend/breakout/mean-reversion score floors while keeping defaults unchanged.

Latest full-candidate matrix run:

- Output: `research/regime_v2_phase4b_overlay_matrix.json` and `research/regime_v2_phase4b_overlay_matrix.md`.
- Candidate set: Momentum, TrendFollowing, PriceAction, RegimePullbackScorer, SqueezeBreakout.
- Assets/timeframes/horizons: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT × 1h/4h × 6/12 bars.
- Fees: 2 bps and 5 bps.
- Decision: `HOLD_FOR_MORE_EVIDENCE`.
- Passed combos: 9/16.
- Combo pass rate: 56.25%, just below the 60% conservative promotion threshold.
- Top diagnostic: `no_active_playbook`, meaning many losing rows had no RegimeV2 playbook strong enough to bless the selected candidate.

Latest candidate-subset matrix run:

- Output: `research/regime_v2_phase4b_no_priceaction_overlay_matrix.json` and `research/regime_v2_phase4b_no_priceaction_overlay_matrix.md`.
- Candidate set: Momentum, TrendFollowing, RegimePullbackScorer, SqueezeBreakout.
- Decision: `PROMOTE_TO_SHADOW_CANDIDATE`.
- Passed combos: 10/16.
- Combo pass rate: 62.5%, above the 60% conservative promotion threshold.
- Interpretation: RegimeV2 playbook gating is viable on the trend + pullback + squeeze subset, while `PriceAction` currently behaves like a noisy always-on baseline in this offline matrix and should be validated separately before inclusion in Phase 5.

Calibration notes:

- Lowering overlay score floors to trend=0.20, breakout=0.18, mean_reversion=0.18 degraded the full-candidate matrix to 8/16, so the issue is not simply overly strict floors.
- `top_k=2` kept the full-candidate matrix at 9/16 and increased overlay churn, so widening selection alone is not sufficient.

Still to evaluate:

- Real trendline exports from the trendline module once its canonical candidate frame is selected.
- Regression/pullback candidates on real feature-engineered frames.
- Squeeze-breakout candidates after breakout component validation.

Recommended Phase 4B command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.phase4_overlay_matrix_binance \
  --symbol BTCUSDT --symbol ETHUSDT --symbol SOLUSDT --symbol BNBUSDT \
  --timeframe 1h --timeframe 4h \
  --horizon-bars 6 --horizon-bars 12 \
  --fee-bps 2 --fee-bps 5 \
  --model Momentum --model TrendFollowing --model PriceAction \
  --model RegimePullbackScorer --model SqueezeBreakout \
  --limit 1000 \
  --output-json research/regime_v2_phase4b_overlay_matrix.json \
  --output-md research/regime_v2_phase4b_overlay_matrix.md
```

Recommended candidate-subset command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.phase4_overlay_matrix_binance \
  --symbol BTCUSDT --symbol ETHUSDT --symbol SOLUSDT --symbol BNBUSDT \
  --timeframe 1h --timeframe 4h \
  --horizon-bars 6 --horizon-bars 12 \
  --fee-bps 2 --fee-bps 5 \
  --model Momentum --model TrendFollowing \
  --model RegimePullbackScorer --model SqueezeBreakout \
  --limit 1000 \
  --output-json research/regime_v2_phase4b_no_priceaction_overlay_matrix.json \
  --output-md research/regime_v2_phase4b_no_priceaction_overlay_matrix.md
```

Acceptance:

- RegimeV2 must improve at least one real downstream candidate family after fees/slippage.
- Improvement must not be concentrated in only one symbol/timeframe.

### 4C. Failure-mode diagnostics — implemented

Added:

- `evaluation/failure_diagnostics.py`
- Diagnostic context columns in offline selected-candidate replay frames.
- Per-window diagnostics in `run_overlay_window_validation` metrics.
- Fee-level and matrix-level diagnostic aggregation.

Diagnostics currently classify:

- Trend direction wrong.
- Trend score too low.
- Breakout score too low.
- Mean-reversion score too low.
- No active playbook.
- Confidence too low.
- High uncertainty.
- Chop leakage.
- False-breakout risk.
- Shock risk.
- Overlay changed pick.
- Conflict-penalty selected.
- Aligned pick lost.
- Missing gated pick.

Next refinement:

- Add slippage sensitivity once execution/slippage assumptions are standardized.

## Phase 5 — Shadow Mode

Only start after Phase 4 matrix says `PROMOTE_TO_SHADOW_CANDIDATE`.

### 5A. Validated shadow subset wiring — implemented

Implemented safety scaffolding:

- Live trading decisions remain unchanged when `regime_v2_trend_gate.enabled: false`.
- `regime_v2_trend_gate.shadow_enabled` can preview the gated selection path without filtering live candidates.
- Shadow mode now defaults to the validated Phase 5A subset when no override is supplied:
  - Momentum
  - MomentumV2
  - TrendFollowing
  - TrendFollowingModel
  - RegimePullbackScorer
  - SqueezeBreakout
- `PriceAction` is excluded from the default shadow subset and remains a separate follow-up family.
- Live `target_models` remains trend-only unless explicitly changed.
- Shadow payload is attached to selected-candidate metadata as `regime_v2_trend_gate_shadow` and includes:
  - baseline selected model
  - RegimeV2-gated shadow selected model
  - selection-score delta
  - conflict/alignment reason
  - gate active/reason diagnostics
  - active playbooks
  - candidate-to-playbook mapping
  - trend/breakout/mean-reversion scores
  - confidence and uncertainty
  - shadow subset name and target models
- Optional `shadow_log_enabled` logs the top-pick comparison; it remains disabled by default.

Validation:

- `tests/test_selection_layer.py`: 26 passed.
- `tests/test_regime_v2.py` + `tests/test_regime_v2_phase4_matrix.py`: 45 passed.
- `tests/signals/test_regime_wiring.py`: 13 passed.

### 5B. Durable shadow decision logging — implemented

Implemented:

- Added disabled-by-default JSONL persistence for RegimeV2 shadow decisions.
- Config keys:
  - `shadow_persist_enabled: false`
  - `shadow_persist_path: logs/regime_v2_shadow_decisions.jsonl`
- Each JSONL row includes:
  - baseline and shadow selected model
  - selection changed flag and reason
  - active playbooks
  - candidate playbook mapping
  - RegimeV2 scores/confidence/uncertainty
  - candidate counts and shadow subset metadata
  - full shadow payload for replay/debugging
- Persistence failures are warning-only and cannot break live selection.

Validation:

- `tests/test_selection_layer.py`: 29 passed.

### 5C. Shadow replay/report tooling — implemented

Implemented:

- Added offline report engine for `logs/regime_v2_shadow_decisions.jsonl`.
- Added CLI wrapper:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.report_shadow_decisions \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --output-json research/regime_v2_phase5_shadow_report.json \
  --output-md research/regime_v2_phase5_shadow_report.md
```

The report summarizes:

- selection-changed count/rate
- gate-active count/rate
- missing RegimeV2 payloads
- inactive playbook policy rows
- no-active-playbook rows
- active playbook distribution
- baseline-vs-shadow model-pair summary
- changed-pick groups
- mean edge delta, confidence, uncertainty, and playbook scores

Validation:

- `tests/test_regime_v2_shadow_report.py`: 5 passed.
- `tests/test_selection_layer.py` + `tests/test_regime_v2_shadow_report.py`: 34 passed.

### 5D. Controlled shadow rollout — implemented

Implemented in `configs/selection.yaml`:

- Live gate remains disabled everywhere with `enabled: false`.
- Global/default shadow collection remains disabled.
- Shadow collection and JSONL persistence are enabled only for:
  - `BTCUSDT` `4h`
  - `ETHUSDT` `4h`
  - `SOLUSDT` `4h`
  - `BNBUSDT` `1h`
- Asset-level `default` timeframes remain disabled so non-rollout timeframes do not accidentally inherit shadow collection.
- Phase 5A validated subset remains active for shadow target models.
- `PriceAction` remains excluded from the default shadow subset.

Validation:

- `tests/test_selection_layer.py`: 31 passed.

Offline collection fallback:

Because the live signal/strategy stream may be unavailable while the pipeline is under repair, Phase 5D can collect compatible shadow logs directly from Binance candles:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.collect_shadow_binance \
  --limit 420 \
  --warmup-bars 160 \
  --max-records-per-pair 80 \
  --reset-log \
  --output-json research/regime_v2_shadow_collect_summary.json \
  --report-json research/regime_v2_phase5_shadow_report.json \
  --report-md research/regime_v2_phase5_shadow_report.md
```

This uses the same `SelectionLayer` shadow persistence as runtime and writes the same `logs/regime_v2_shadow_decisions.jsonl` schema.

Latest bounded offline collection:

- Pairs: `BTCUSDT 4h`, `ETHUSDT 4h`, `SOLUSDT 4h`, `BNBUSDT 1h`.
- OHLCV rows per pair: 420.
- Attempted shadow records: 320.
- JSONL rows written: 320.
- Missing RegimeV2 payloads: 0.
- Gate-active rows: 13.
- No-active-playbook rows: 307.

Phase 6A-lite report split — implemented:

- Added gate-active changed count/rate.
- Added gate-inactive changed count/rate.
- Added inactive-policy changed count/rate.
- Added shadow-empty changed count.
- Added subset-only changed count.
- Added PriceAction subset-exclusion count.
- Added separate changed-pick groups for gate-active, inactive-policy, and subset-only rows.

Latest report split on the bounded offline collection:

- Total rows: 320.
- Selection changed: 146.
- Gate-active rows: 13.
- Gate-active changed rows: 6.
- Gate-inactive rows: 307.
- Gate-inactive changed rows: 140.
- Subset-only changed rows: 145.
- PriceAction subset exclusions: 145.

### 6A. Shadow outcome labeling — implemented

Implemented:

- Added selected direction/edge/conviction fields to shadow payloads and durable JSONL records.
- Added outcome labeling module: `libs.selection.regime_v2_shadow_outcomes`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.label_shadow_outcomes_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --limit 700 \
  --horizon-bars 12 \
  --fee-bps 5 \
  --output-jsonl research/regime_v2_shadow_outcomes.jsonl \
  --report-json research/regime_v2_shadow_outcome_report.json \
  --report-md research/regime_v2_shadow_outcome_report.md
```

Output labels:

- `avoided_loss`
- `missed_win`
- `improved_pick`
- `worsened_pick`
- `neutral_changed`
- `unchanged`
- `unlabeled`

Latest bounded offline outcome report:

- Shadow decisions: 320.
- Labeled outcomes: 320.
- Unlabeled outcomes: 0.
- Changed decisions: 146.
- Gate-active rows: 13.
- Gate-active changed rows: 6.
- Subset-only changed rows: 145.
- Overall outcome labels:
  - `avoided_loss`: 89.
  - `missed_win`: 56.
  - `neutral_changed`: 1.
  - `unchanged`: 174.
- Average shadow minus baseline: `0.0024080656229428727`.
- Average changed shadow minus baseline: `0.005277952050285748`.
- Average gate-active changed shadow minus baseline: `0.004043099698045685`.

Validation:

- `tests/test_regime_v2_shadow_outcomes.py`: 9 passed.
- Outcome + collector + report + selection tests: 51 passed.

### 6B. Multi-horizon / fee outcome matrix — implemented

Implemented:

- Added matrix module: `libs.selection.regime_v2_shadow_outcome_matrix`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.shadow_outcome_matrix_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --limit 800 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --output-json research/regime_v2_shadow_outcome_matrix.json \
  --output-md research/regime_v2_shadow_outcome_matrix.md
```

Matrix dimensions:

- Horizons: `3`, `6`, `12`, `24` bars.
- Fee/slippage assumptions: `2`, `5`, `10` bps.
- Cells: 12.
- Rows per cell: 320.
- Unlabeled rows per cell: 0.

Latest bounded matrix findings:

- Changed rows are positive in all cells.
- Worst changed cell: horizon `3`, fee `2` bps, average shadow-minus-baseline `0.002156932810121709`.
- Best changed cell: horizon `24`, fee `10` bps, average shadow-minus-baseline `0.011279230561220283`.
- Subset-only changed rows are also positive in all cells.
- Gate-active changed rows are mixed and too small for promotion:
  - Count: 6 per cell.
  - Best: horizon `12`, fee `10` bps, average shadow-minus-baseline `0.004459766364712352`.
  - Worst: horizon `24`, fee `2` bps, average shadow-minus-baseline `-0.008328735448087939`.

Validation:

- `tests/test_regime_v2_shadow_outcome_matrix.py`: 5 passed.
- Matrix + outcome + collector + report + selection tests: 56 passed.

Still required:

- Treat this as offline evidence only until live feature pipeline has OHLCV history again.
- Increase sample size before promotion.
- Improve playbook activation rate; current bounded sample has only 13 active rows out of 320 and only 6 active changed rows.
- Separate PriceAction into its own playbook/matrix; current lift is dominated by subset-only PriceAction removal.
- Run runtime shadow collection once the live feature pipeline has OHLCV history again.
- Run Phase 5C reports periodically over `logs/regime_v2_shadow_decisions.jsonl`.
- Add optional richer dashboards/CSV views if JSON/Markdown summaries are not enough.
- Keep `PriceAction` out of the default Phase 5A subset until it has a separate playbook or its own matrix evidence.

Do not enable `RegimeV2.enabled` globally during this phase.

### 6C. Activation diagnostics — implemented

Implemented:

- Added policy context to shadow payloads and durable JSONL records:
  - `allow_trend_following`
  - `allow_breakout`
  - `allow_mean_reversion`
  - `min_trend_score`
  - `min_breakout_score`
  - `min_mean_reversion_score`
  - `min_confidence`
- Added diagnostics module: `libs.selection.regime_v2_activation_diagnostics`.
- Added CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.diagnose_shadow_activation \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --output-json research/regime_v2_activation_diagnostics.json \
  --output-md research/regime_v2_activation_diagnostics.md
```

Latest bounded activation diagnostics:

- Rows: 320.
- Gate active: 14 (`0.04375`).
- Gate-active changed: 5.
- Inactive policy rows: 306.
- Missing policy context: 0.
- Target candidate absent: 143 (`0.446875`).
- Active playbooks:
  - `trend`: 13.
  - `breakout`: 5.
  - `mean_reversion`: 0.
  - `none`: 306.

Per asset/timeframe activation:

- `BNBUSDT|1h`: 0 / 80 active.
- `BTCUSDT|4h`: 4 / 80 active.
- `ETHUSDT|4h`: 4 / 80 active.
- `SOLUSDT|4h`: 6 / 80 active.

Playbook findings:

- `trend`: allow+score pass 13 / 320; p95 score `0.1821`, below default floor `0.24`.
- `breakout`: allow+score pass 5 / 320; p95 score `0.0853`, below default floor `0.24`.
- `mean_reversion`: allow+score pass 0 / 320; allow true 0 / 320; p95 score `0.0326`.
- Lowering floors alone does not materially increase policy-active rows because the `allow_*` flags are already false on most rows.
- Score-only relaxed floor at `0.18` would raise potential active rows to 21 / 320, but policy-gated potential remains only 14 / 320.

Refreshed Phase 6B matrix after regenerating the log:

- Changed rows remain positive in all 12 cells.
- Worst changed cell: horizon `3`, fee `2` bps, average shadow-minus-baseline `0.002069487281790716`.
- Best changed cell: horizon `24`, fee `10` bps, average shadow-minus-baseline `0.011453480058756979`.
- Gate-active changed rows remain too small and mixed:
  - Count: 5 per cell.
  - Best: horizon `12`, fee `10` bps, average shadow-minus-baseline `0.000450533474413584`.
  - Worst: horizon `24`, fee `2` bps, average shadow-minus-baseline `-0.012346110787991164`.

Validation:

- `tests/test_regime_v2_activation_diagnostics.py`: 5 passed.

### 6D. Playbook threshold calibration — implemented

Implemented:

- Added calibration module: `libs.selection.regime_v2_playbook_calibration`.
- Added CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.calibrate_playbook_thresholds \
  --outcomes research/regime_v2_shadow_outcomes.jsonl \
  --floor 0.10 --floor 0.14 --floor 0.18 --floor 0.20 --floor 0.22 --floor 0.24 \
  --output-json research/regime_v2_playbook_calibration.json \
  --output-md research/regime_v2_playbook_calibration.md
```

Latest bounded calibration findings:

- Rows: 320.
- Labeled: 320.
- Best policy-gated cell:
  - playbook: `trend`.
  - floor: `0.10`.
  - count: 13.
  - average shadow-minus-baseline: `0.00001943595169753235`.
  - positive lift rate: `0.07692307692307693`.
- Best score-only cell:
  - playbook: `mean_reversion`.
  - floor: `0.20`.
  - count: 1.
  - average shadow-minus-baseline: `0.03360617413240348`.
  - positive lift rate: `1.0`.
- Best allow-blocked score-pass cell:
  - playbook: `mean_reversion`.
  - floor: `0.20`.
  - count: 1.
  - average shadow-minus-baseline: `0.03360617413240348`.
  - positive lift rate: `1.0`.

PriceAction subset-removal evidence:

- Count: 143.
- Average shadow-minus-baseline: `0.005570930285283932`.
- Positive lift rate: `0.6153846153846154`.
- Outcomes:
  - `avoided_loss`: 88.
  - `missed_win`: 55.

Interpretation:

- Lowering playbook floors alone is not enough.
- Policy-gated trend rows are too few and near-flat after outcomes.
- Breakout active rows are mostly unchanged, not a useful intervention yet.
- Mean reversion has a tiny allow-blocked positive pocket, but sample size is 1, so it is not promotable evidence.
- PriceAction removal remains the only sizeable positive source and should be handled as a separate playbook/matrix rather than mixed into generic RegimeV2 promotion.

Validation:

- `tests/test_regime_v2_playbook_calibration.py`: 6 passed.

### 6E. PriceAction-specific subset-removal matrix — implemented

Implemented:

- Added PriceAction-specific evidence module: `libs.selection.regime_v2_price_action_matrix`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.price_action_subset_matrix_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --limit 800 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --output-json research/regime_v2_price_action_matrix.json \
  --output-md research/regime_v2_price_action_matrix.md
```

Purpose:

- Isolate rows where baseline selected `PriceAction`.
- Require shadow selection to be `none` because `PriceAction` is outside the validated shadow subset.
- Require `shadow_subset_only=True` and `include_non_target_models=False`.
- Treat this as a PriceAction-specific evidence stream, not generic RegimeV2 playbook promotion.

Latest bounded PriceAction matrix findings:

- Total rows: 320.
- PriceAction subset-removal rows: 143 (`0.446875`).
- Cells: 12.
- Stable positive cells: 12 / 12.
- Worst cell:
  - horizon `3`, fee `2` bps.
  - average shadow-minus-baseline `0.0020839592208242177`.
  - positive lift rate `0.5874125874125874`.
- Best cell:
  - horizon `24`, fee `10` bps.
  - average shadow-minus-baseline `0.011533574324902133`.
  - positive lift rate `0.6013986013986014`.
- At horizon `12`, fee `5` bps:
  - average shadow-minus-baseline `0.005570930285283932`.
  - positive lift rate `0.6153846153846154`.
  - `avoided_loss`: 88.
  - `missed_win`: 55.

Per-pair note:

- `BTCUSDT|4h`, `ETHUSDT|4h`, and `BNBUSDT|1h` are consistently positive in most cells.
- `SOLUSDT|4h` is weaker/mixed, especially at longer horizons.

Interpretation:

- PriceAction removal is the only sizeable, stable positive finding so far.
- This should become a dedicated PriceAction playbook/guardrail candidate, not evidence for generic RegimeV2 gate promotion.
- A future implementation should add explicit PriceAction diagnostic features before any live suppression is considered.

Validation:

- `tests/test_regime_v2_price_action_matrix.py`: 6 passed.

### 6F. PriceAction guardrail candidate discovery — implemented

Implemented:

- Added offline guardrail discovery module: `libs.selection.regime_v2_price_action_guardrail`.
- Added CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.price_action_guardrail_candidates \
  --outcomes research/regime_v2_shadow_outcomes.jsonl \
  --min-support 10 \
  --min-bad-rate 0.55 \
  --min-avg-lift 0.0 \
  --output-json research/regime_v2_price_action_guardrail.json \
  --output-md research/regime_v2_price_action_guardrail.md
```

Purpose:

- Convert the Phase 6E PriceAction subset-removal evidence into candidate guardrail conditions.
- Rank conditions by support, PriceAction bad-rate, and removal lift.
- Keep this offline-only; no live suppression is enabled.

Latest bounded guardrail findings:

- Total rows: 320.
- PriceAction subset-removal rows: 143 (`0.446875`).
- Candidate guardrail rules: 13.
- Overall PriceAction removal metrics:
  - average shadow-minus-baseline `0.005570930285283932`.
  - bad rate `0.6153846153846154`.
  - `avoided_loss`: 88.
  - `missed_win`: 55.

Top candidate rules:

1. `direction=direction_1`
   - Count: 84.
   - Bad count: 82.
   - Bad rate: `0.9761904761904762`.
   - Average shadow-minus-baseline: `0.02834442664713288`.
   - Outcomes: 82 avoided losses, 2 missed wins.
2. `asset_timeframe=BTCUSDT|4h`
   - Count: 32.
   - Bad rate: `0.78125`.
   - Average shadow-minus-baseline: `0.009655834170479253`.
3. `confidence_bucket=confidence:(0.3,0.5]`
   - Count: 41.
   - Bad rate: `0.7317073170731707`.
   - Average shadow-minus-baseline: `0.00860774004623683`.
4. `uncertainty_bucket=uncertainty:(-inf,0.25]`
   - Count: 25.
   - Bad rate: `0.72`.
   - Average shadow-minus-baseline: `0.00200589531172162`.
5. `asset_timeframe=ETHUSDT|4h`
   - Count: 45.
   - Bad rate: `0.6222222222222222`.
   - Average shadow-minus-baseline: `0.008073239571370083`.

Interpretation:

- The first serious guardrail candidate is not generic PriceAction removal; it is PriceAction long suppression under this bounded sample.
- Short PriceAction rows were mostly missed wins when removed, so any future guardrail must be direction-aware.
- Asset/timeframe and confidence/uncertainty buckets are useful secondary diagnostics, but direction appears to be the dominant split.
- This remains offline evidence only and must be validated on a larger sample and rolling windows before any paper/live suppression.

Validation:

- `tests/test_regime_v2_price_action_guardrail.py`: 6 passed.

### 6G. PriceAction direction-aware guardrail validation — implemented

Implemented:

- Added rolling validation module: `libs.selection.regime_v2_price_action_guardrail_validation`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.validate_price_action_guardrail_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --direction 1 \
  --limit 1200 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --rolling-window 30 \
  --min-window 10 \
  --output-json research/regime_v2_price_action_guardrail_validation.json \
  --output-md research/regime_v2_price_action_guardrail_validation.md
```

Validation method:

- Re-collected a larger bounded offline shadow batch:
  - `--limit 1000`
  - `--warmup-bars 220`
  - `--max-records-per-pair 180`
  - 720 shadow rows total.
- Validated `PriceAction` subset removals where `baseline_selected_direction == 1`.
- Tested horizons `3`, `6`, `12`, `24` bars.
- Tested fees/slippage `2`, `5`, `10` bps.
- Tested 30-row rolling windows with minimum 10 rows.

Larger-sample result:

- Total rows: 720.
- Direction-1 guardrail candidate rows: 88 (`0.12222222222222222`).
- Stable positive cells: 0 / 12.
- Rolling-stable cells: 0 / 12.
- Best cell:
  - horizon `24`, fee `10` bps.
  - average shadow-minus-baseline `0.004679294157896675`.
  - bad rate `0.5454545454545454`.
- Worst cell:
  - horizon `12`, fee `2` bps.
  - average shadow-minus-baseline `-0.006523643622427316`.
  - bad rate `0.5113636363636364`.

Refreshed larger-sample 12-bar/5-bps outcome report:

- Rows: 720.
- Labeled: 720.
- Overall average shadow-minus-baseline: `-0.0010474045394583873`.
- Changed average shadow-minus-baseline: `-0.0038280775046194864`.
- Gate-active changed average shadow-minus-baseline: `-0.03894379511421357`.
- Gate-active changed positive lift rate: `0.3333333333333333`.
- Subset-only changed count: 185.

Refreshed larger-sample guardrail candidate report:

- PriceAction subset-removal rows: 185 (`0.2569444444444444`).
- Overall PriceAction removal average shadow-minus-baseline: `-0.0010447234480054173`.
- Overall PriceAction bad rate: `0.4918918918918919`.
- Candidate rules above thresholds: 4.
- The previous `direction=direction_1` rule is no longer a candidate:
  - Count: 88.
  - Average shadow-minus-baseline: `-0.006223643622427316`.
  - Bad rate: `0.5113636363636364`.

Interpretation:

- The earlier 320-row `direction_1` finding was likely sample-window overfit.
- Do not implement live PriceAction long suppression.
- Do not promote generic RegimeV2 based on subset-only PriceAction removal.
- Future work should move from simple one-dimensional guardrails to rolling-window robustness and maybe pair-specific/volatility-context rules.

Validation:

- `tests/test_regime_v2_price_action_guardrail_validation.py`: 6 passed.

### 6H. PriceAction guardrail drift / failure analysis — implemented

Implemented:

- Added drift module: `libs.selection.regime_v2_pa_drift_report`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.report_pa_drift_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --direction 1 \
  --limit 1200 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --rolling-window 30 \
  --min-window 10 \
  --output-json research/regime_v2_pa_drift_report.json \
  --output-md research/regime_v2_pa_drift_report.md
```

Purpose:

- Explain why the smaller 320-row `PriceAction + long` signal disappeared in the 720-row validation.
- Split by horizon/fee, rolling window, asset/timeframe, and direction.
- Keep this offline-only; no live suppression is enabled.

Latest 720-row drift findings:

- Total rows: 720.
- PriceAction subset-removal rows: 185 (`0.2569444444444444`).
- Direction tested: `1`.
- Candidate rows: 88 (`0.12222222222222222`).
- Cells: 12.
- Passing cells: 0 / 12.
- Failing cells: 12 / 12.
- Negative cells: 9 / 12.
- Rolling failure windows: 15.

Direction comparison across all horizon/fee cells:

- Direction `1`:
  - Count: 1056 cell-rows.
  - Average shadow-minus-baseline: `-0.002115356836362059`.
  - Bad rate: `0.5378787878787878`.
- Direction `-1`:
  - Count: 1164 cell-rows.
  - Average shadow-minus-baseline: `0.0002717036643974916`.
  - Bad rate: `0.5060137457044673`.

Asset/timeframe split for direction `1`:

- `BNBUSDT|1h`:
  - Negative cells: 0 / 12.
  - Average shadow-minus-baseline: `0.017125930321326772`.
  - Bad rate: `0.8055555555555556`.
- `BTCUSDT|4h`:
  - Negative cells: 12 / 12.
  - Average shadow-minus-baseline: `-0.009219100927506059`.
  - Bad rate: `0.31862745098039214`.
- `ETHUSDT|4h`:
  - Negative cells: 12 / 12.
  - Average shadow-minus-baseline: `-0.02796063803617932`.
  - Bad rate: `0.2875`.
- `SOLUSDT|4h`:
  - Negative cells: 12 / 12.
  - Average shadow-minus-baseline: `-0.011510433970034668`.
  - Bad rate: `0.3958333333333333`.

Worst rolling windows:

- The worst windows all start at timestamp `1771977600.0` and end at `1773489600.0`.
- Worst 12-bar / 2-bps window:
  - Count: 30.
  - Average shadow-minus-baseline: `-0.024792812761196194`.
  - Bad rate: `0.23333333333333334`.
  - Outcomes: 7 avoided losses, 23 missed wins.
- This early 30-row segment is the main reason the larger sample invalidates the smaller-sample guardrail.

Interpretation:

- The original direction-aware PriceAction long rule was sample-window overfit.
- The failure is asset-specific and time-window-specific, not random noise.
- `BNBUSDT|1h` remains interesting, but BTC/ETH/SOL are consistently negative for the same candidate.
- A future rule must be rolling-window and asset-specific; simple global direction suppression is invalid.
- Do not enable PriceAction suppression live or in paper yet.

Validation:

- `tests/test_regime_v2_pa_drift_report.py`: 6 passed.

### 6I. Asset-specific PriceAction candidate validation — implemented

Implemented:

- Added asset-specific validator: `libs.selection.regime_v2_pa_asset_candidate`.
- Added Binance wrapper CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.validate_pa_asset_candidate_binance \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --asset BNBUSDT \
  --timeframe 1h \
  --direction 1 \
  --limit 1200 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --rolling-window 20 --rolling-window 30 --rolling-window 50 \
  --min-window 10 \
  --min-support 30 \
  --passing-cell-floor 10 \
  --max-negative-cells 1 \
  --rolling-stable-floor 8 \
  --min-positive-rate 0.60 \
  --output-json research/regime_v2_pa_asset_candidate.json \
  --output-md research/regime_v2_pa_asset_candidate.md
```

Candidate tested:

- Asset/timeframe: `BNBUSDT|1h`.
- Baseline model: `PriceAction`.
- Baseline direction: `1`.
- Shadow removes PriceAction because it is outside the validated subset.

Strict validation gates:

- Candidate support >= 30.
- Passing cells >= 10 / 12.
- Negative cells <= 1 / 12.
- Rolling-stable cells >= 8 / 12.
- Positive lift rate >= 0.60.
- Rolling windows tested: 20, 30, 50 rows.

Latest 720-row result:

- Candidate rows: 39 (`0.05416666666666667`).
- Passing cells: 12 / 12.
- Negative cells: 0 / 12.
- Rolling-stable cells: 12 / 12.
- Recommendation: `paper_candidate`.
- Promote-ready flag in offline report: `true`.

Best cell:

- Horizon: 24.
- Fee: 10 bps.
- Count: 39.
- Average shadow-minus-baseline: `0.03043681728217294`.
- Bad rate: `0.8205128205128205`.
- Positive lift rate: `0.8205128205128205`.

Worst cell:

- Horizon: 3.
- Fee: 2 bps.
- Count: 39.
- Average shadow-minus-baseline: `0.006866099415516237`.
- Bad rate: `0.7948717948717948`.
- Positive lift rate: `0.7948717948717948`.

Worst rolling window:

- Rolling window: 20 rows.
- Horizon: 3.
- Fee: 2 bps.
- Count: 19.
- Average shadow-minus-baseline: `0.003480964765908864`.
- Bad rate: `0.6842105263157895`.
- Outcomes: 13 avoided losses, 6 missed wins.

Cross-asset comparison for direction `1` across the same horizon/fee grid:

- `BNBUSDT|1h`:
  - Count: 468 cell-rows.
  - Average shadow-minus-baseline: `0.017125930321326775`.
  - Bad rate: `0.8055555555555556`.
- `BTCUSDT|4h`:
  - Count: 204 cell-rows.
  - Average shadow-minus-baseline: `-0.009219100927506059`.
  - Bad rate: `0.31862745098039214`.
- `SOLUSDT|4h`:
  - Count: 144 cell-rows.
  - Average shadow-minus-baseline: `-0.011510433970034668`.
  - Bad rate: `0.3958333333333333`.
- `ETHUSDT|4h`:
  - Count: 240 cell-rows.
  - Average shadow-minus-baseline: `-0.027960638036179316`.
  - Bad rate: `0.2875`.

Interpretation:

- The global PriceAction direction rule is invalid.
- The BNBUSDT|1h-specific candidate is currently the only Phase 6 PriceAction lead strong enough for a controlled paper-shadow experiment.
- This is not live-ready.
- Next step should be a disabled-by-default paper-shadow overlay that records what would happen if this exact BNBUSDT|1h guardrail suppressed PriceAction direction-1 picks.

Validation:

- `tests/test_regime_v2_pa_asset_candidate.py`: 6 passed.

### 6J. BNBUSDT PriceAction paper-shadow overlay — implemented

Implemented:

- Added disabled-by-default paper preview module: `libs.selection.regime_v2_pa_asset_paper_guardrail`.
- Added separate JSONL paper logger: `libs.selection.regime_v2_pa_paper_log`.
- Integrated paper payload generation into `SelectionLayer` without changing live candidates or live selected results.
- Added config block under `overlays.regime_v2_pa_asset_guardrail`.
- Added BNBUSDT 1h guardrail config, still disabled by default.

Config shape:

```yaml
regime_v2_pa_asset_guardrail:
  paper_enabled: false
  paper_log_enabled: false
  paper_persist_enabled: false
  paper_persist_path: logs/regime_v2_pa_asset_paper_decisions.jsonl
  model_name: PriceAction
  asset: BNBUSDT
  timeframe: 1h
  direction: 1
```

Runtime behavior:

- If `paper_enabled: false`, exact no-op.
- If `paper_enabled: true`, SelectionLayer computes a counterfactual selection after removing only:
  - `model_name == PriceAction`
  - `asset == BNBUSDT`
  - `timeframe == 1h`
  - `direction == 1`
- Live selection candidates are not modified.
- Live selected results are not modified.
- Paper payload is attached to result metadata only for observability.
- JSONL persistence only happens if `paper_persist_enabled: true`.
- Paper logs write to a separate file, not the main RegimeV2 shadow log.

Paper log path:

```text
logs/regime_v2_pa_asset_paper_decisions.jsonl
```

Paper record type:

```text
regime_v2_pa_asset_paper_decision
```

Important safety constraints:

- No live/paper behavior is enabled by default.
- BNBUSDT 1h is configured as a candidate only, not active.
- This must not be enabled globally.
- This must not be generalized to BTC/ETH/SOL because Phase 6H showed those assets failed.

Validation:

- `tests/test_regime_v2_pa_paper_guardrail.py`: 5 passed.
- Full focused Phase 6 suite: 102 passed.
- `py_compile` passed for:
  - `regime_v2_pa_asset_paper_guardrail.py`
  - `regime_v2_pa_paper_log.py`
  - `selection_layer.py`
  - `test_regime_v2_pa_paper_guardrail.py`

Next step:

- Phase 6K should add a paper-log reporter and outcome-labeler for `regime_v2_pa_asset_paper_decision` records before any long-running paper rollout.

### 6K. PA paper reporting and outcomes — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_report`
- `libs.models.regime_v2.scripts.pa_paper_report`
- `libs.models.regime_v2.scripts.pa_paper_label`
- `tests/test_regime_v2_pa_paper_report.py`

Purpose:

- Summarize `logs/regime_v2_pa_asset_paper_decisions.jsonl`.
- Label PA paper records with future-return outcomes using Binance candles.
- Keep the paper stream separate from the main RegimeV2 shadow stream.
- Treat a missing paper log as an empty log so scheduled jobs are safe before rollout.

Generated empty pre-rollout artifacts:

- `research/regime_v2_pa_paper_report.json`
- `research/regime_v2_pa_paper_report.md`
- `research/regime_v2_pa_paper_outcomes.jsonl`
- `research/regime_v2_pa_paper_outcome_report.json`
- `research/regime_v2_pa_paper_outcome_report.md`

Current state:

- PA paper guardrail is still disabled.
- Paper report is therefore empty by design.
- Empty report CLI completed successfully.
- Empty outcome-label CLI completed successfully.
- No Binance fetches are attempted when the paper log has zero records.

Validation:

- New tests: 6 passed.
- Full focused Phase 6 suite: 108 passed.
- `py_compile` passed for the new module, both CLIs, and the test file.

Next step:

- Phase 6L: offline paper-log generator/replayer for BNBUSDT 1h, without enabling runtime config.

### 6L. Offline PA paper-log generator/replayer — implemented

Implemented:

- `libs.models.regime_v2.scripts.collect_pa_paper_binance`
- `tests/test_regime_v2_pa_paper_collector.py`

Purpose:

- Generate `logs/regime_v2_pa_asset_paper_decisions.jsonl` from historical Binance replay.
- Enable the BNBUSDT 1h PA paper guardrail only inside the script's in-memory `SelectionLayer` config.
- Keep runtime YAML disabled.
- Disable normal RegimeV2 shadow persistence inside the replay to avoid contaminating the main shadow log.

Replay command used:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.collect_pa_paper_binance \
  --asset BNBUSDT \
  --timeframe 1h \
  --limit 1000 \
  --warmup-bars 220 \
  --max-records 180 \
  --reset-log \
  --log-path logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --output-json research/regime_v2_pa_paper_collect_summary.json \
  --report-json research/regime_v2_pa_paper_report.json \
  --report-md research/regime_v2_pa_paper_report.md
```

Collection result:

- Status: `ok`.
- OHLCV rows: 1000.
- Candidate rows: 2189.
- Comparison rows: 1000.
- Paper records attempted: 180.
- Selected total: 364.
- Missing candidate bars: 0.

Outcome label result at 12 bars / 5 bps:

- Labeled: 180.
- Unlabeled: 0.
- Paper active: 97.
- Selection changed: 39.
- Paper-active changed: 39.
- Avg baseline net return: `0.004378160444750324`.
- Avg paper net return: `0.008741691273049308`.
- Avg paper minus baseline: `0.004363530828298983`.
- Avg changed paper minus baseline: `0.020139373053687615`.
- Changed positive paper lift rate: `0.7948717948717948`.

Changed group:

- Baseline: `PriceAction`.
- Paper: flat / no selection.
- Count: 39.
- Average paper-minus-baseline: `0.020139373053687615`.
- Outcomes: 31 avoided losses, 8 missed wins.

Validation:

- New collector tests: 3 passed.
- Full focused Phase 6 suite: 111 passed.
- `py_compile` passed for collector, reporter, labeler, and tests.

Conclusion:

- The BNBUSDT 1h paper pipeline is functional and confirms the offline candidate under the new paper-log path.
- It is still not live-enabled.
- Runtime config remains disabled.

### 6M. PA paper multi-cell robustness — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_robustness`
- `libs.models.regime_v2.scripts.pa_paper_robust`
- `tests/test_regime_v2_pa_paper_robustness.py`

Purpose:

- Re-label the BNBUSDT 1h PA paper log across horizon/fee cells.
- Validate the active-changed paper decisions across rolling windows.
- Keep this as an offline/paper report, not a live enablement.

Grid:

- Horizons: 3, 6, 12, 24 bars.
- Fees: 2, 5, 10 bps.
- Rolling windows: 20, 30, 50 rows.
- Minimum rolling window: 10 rows.

Latest refreshed result on 180 paper rows:

- Candidate rows: 40.
- Cells: 12.
- Passing cells: 0 / 12.
- Negative cells: 0 / 12.
- Rolling-stable cells: 0 / 12.
- Recommendation: `hold_off`.
- Paper-ready: `false`.

Best cell:

- Horizon: 24.
- Fee: 10 bps.
- Count: 40.
- Average paper-minus-baseline: `0.029453237975449`.
- Positive paper lift rate: `0.8`.

Worst cell:

- Horizon: 3.
- Fee: 2 bps.
- Count: 40.
- Average paper-minus-baseline: `0.006701542048503745`.
- Positive paper lift rate: `0.8`.

Worst rolling window:

- Rolling window: 30 rows.
- Horizon: 24.
- Fee: 2 bps.
- Count: 10.
- Average paper-minus-baseline: `-0.019160547889928922`.
- Positive paper lift rate: `0.2`.
- Outcomes: 2 avoided losses, 8 missed wins.

Generated artifacts:

- `research/regime_v2_pa_paper_robustness.json`
- `research/regime_v2_pa_paper_robustness.md`

Validation:

- New 6M tests: 3 passed.
- Existing focused Phase 6 suite: 111 passed.
- `py_compile` passed for the new module, CLI, and tests.

Conclusion:

- BNBUSDT 1h PA paper candidate remains positive on average across cells.
- Rolling stability is not currently good enough for a paper rollout.
- Runtime paper observation should hold off until the negative recent rolling window is understood.

### 6N. Controlled PA paper rollout safety switch — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_safety`
- `libs.models.regime_v2.scripts.pa_paper_safety`
- `tests/test_regime_v2_pa_paper_safety.py`
- `src/libs/models/regime_v2/PA_PAPER_ROLLOUT.md`

Purpose:

- Validate whether the PA paper rollout config is safe before runtime paper observation.
- Keep checked-in config disabled by default.
- Allow only `BNBUSDT|1h` as the PA paper pair.
- Block live-gate enablement.
- Block PA paper enablement on any other asset/timeframe.
- Block paper logs from using the main RegimeV2 shadow log path.

Default checked-in config result:

- `safe: true`.
- `rollout_ready: false`.
- Enabled pairs: `[]`.
- Persist-enabled pairs: `[]`.
- Live gate enabled pairs: `[]`.
- Violations: `0`.

Safety CLI:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_safety \
  --config configs/selection.yaml \
  --output-json research/regime_v2_pa_paper_safety.json \
  --output-md research/regime_v2_pa_paper_safety.md
```

Required pre-run check after temporarily enabling paper observation:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_safety \
  --config configs/selection.yaml \
  --require-enabled
```

Validation:

- New 6N tests: 6 passed.
- Focused Phase 6 suite: 117 passed.
- `py_compile` passed for safety module, CLI, and tests.

Current state:

- Runtime YAML remains disabled.
- PA paper observation is not active.
- Phase 6N provides a safe switch/check path but does not enable it.

### 6O. PA paper runtime monitoring report — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_monitor`
- `libs.models.regime_v2.scripts.pa_paper_monitor`
- `tests/test_regime_v2_pa_paper_monitor.py`

Purpose:

- Monitor PA paper outcome rows after runtime paper observation begins.
- Report all-time metrics plus recent windows.
- Surface watch flags without automatically disabling anything.
- Automatic disable remains Phase 6P.

Default monitoring windows:

- 24h.
- 168h / 7d.
- 720h / 30d.

Monitor metrics:

- labeled/unlabeled rows.
- paper-active rows.
- changed rows.
- active-changed rows.
- avoided losses.
- missed wins.
- average paper-minus-baseline.
- changed positive paper lift rate.
- monitor flags.

Monitor flags:

- `low_changed_sample`.
- `negative_avg_lift`.
- `missed_wins_exceed_avoided_losses`.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_monitor \
  --outcomes research/regime_v2_pa_paper_outcomes.jsonl \
  --window-hours 24 \
  --window-hours 168 \
  --window-hours 720 \
  --min-changed-rows 10 \
  --output-json research/regime_v2_pa_paper_monitor.json \
  --output-md research/regime_v2_pa_paper_monitor.md
```

Latest monitor result on current 180 labeled paper rows:

All-time:

- Active changed: 39.
- Average paper-minus-baseline: `0.020139373053687615`.
- Changed positive lift rate: `0.7948717948717948`.
- Avoided losses: 31.
- Missed wins: 8.
- Status: `ok`.

Last 24h:

- Active changed: 3.
- Average paper-minus-baseline: `-0.013897349580221709`.
- Changed positive lift rate: `0.0`.
- Avoided losses: 0.
- Missed wins: 3.
- Flags: `low_changed_sample`, `negative_avg_lift`, `missed_wins_exceed_avoided_losses`.
- Status: `watch`.

Last 7d:

- Active changed: 36.
- Average paper-minus-baseline: `0.020907885397431904`.
- Changed positive lift rate: `0.8055555555555556`.
- Avoided losses: 29.
- Missed wins: 7.
- Status: `ok`.

Last 30d:

- Active changed: 39.
- Average paper-minus-baseline: `0.020139373053687615`.
- Changed positive lift rate: `0.7948717948717948`.
- Avoided losses: 31.
- Missed wins: 8.
- Status: `ok`.

Interpretation:

- All-time, 7d, and 30d remain strong.
- The 24h view is currently a watch condition due to low sample size and 3 missed wins.
- This confirms why Phase 6P automatic disable criteria must exist before any long-running paper rollout.

Validation:

- New 6O tests: 4 passed.
- Focused Phase 6 suite: 121 passed.
- `py_compile` passed for monitor module, CLI, and tests.

### 6P. PA paper automatic disable recommendation — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_disable`
- `libs.models.regime_v2.scripts.pa_paper_disable`
- `tests/test_regime_v2_pa_paper_disable.py`
- Updated `PA_PAPER_ROLLOUT.md` with the disable recommendation check.

Purpose:

- Convert Phase 6O monitor output into an explicit non-mutating recommendation.
- Do not edit config automatically.
- Do not disable on insufficient sample.
- Recommend pause/disable only for hard failures with enough changed rows.

Hard failure reasons:

- `negative_avg_lift`.
- `missed_wins_exceed_avoided_losses`.

Insufficient sample behavior:

- If a hard failure occurs but `active_changed_count < min_changed_rows`, recommendation is `continue_monitoring_insufficient_sample`.
- This avoids overreacting to a tiny window such as 3 changed rows.

Recommendations:

- `continue_monitoring`.
- `continue_monitoring_insufficient_sample`.
- `pause_for_review`.
- `disable_paper_observation`.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_disable \
  --monitor research/regime_v2_pa_paper_monitor.json \
  --output-json research/regime_v2_pa_paper_disable.json \
  --output-md research/regime_v2_pa_paper_disable.md
```

Latest recommendation from current monitor report:

- Recommendation: `continue_monitoring_insufficient_sample`.
- Disable recommended: `false`.
- Pause recommended: `false`.
- Actionable failures: 0.
- Insufficient failures: 1.
- Low-sample segments: 1.
- Hard failure count: 1.

Reason:

- Last 24h had 3 active-changed rows, negative average lift, and 3 missed wins.
- Because 3 rows is below the 10-row floor, this is not actionable.
- All-time, 7d, and 30d remain healthy.

Validation:

- New 6P tests: 6 passed.
- Focused Phase 6 suite: 127 passed.
- `py_compile` passed for disable module, CLI, and tests.

Current state:

- Runtime config remains disabled.
- Phase 6P only emits recommendations.
- No automatic config mutation exists.

### 6Q. PA paper action comparison — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_actions`
- `libs.models.regime_v2.scripts.pa_paper_actions`
- `tests/test_regime_v2_pa_paper_actions.py`
- Updated `PA_PAPER_ROLLOUT.md` with the action comparison step.

Purpose:

- Compare the current hard suppression/reselect paper action against softer alternatives.
- Use labeled paper outcomes only.
- Do not change runtime behavior.

Compared actions:

- `keep_baseline`.
- `suppress_to_paper`.
- `scale_baseline_0.25`.
- `scale_baseline_0.5`.
- `scale_baseline_0.75`.

Latest result on the active changed cohort:

- Cohort rows: 40.
- Best action: `suppress_to_paper`.
- Current action: `suppress_to_paper`.
- Current rank: 1.
- Recommendation: `keep_suppress_to_paper`.
- Average lift for current action: `0.019337334305283522`.
- Positive lift rate: `0.775`.
- Outcomes: 31 avoided losses, 9 missed wins.

Action ranking by average paper/action-minus-baseline:

1. `suppress_to_paper`: `0.019337334305283522`.
2. `scale_baseline_0.25`: `0.014503000728962642`.
3. `scale_baseline_0.5`: `0.009668667152641761`.
4. `scale_baseline_0.75`: `0.0048343335763208805`.
5. `keep_baseline`: `0.0`.

Interpretation:

- Softer reduced-size variants are positive but weaker than hard suppression on the tested cohort.
- Keeping PriceAction is worst on this specific changed cohort.
- Current paper action remains the best tested action.
- Full alternate candidate re-ranking is not yet possible from paper logs alone because full candidate rankings are not persisted.

Validation:

- New 6Q tests: 4 passed.
- Focused Phase 6 suite: 131 passed.
- `py_compile` passed for action module, CLI, and tests.

### 6R. PA paper candidate-ranking snapshots — implemented

Implemented:

- Added ranked candidate snapshots to the PA paper payload in `selection_layer.py`.
- Added top-level JSONL snapshot fields in `regime_v2_pa_paper_log.py`.
- `libs.selection.regime_v2_pa_paper_snapshots`.
- `libs.models.regime_v2.scripts.pa_paper_snapshots`.
- `tests/test_regime_v2_pa_paper_snapshots.py`.
- `tests/test_regime_v2_pa_paper_snapshot_report.py`.

Purpose:

- Persist compact candidate ranking snapshots for baseline and paper selections.
- Make future alternate-action testing possible when alternate candidates exist.
- Validate whether changed rows have a usable next-best candidate.

Snapshot fields:

- `candidate_snapshot_schema_version`.
- `baseline_ranked_candidates`.
- `paper_ranked_candidates`.

Each snapshot row contains:

- rank.
- model name.
- asset/timeframe.
- direction.
- edge score.
- conviction.
- selection score.
- penalties.

Latest snapshot coverage on refreshed 180-row paper log:

- Baseline snapshot count: 180.
- Paper snapshot count: 140.
- Both snapshot count: 140.
- Snapshot coverage rate: `0.7777777777777778`.
- Paper active count: 99.
- Selection changed count: 40.
- Changed with alternate count: 0.
- Changed alternate coverage rate: `0.0`.
- Alternate action ready: `false`.
- Avg baseline snapshot size: `2.033333333333333`.
- Avg paper snapshot size: `1.9428571428571428`.

Interpretation:

- The new snapshot schema is being persisted.
- Changed rows currently suppress to flat because no alternate paper candidate remains after suppression.
- True next-best routing is therefore not ready from the current BNBUSDT 1h paper rows.
- This supports keeping flat suppression as the only tested action for now, while also showing why runtime paper rollout should hold off after the refreshed rolling-stability failure.

Generated artifacts:

- `research/regime_v2_pa_paper_snapshots.json`.
- `research/regime_v2_pa_paper_snapshots.md`.

Validation:

- New 6R tests: 5 passed.
- Focused Phase 6 suite: 139 passed.
- `py_compile` passed for selection layer, paper log, snapshot module, CLI, and tests.

### 6S. PA paper negative rolling-window diagnostics — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_window_diagnostics`.
- `libs.models.regime_v2.scripts.pa_paper_window_diag`.
- `tests/test_regime_v2_pa_paper_window_diagnostics.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the diagnostic posture.

Purpose:

- Reconstruct the worst rolling window from the robustness report.
- Re-label paper decisions at the same horizon/fee as that worst window.
- Compare failure-window rows against before/after/all active-changed rows.
- Explain why the rolling-stability check failed.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_window_diag \
  --log logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --robustness research/regime_v2_pa_paper_robustness.json \
  --limit 1200 \
  --min-changed-rows 10 \
  --include-rows 25 \
  --output-json research/regime_v2_pa_paper_window_diag.json \
  --output-md research/regime_v2_pa_paper_window_diag.md
```

Latest diagnostic result:

- Window start timestamp: `1780696800.0`.
- Window end timestamp: `1780891200.0`.
- Horizon: 24 bars.
- Fee: 2 bps.
- Rolling window: 30.
- Failure rows: 10.
- Failure average paper-minus-baseline: `-0.019160547889928922`.
- Failure positive lift rate: `0.2`.
- Outcomes: 2 avoided losses, 8 missed wins.
- Recommendation: `hold_off_and_investigate_window`.

Diagnosis:

- `negative_window_lift`.
- `missed_wins_dominate`.
- `flat_after_suppression`.
- `baseline_price_action_worked_in_window`.

Segment comparison:

Before failure window:

- Count: 30.
- Average paper-minus-baseline: `0.04459116659724163`.
- Positive lift rate: `1.0`.
- Outcomes: 30 avoided losses, 0 missed wins.

Failure window:

- Count: 10.
- Average paper-minus-baseline: `-0.019160547889928922`.
- Positive lift rate: `0.2`.
- Outcomes: 2 avoided losses, 8 missed wins.

All active-changed rows:

- Count: 40.
- Average paper-minus-baseline: `0.028653237975448997`.
- Positive lift rate: `0.8`.
- Outcomes: 32 avoided losses, 8 missed wins.

Interpretation:

- The failure is not a timestamp/window artifact.
- It is a localized market-regime drift where PriceAction longs worked and flat suppression missed the move.
- The pre-window evidence was very strong in favor of suppression, so the candidate is unstable rather than useless.
- Runtime paper observation should remain on hold until there is a context filter or drift gate for this reversal pocket.

Generated artifacts:

- `research/regime_v2_pa_paper_window_diag.json`.
- `research/regime_v2_pa_paper_window_diag.md`.

Validation:

- New 6S tests: 3 passed.
- Focused Phase 6 suite: 142 passed.
- `py_compile` passed for diagnostic module, CLI, and tests.

### 6T. PA paper context-filter discovery — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_filter_discovery`.
- `libs.models.regime_v2.scripts.pa_paper_filter_discovery`.
- `libs.models.regime_v2.scripts.pa_paper_ctx` alias.
- `tests/test_regime_v2_pa_paper_filter_discovery.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the context-filter discovery posture.

Purpose:

- Search for simple context filters that would keep the strong suppression zone while rejecting the recent missed-win pocket.
- Evaluate filters at the same horizon/fee as the worst robustness window.
- Keep this offline only; do not change runtime config.

Default searched fields:

- `baseline_selection_score`.
- `baseline_edge_score`.
- `baseline_conviction`.
- derived recency position.
- failure-window membership for diagnostics.

Command alias used for real report:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_ctx \
  --log logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --robustness research/regime_v2_pa_paper_robustness.json \
  --limit 1200 \
  --min-support 5 \
  --min-rejected-bad-rate 0.60 \
  --max-kept-bad-rate 0.35 \
  --output-json research/regime_v2_pa_paper_ctx.json \
  --output-md research/regime_v2_pa_paper_ctx.md
```

Latest discovery result:

- Active changed rows: 40.
- Failure window rows: 10.
- Candidate filters found: 2.
- Recommendation: `candidate_filter_found`.

Best filter:

- Rule: `recent_window_position >= 0.75`.
- Kept rows: 30.
- Rejected rows: 10.
- Kept average lift: `0.04459116659724163`.
- Rejected average lift: `-0.019160547889928922`.
- Kept bad rate: `0.0`.
- Rejected bad rate: `0.8`.
- Failure window coverage: `1.0`.

Second equivalent filter:

- Rule: `timestamp >= failure_window_start`.
- Same kept/rejected performance.

Interpretation:

- The only simple filters that cleanly separate the failure pocket are time/recency filters.
- Score, edge, and conviction thresholds did not produce a durable simple context filter under the current thresholds.
- This points to temporal drift / localized regime shift, not a stable confidence-score cutoff.
- Runtime paper rollout should still hold off.
- Next work should add either a drift detector/streak gate or richer real-time features such as volatility, trend slope, breakout context, and higher-timeframe state.

Generated artifacts:

- `research/regime_v2_pa_paper_ctx.json`.
- `research/regime_v2_pa_paper_ctx.md`.

Validation:

- New 6T tests: 3 passed.
- Focused Phase 6 suite: 145 passed.
- `py_compile` passed for discovery module, CLI, alias, and tests.

### 6U. PA paper drift/streak gate simulation — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_drift_gate`.
- `libs.models.regime_v2.scripts.pa_paper_drift_gate`.
- `libs.models.regime_v2.scripts.pa_paper_dg` alias.
- `tests/test_regime_v2_pa_paper_drift_gate.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the drift-gate diagnostic posture.

Purpose:

- Simulate non-live pause rules for PA suppression.
- Use only prior active-changed paper outcomes to decide whether suppression would be paused on the current row.
- Avoid look-ahead decisions in the gate simulation.
- Compare paused-gate performance against current suppress-to-flat.

Tested gate families:

- Missed-win streak gates: `missed_streak_2`, `missed_streak_3`.
- Rolling negative average lift gates: `rolling_avg_neg_3`, `rolling_avg_neg_5`, `rolling_avg_neg_10`.
- Rolling missed-wins-vs-avoided-losses gates: `miss_gt_avoid_3`, `miss_gt_avoid_5`, `miss_gt_avoid_10`.

Command alias used for real report:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_dg \
  --log logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --robustness research/regime_v2_pa_paper_robustness.json \
  --limit 1200 \
  --min-paused-rows 1 \
  --output-json research/regime_v2_pa_paper_dg.json \
  --output-md research/regime_v2_pa_paper_dg.md
```

Latest result:

- Active changed rows: 40.
- Candidate gates: 8.
- Ranked gates: 8.
- Recommendation: `candidate_drift_gate_found`.
- Current suppress-to-paper average lift: `0.028653237975448997`.

Best gate:

- Name: `rolling_avg_neg_3`.
- Paused rows: 6.
- Active rows: 34.
- Recovered missed wins: 6.
- Lost avoided losses: 0.
- Failure-window pause rate: `0.6`.
- Gate average lift: `0.03300262575865177`.
- Improvement over current suppression: `0.004349387783202768`.

Equivalent top-tier gate:

- `miss_gt_avoid_3` has the same metrics as `rolling_avg_neg_3` on the refreshed sample.

Other useful gates:

- `missed_streak_2`: recovered 5 missed wins, lost 0 avoided losses, improvement `0.003492270272345193`.
- `rolling_avg_neg_5`: recovered 5 missed wins, lost 0 avoided losses, improvement `0.003492270272345193`.
- `miss_gt_avoid_5`: recovered 5 missed wins, lost 0 avoided losses, improvement `0.003492270272345193`.

Interpretation:

- A short-memory drift gate can partially avoid the localized failure pocket.
- Unlike the score-filter search, this is not a static confidence cutoff; it is a recent-outcome deterioration detector.
- The best diagnostic gate improved average lift and did not sacrifice any avoided-loss rows on the refreshed 40-row active-changed cohort.
- This is promising but still too small to enable runtime paper observation.

Generated artifacts:

- `research/regime_v2_pa_paper_dg.json`.
- `research/regime_v2_pa_paper_dg.md`.

Validation:

- New 6U tests: 3 passed.
- Focused Phase 6 suite: 148 passed.
- `py_compile` passed for drift-gate module, CLI, alias, and tests.

### 6V. PA paper drift-gate horizon/fee matrix — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_dg_matrix`.
- `libs.models.regime_v2.scripts.pa_paper_dg_matrix`.
- `tests/test_regime_v2_pa_paper_dg_matrix.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the 6V matrix posture.

Purpose:

- Validate the best Phase 6U gate, `rolling_avg_neg_3`, across horizon/fee cells.
- Test whether the gate remains useful beyond the single 24-bar / 2-bps diagnostic case.
- Include rolling-window stability checks over active-changed rows.
- Keep this offline only; do not change runtime config.

Validation grid:

- Horizons: 3, 6, 12, 24 bars.
- Fees: 2, 5, 10 bps.
- Rolling windows: 20, 30, 50 active-changed rows.
- Minimum rolling window: 10 rows.
- Max lost avoided losses per cell: 0.
- Minimum rolling positive-improvement rate: 0.50.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_dg_matrix \
  --log logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --limit 1200 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --rolling-window 20 --rolling-window 30 --rolling-window 50 \
  --min-window 10 \
  --min-cell-improvement 0.0 \
  --max-lost-avoided 0 \
  --min-rolling-positive-rate 0.50 \
  --output-json research/regime_v2_pa_paper_dg_matrix.json \
  --output-md research/regime_v2_pa_paper_dg_matrix.md
```

Latest result:

- Gate: `rolling_avg_neg_3`.
- Cells: 12.
- Improved cells: 12 / 12.
- Passing cells: 6 / 12.
- No-lost-avoided cells: 6 / 12.
- Rolling-stable cells: 7 / 12.
- Recommendation: `hold_off`.
- Matrix-ready: `false`.

Best cell:

- Horizon: 24 bars.
- Fee: 2 bps.
- Count: 40.
- Gate improvement over current suppression: `0.004349387783202768`.
- Gate average lift: `0.03300262575865177`.
- Recovered missed wins: 6.
- Lost avoided losses: 0.

Worst cell:

- Horizon: 6 bars.
- Fee: 10 bps.
- Count: 40.
- Gate improvement over current suppression: `0.0005918413065712553`.
- Gate average lift: `0.011756032177766777`.
- Recovered missed wins: 3.
- Lost avoided losses: 2.

Worst rolling window:

- Horizon: 6 bars.
- Fee: 10 bps.
- Rolling window: 20 rows.
- Count: 20.
- Gate improvement over current suppression: `-0.0006556879307570669`.
- Gate average lift: `0.013197801220012642`.
- Recovered missed wins: 0.
- Lost avoided losses: 1.

Interpretation:

- The drift gate improves average outcome in every horizon/fee cell.
- It is strongest at 12-bar and 24-bar horizons.
- It is not strict-promotion-ready because short horizons lose avoided-loss rows and some rolling windows remain unstable.
- This upgrades the idea from a single-cell diagnostic to a promising candidate, but not a runtime paper-rollout rule.

Generated artifacts:

- `research/regime_v2_pa_paper_dg_matrix.json`.
- `research/regime_v2_pa_paper_dg_matrix.md`.

Validation:

- New 6V tests: 3 passed.
- Focused Phase 6 suite: 151 passed.
- `py_compile` passed for matrix module, CLI, and tests.

### 6W. PA paper drift-gate refinement search — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_gate_search`.
- `libs.models.regime_v2.scripts.pa_paper_gs`.
- `tests/test_regime_v2_pa_paper_gs.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the 6W refinement posture.

Purpose:

- Refine the Phase 6V drift gate to reduce short-horizon avoided-loss damage.
- Compare stricter variants across the same horizon/fee matrix.
- Keep this offline only; do not change runtime config.

Variants tested:

- `rolling_avg_neg_3`.
- `miss_gt_avoid_3`.
- `missed_streak_2`.
- `rolling_avg_neg_3_and_miss_gt_avoid_3`.
- `rolling_avg_neg_3_and_missed_streak_2`.
- `rolling_avg_below_002_3`.
- `rolling_avg_below_005_3`.
- `rolling_avg_below_002_5`.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_gs \
  --log logs/regime_v2_pa_asset_paper_decisions.jsonl \
  --limit 1200 \
  --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
  --fee-bps 2 --fee-bps 5 --fee-bps 10 \
  --rolling-window 20 --rolling-window 30 --rolling-window 50 \
  --min-window 10 \
  --max-lost-avoided 0 \
  --output-json research/regime_v2_pa_paper_gs.json \
  --output-md research/regime_v2_pa_paper_gs.md
```

Latest result:

- Variants: 8.
- Cells per variant: 12.
- Ready variants: 0.
- Recommendation: `hold_off_refine_more`.

Best variant:

- Name: `rolling_avg_below_002_3`.
- Passing cells: 9 / 12.
- Improved cells: 12 / 12.
- No-lost-avoided cells: 9 / 12.
- Rolling-stable cells: 12 / 12.
- Average improvement over current suppression: `0.002141768351162817`.
- Total recovered missed wins across cells: 51.
- Total lost avoided losses across cells: 3.
- Matrix-ready: `false`.

Best cell for best variant:

- Horizon: 24 bars.
- Fee: 2 bps.
- Improvement: `0.004349387783202768`.
- Recovered missed wins: 6.
- Lost avoided losses: 0.

Remaining failed cells for best variant:

- Horizon 3 / fee 2 bps: recovered 2, lost 1 avoided loss.
- Horizon 3 / fee 5 bps: recovered 2, lost 1 avoided loss.
- Horizon 3 / fee 10 bps: recovered 2, lost 1 avoided loss.

Comparison to Phase 6V base gate:

- Base `rolling_avg_neg_3`: 6 / 12 passing, 11 total lost avoided losses.
- Refined `rolling_avg_below_002_3`: 9 / 12 passing, 3 total lost avoided losses.

Interpretation:

- The magnitude threshold refinement materially reduced short-horizon damage.
- The candidate is strongest at 12-bar and 24-bar horizons.
- The only remaining blocker is 3-bar short-horizon behavior.
- This suggests the PA suppression rule should be horizon-aware or evaluated only on longer holding horizons before any runtime paper rollout.

Generated artifacts:

- `research/regime_v2_pa_paper_gs.json`.
- `research/regime_v2_pa_paper_gs.md`.

Validation:

- New 6W tests: 3 passed.
- Focused Phase 6 suite: 154 passed.
- `py_compile` passed for gate-search module, CLI, and tests.

### 6X. PA paper horizon-slice validation — implemented

Implemented:

- `libs.selection.regime_v2_pa_paper_hz`.
- `libs.models.regime_v2.scripts.pa_paper_hz`.
- `tests/test_regime_v2_pa_paper_hz.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the 6X horizon-slice posture.

Purpose:

- Separate short-horizon 3-bar failures from mid/long-horizon behavior.
- Validate whether the best 6W refined gate is a long-horizon-only candidate.
- Use the existing 6W gate-search report as input.
- Keep this offline only; do not change runtime config.

Command:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_hz
```

Defaults:

- Source: `research/regime_v2_pa_paper_gs.json`.
- Long horizons: 12 and 24 bars.
- Short horizons: 3 bars.
- Mid horizon: 6 bars.

Latest result:

- Variant count: 8.
- Best variant: `rolling_avg_below_002_3`.
- Long-horizon candidate: `true`.
- Recommendation: `long_horizon_paper_candidate`.

Best variant long-horizon slice:

- Long horizons: 12 and 24 bars.
- Long cells: 6.
- Long passing cells: 6 / 6.
- Long average improvement: `0.003234266325851628`.
- Long lost avoided losses: 0.
- Long recovered missed wins: 36.

Best variant mid-horizon slice:

- Mid horizon: 6 bars.
- Mid cells: 3.
- Mid passing cells: 3 / 3.
- Mid average improvement: `0.0010486786595863115`.
- Mid lost avoided losses: 0.
- Mid recovered missed wins: 9.

Best variant short-horizon slice:

- Short horizon: 3 bars.
- Short cells: 3.
- Short passing cells: 0 / 3.
- Short average improvement: `0.0010498620933617011`.
- Short lost avoided losses: 3.
- Short recovered missed wins: 6.

Interpretation:

- The refined pause rule is cleanly valid for 6/12/24-bar outcomes under strict no-lost-avoided criteria.
- The only remaining failure is 3-bar short-horizon behavior.
- This supports treating the rule as a long-horizon-only paper candidate, not a general PA rule.
- Runtime paper mode remains disabled by default.

Generated artifacts:

- `research/regime_v2_pa_paper_hz.json`.
- `research/regime_v2_pa_paper_hz.md`.

Validation:

- New 6X tests: 3 passed.
- Previous broad focused suite before 6X: 154 passed.
- Broad focused-suite command was blocked after 6X by safety checker, but 6X focused tests and `py_compile` passed.

### 6Y. PA paper long-horizon candidate descriptor — implemented

Implemented:

- `configs/selection.yaml` long-horizon candidate metadata under `regime_v2_pa_asset_guardrail`.
- `libs.selection.regime_v2_pa_paper_hzc`.
- `libs.models.regime_v2.scripts.pa_paper_hzc`.
- `tests/test_regime_v2_pa_paper_hzc.py`.
- Updated `PA_PAPER_ROLLOUT.md` with the descriptor safety posture.

Purpose:

- Represent the 6X result as an explicit long-horizon-only candidate.
- Keep candidate metadata disabled by default.
- Verify that runtime paper flags and live RegimeV2 gate remain off.
- Prevent accidental broad paper rollout or live promotion.

Descriptor added to selection config:

```yaml
long_horizon_candidate:
  candidate_enabled: false
  paper_runtime_enabled: false
  rule_name: rolling_avg_below_002_3
  rule_type: rolling_avg_below
  window: 3
  threshold: -0.002
  valid_horizons_bars:
    - 6
    - 12
    - 24
  invalid_horizons_bars:
    - 3
  source_report: research/regime_v2_pa_paper_hz.json
```

Validation report:

- `research/regime_v2_pa_paper_hzc.json`.
- `research/regime_v2_pa_paper_hzc.md`.

Latest descriptor validation result:

- Asset/timeframe: `BNBUSDT|1h`.
- Target model: `PriceAction`.
- Target direction: 1.
- Rule: `rolling_avg_below_002_3`.
- Valid horizons: 6, 12, 24.
- Invalid horizons: 3.
- Candidate enabled: `false`.
- Paper runtime enabled: `false`.
- Paper log enabled: `false`.
- Paper persist enabled: `false`.
- Live gate enabled: `false`.
- Horizon report recommendation: `long_horizon_paper_candidate`.
- Safe: `true`.
- Violations: 0.
- Warnings: 0.
- Recommendation: `metadata_candidate_disabled_ok`.

Interpretation:

- The long-horizon candidate is now explicitly represented and guarded.
- Runtime paper mode remains disabled.
- This is not a live rule and not a general all-horizon paper rollout.
- Any future paper observation must pass this descriptor check plus the existing rollout safety checks.

Validation:

- New 6Y tests: 4 passed.
- Descriptor report generated successfully.
- `py_compile` command was blocked by safety checker, but tests import and execute the new module/CLI path.

### 6Z. Repo hygiene and phase index — implemented

Implemented:

- `PHASE_INDEX.md`.
- `REPO_REVIEW.md`.
- Updated this phase plan with the 6Z status.

Purpose:

- Add a compact navigation index for the RegimeV2 implementation.
- Summarize current runtime posture and the long-horizon-only PA candidate scope.
- Separate commit-worthy code/docs/tests from generated local evidence.
- Call out unrelated Alert App work so it is not mixed with a RegimeV2 commit.

Working-tree snapshot observed before the 6Z docs were added:

- Modified tracked files: 12.
- Untracked files overall: 129.
- RegimeV2 core files: 67.
- RegimeV2 selection helper files: 28.
- RegimeV2 focused tests: 30.
- RegimeV2 research artifacts: 66.
- Separate Alert App work: 47 untracked files plus config/plan files.

Commit-readiness recommendation:

- Stage RegimeV2 core and docs together.
- Stage selection integration separately if desired.
- Stage focused tests separately if desired.
- Prefer committing Markdown research summaries over generated JSON/JSONL outputs.
- Keep runtime logs local.
- Keep Alert App work separate from the RegimeV2 commit.

Current 6Z conclusion:

- RegimeV2 is commit-ready as a disabled, offline-first/shadow-first module if staged carefully.
- Runtime live gate and PA paper runtime remain disabled.
- The long-horizon PA candidate is explicit but metadata-only.
- Next work should either collect more out-of-sample paper evidence for the long-horizon candidate or move into deterministic playbook redesign.

## Phase 6 — Calibration

Goal: make confidence meaningful rather than heuristic.

Required work:

- Bucket confidence and trend_score against realized downstream outcome.
- Add reliability curves.
- Track per-asset/timeframe calibration.
- Optional: isotonic/Platt-style calibration after enough labeled outcomes exist.

## Phase 7 — Deterministic playbook redesign and challenger layer

### 7A. Read-only playbook context layer — implemented

Implemented:

- `libs.models.regime_v2.policy.playbook_context`.
- `libs.models.regime_v2.evaluation.playbook_context_report`.
- `libs.models.regime_v2.scripts.report_playbook_context`.
- `tests/test_regime_v2_playbook_context.py`.
- `tests/test_regime_v2_playbook_context_report.py`.
- Exported context helpers from `libs.models.regime_v2.policy`.
- Generated `research/regime_v2_phase7a_playbook_context.json` and `.md`.

Purpose:

- Add a richer deterministic explanation layer without changing policy permissions.
- Label each row with market phase, risk state, dominant playbook, horizon bias, context alignment, conflict tags, and recommended next step.
- Make playbook redesign observable before changing any live or paper gating.

New context fields include:

- `market_phase` such as `bull_trend`, `displacement_breakout`, `retest_breakout`, `breakout_setup`, `range_reversion`, `compressed_wait`, `shock_no_trade`, and `uncertain_no_trade`.
- `risk_state`: `ok`, `watch`, or `blocked`.
- `dominant_playbook`: trend, breakout, mean reversion, scalping, countertrend, or none.
- `horizon_bias`: none, short/flat, short-to-mid, mid, mid-to-long, long, or wait-for-expansion.
- `context_alignment`: aligned, against, mixed, risk-on/off without trend, or neutral/missing.
- `conflict_tags`: deterministic conflict explanations such as trend/chop conflict, breakout false-break risk, shock conflict, liquidity stress, uncertainty, or compression without breakout.

Initial BNBUSDT 1h report:

- Rows: 720.
- Active context count: 366.
- Active context rate: `0.5083333333333333`.
- Average risk score: `0.5322576388888889`.
- Average conflict count: `0.9069444444444444`.
- Dominant playbook distribution: scalping 631, none 84, mean reversion 5.
- Risk state distribution: blocked 354, ok 361, watch 5.
- Horizon bias distribution: none 354, wait-for-expansion 314, mid 44, short-to-mid 8.
- Market phase distribution: uncertain no-trade 327, compressed wait 177, breakout setup 146, neutral context 40, shock no-trade 27, range reversion 3.
- Top conflicts: compression without breakout 333, uncertainty high 320.

Interpretation:

- The current deterministic score surface is too scalping-heavy for BNBUSDT 1h.
- External/cross-asset context is neutral or missing for the fetched OHLCV-only run, so richer context columns are needed before relying on context confirmation.
- Many rows are blocked by uncertainty or waiting for compression expansion, which gives a practical redesign direction: separate setup/wait states from executable playbooks.
- This supports redesigning playbook policy as a staged state machine rather than a flat threshold table.

Validation:

- New Phase 7A tests: 6 passed.
- `py_compile` passed for new modules, CLI, and tests.

### 7B. Offline staged playbook state machine — implemented

Implemented:

- `libs.models.regime_v2.policy.playbook_state_machine`.
- `libs.models.regime_v2.scripts.report_playbook_states`.
- `tests/test_regime_v2_playbook_state_machine.py`.
- Exported state-machine helpers from `libs.models.regime_v2.policy`.
- Generated `research/regime_v2_phase7b_playbook_states.json` and `.md`.

Purpose:

- Turn the Phase 7A diagnostic context into explicit staged states.
- Separate risk/no-trade, wait/setup, and executable states.
- Make the deterministic redesign testable before changing `RegimePolicy` permissions or selection behavior.

States:

- `NO_TRADE_RISK`.
- `WAIT_COMPRESSION`.
- `BREAKOUT_SETUP`.
- `BREAKOUT_CONFIRMATION`.
- `TREND_CONTINUATION`.
- `RANGE_REVERSION`.
- `SCALP_ONLY`.
- `OBSERVE_ONLY`.

Initial BNBUSDT 1h state report:

- Rows: 720.
- Executable count: 43.
- Executable rate: `0.059722222222222225`.
- Wait count: 325.
- Wait rate: `0.4513888888888889`.
- Risk/no-trade count: 352.
- Risk/no-trade rate: `0.4888888888888889`.
- Average risk score: `0.5308023611111111`.
- Average conflict count: `0.9069444444444444`.

State distribution:

- `NO_TRADE_RISK`: 352.
- `WAIT_COMPRESSION`: 316.
- `SCALP_ONLY`: 40.
- `BREAKOUT_SETUP`: 9.
- `RANGE_REVERSION`: 3.

Interpretation:

- The staged state machine is much stricter than the flat score surface.
- Most rows become either risk/no-trade or wait/setup, not executable signals.
- This aligns with the Phase 7 direction: wait states must not be treated as executable playbooks.
- The current BNBUSDT 1h sample has almost no trend-continuation or confirmed-breakout states, so the next phase should validate whether the state machine aligns with forward outcomes before using it to alter policy.

Validation:

- Phase 7A/7B combined tests: 11 passed.
- `py_compile` passed for the state-machine module, CLI, and tests.

### 7C. Playbook state-outcome validation — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_state_outcomes`.
- `libs.models.regime_v2.scripts.report_playbook_state_outcomes`.
- `tests/test_regime_v2_playbook_state_outcomes.py`.
- Generated `research/regime_v2_phase7c_state_outcomes.json` and `.md`.

Purpose:

- Validate whether 7B states separate forward outcomes.
- Evaluate state groups across horizons 3, 6, 12, and 24 bars.
- Evaluate fee grid 2, 5, and 10 bps for directional states where direction is known.
- Keep the validation offline; no live policy or selection changes.

Outcome metrics:

- Forward log return.
- Absolute forward movement.
- Positive/negative forward-return rate.
- Large-move rate.
- Directional net return only for clear bull/bear trend-continuation states.

Initial BNBUSDT 1h result:

- Cells: 12.
- Horizons: 3, 6, 12, 24.
- Fees: 2, 5, 10 bps.
- Best executable cell: 3 bars / 2 bps, average forward return `0.0017833842961805626`, count 43.
- Worst executable cell: 24 bars / 2 bps, average forward return `-0.014245021164536003`, count 40.
- Best scalp-only cell: 3 bars / 2 bps, average forward return `0.0015753785894020399`, count 40.
- Wait-state highest large-move cell: 24 bars / 2 bps, large-move rate `0.922360248447205`, count 322.
- Range-reversion best cell: 24 bars / 2 bps, average forward return `0.009596878596775264`, count 3.

Important segment evidence:

- `NO_TRADE_RISK` is negative into longer horizons: 12-bar average `-0.005546138958708619`, 24-bar average `-0.009093205792206014`.
- `WAIT_COMPRESSION` frequently precedes larger moves: 24-bar large-move rate `0.9233226837060703`, positive rate `0.6293929712460063`.
- `SCALP_ONLY` behaves like a short-horizon state: 3-bar average `0.0015753785894020399`, but 24-bar average `-0.016178148172209892`.
- `BREAKOUT_SETUP` is not directly executable in this sample: 12-bar average `-0.006790765403596906`, 24-bar average `-0.015159368153442512`, count 9.
- `TREND_CONTINUATION` and `BREAKOUT_CONFIRMATION` had zero rows in this BNBUSDT 1h sample, so they need broader-sample validation.

Interpretation:

- 7C confirms the state-machine separation is directionally useful.
- Risk/no-trade is doing useful defensive filtering in longer horizons.
- Wait/compression should be a watcher state, not a direct entry state.
- Scalping should remain short-horizon only; carrying it into 12/24 bars is harmful in this sample.
- Breakout setup needs a confirmation trigger before execution.
- The next design step is to add transition validation: WAIT_COMPRESSION → BREAKOUT_SETUP → BREAKOUT_CONFIRMATION, and to broaden validation across assets/timeframes.

Validation:

- Phase 7 tests: 14 passed.
- `py_compile` passed for the outcome module, CLI, and tests.

### 7D. Playbook state-transition validation — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_state_transitions`.
- `libs.models.regime_v2.scripts.report_playbook_state_transitions`.
- `tests/test_regime_v2_playbook_state_transitions.py`.
- Generated `research/regime_v2_phase7d_state_transitions.json` and `.md`.

Purpose:

- Validate transitions between 7B states, not only state buckets.
- Evaluate transition offsets 1, 3, and 6 bars.
- Evaluate outcome horizons 3, 6, 12, and 24 bars.
- Identify transition intents such as compression-to-setup, setup-to-confirmation, risk recovery, scalp exit, and range invalidation.
- Keep the validation offline; no live policy or selection changes.

Initial BNBUSDT 1h result:

- Cells: 12.
- Transition bars: 1, 3, 6.
- Outcome horizons: 3, 6, 12, 24.
- Best intentful transition cell: transition 6 bars / outcome 3 bars, average return `0.0017722753028159214`, count 99.
- Best risk-recovery cell: transition 6 bars / outcome 24 bars, average return `0.001959434528876435`, count 58.
- Best setup cell: transition 1 bar / outcome 3 bars, average return `-0.0017225533429926375`, count 9.
- Highest wait large-move cell: transition 1 bar / outcome 24 bars, large-move rate `0.922360248447205`, count 322.
- Worst scalp-exit cell: transition 3 bars / outcome 24 bars, average return `-0.015679647844386704`, count 24.

Important transition evidence:

- `WAIT_COMPRESSION -> BREAKOUT_SETUP` is rare but meaningful: 6-bar transition / 24-bar outcome had count 4, average return `0.013895753386699563`, positive rate `0.75`, and large-move rate `1.0`.
- `BREAKOUT_SETUP -> BREAKOUT_CONFIRMATION` had zero rows, so confirmation is not yet being generated by current deterministic rules.
- `BREAKOUT_SETUP -> any` is negative across the current sample, confirming setup alone should not execute.
- `SCALP_ONLY -> exit` is strongly negative at longer horizons: 3-bar transition / 24-bar outcome average `-0.015679647844386704`, positive rate `0.16666666666666666`.
- `NO_TRADE_RISK -> recovery` is mildly positive, especially at 6-bar transition / 24-bar outcome with average `0.001959434528876435` and positive rate `0.5862068965517241`.
- `RANGE_REVERSION -> WAIT_COMPRESSION` exists but has only 3 rows, so it is not decision-ready.

Interpretation:

- 7D supports a transition-based controller rather than a direct state-to-trade mapper.
- Compression should first become setup, then require a separate confirmation trigger before execution.
- Scalp states need short-horizon exits and should not be held into 12/24 bars.
- Risk recovery is a candidate watcher transition, not yet an execution state.
- The missing confirmation rows are the biggest gap in the current deterministic design.

Validation:

- Phase 7 tests: 17 passed.
- `py_compile` passed for the transition module, CLI, and tests.

### 7E. Breakout-confirmation refinement prototype — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_breakout_confirmation`.
- `libs.models.regime_v2.scripts.report_breakout_confirmation`.
- `tests/test_regime_v2_breakout_confirmation.py`.
- Generated `research/regime_v2_phase7e_bconf.json` and `.md`.
- Generated `research/regime_v2_phase7e_bconf_outcomes.json` and `.md`.

Purpose:

- Create an offline refinement layer that can promote eligible `BREAKOUT_SETUP` or `WAIT_COMPRESSION` rows into `BREAKOUT_CONFIRMATION`.
- Use deterministic evidence only: displacement score, close hold beyond channel, follow-through, volume expansion, range expansion, retest evidence, false-break risk, and shock risk.
- Validate whether the resulting confirmation rows are outcome-ready before touching policy or selection.

Initial BNBUSDT 1h result:

- Rows: 720.
- Eligible rows: 326.
- Confirmation rows: 7.
- Promoted rows: 7.
- Confirmation rate: `0.009722222222222222`.
- Average confirmation score: `0.048374230094299954`.
- Average confirmed score: `0.390411421685517`.
- Confirmation directions: 5 up, 2 down.

Refined state distribution:

- `BREAKOUT_CONFIRMATION`: 7.
- `BREAKOUT_SETUP`: 6.
- `WAIT_COMPRESSION`: 313.
- `NO_TRADE_RISK`: 351.
- `SCALP_ONLY`: 40.
- `RANGE_REVERSION`: 3.

Outcome validation for confirmation rows:

- 3-bar average: `-0.0020902343167903794`, positive rate `0.2857142857142857`.
- 6-bar average: `-0.004864640201891429`, positive rate `0.2857142857142857`.
- 12-bar average: `-0.003823946372196533`, positive rate `0.42857142857142855`.
- 24-bar average: `-0.006392824518556282`, positive rate `0.42857142857142855`.

Threshold sensitivity:

- Min score `0.35`: 7 confirmation rows, all horizon averages negative.
- Min score `0.40`: 3 confirmation rows, all horizon averages worse.
- Min score `0.45+`: zero confirmation rows.

Interpretation:

- The prototype successfully creates confirmation rows, but the current confirmation formula is not outcome-ready.
- The problem is not just a loose threshold; stricter thresholds remove rows or worsen outcomes.
- Current confirmation evidence identifies high-movement rows, but not favorable directional follow-through.
- Do not use this confirmation layer for policy gating yet.
- Next work should redesign confirmation around directional hold/retest-follow-through quality, not only displacement/volume/range expansion.

Validation:

- Phase 7 tests including 7E: 20 passed.
- `py_compile` passed for the confirmation module, CLI, and tests.

### 7F. Direction-aware breakout follow-through redesign — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_breakout_followthrough`.
- `libs.models.regime_v2.scripts.report_breakout_followthrough`.
- `tests/test_regime_v2_breakout_followthrough.py`.
- Generated `research/regime_v2_phase7f_breakout_followthrough.json` and `.md`.
- Generated `research/regime_v2_phase7f_breakout_followthrough_outcomes.json` and `.md`.

Purpose:

- Fix the Phase 7E issue where confirmation detected movement but not favorable direction.
- Score up/down breakout follow-through separately.
- Validate confirmation rows using directional net return after fees.
- Keep the refinement offline; no live policy or selection changes.

Initial BNBUSDT 1h result:

- Rows: 720.
- Eligible rows: 327.
- Active follow-through rows: 10.
- Active rate: `0.013888888888888888`.
- Average active score: `0.4006762357278467`.
- Directions: 5 up, 5 down.

Refined state distribution:

- `BREAKOUT_CONFIRMATION`: 10.
- `BREAKOUT_SETUP`: 6.
- `WAIT_COMPRESSION`: 311.
- `NO_TRADE_RISK`: 350.
- `SCALP_ONLY`: 40.
- `RANGE_REVERSION`: 3.

Directional outcome matrix:

- Cells: 12.
- Passing cells: 8 / 12.
- Best cell: 3 bars / 2 bps, average directional net return `0.0024247430657479236`, positive rate `0.5`, count 10.
- Worst cell: 24 bars / 10 bps, average directional net return `-0.00025770518368077946`, positive rate `0.6`, count 10.

Important outcome evidence:

- 3-bar directional net return is positive across all fee cells: `0.0024247430657479236`, `0.0021247430657479237`, `0.0016247430657479235`.
- 6-bar directional net return is positive at 2 and 5 bps, slightly negative at 10 bps.
- 12-bar directional net return is positive across all fee cells with positive rate `0.7`.
- 24-bar directional net return is positive at 2 and 5 bps, slightly negative at 10 bps.
- Raw average forward return remains negative, which confirms that direction adjustment is essential.

Comparison to Phase 7E:

- 7E confirmation rows had negative average outcomes at every horizon.
- 7F direction-aware rows improve the picture materially: 8/12 cells pass and the worst cell is only slightly negative.
- This is not live-ready because support is only 10 rows, but it is directionally promising.

Interpretation:

- The Phase 7F design is a better confirmation shape than 7E.
- Breakout confirmation must be direction-aware and validated against directional returns.
- The next step should be robustness validation across assets/timeframes and threshold variants, not live policy integration.

Validation:

- Phase 7 tests including 7F: 23 passed.
- `py_compile` passed for the follow-through module, CLI, and tests.

### 7G. Follow-through robustness matrix — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_ft_matrix`.
- `libs.models.regime_v2.scripts.report_ft_matrix`.
- `tests/test_regime_v2_ft_matrix.py`.
- Generated `research/regime_v2_phase7g_ft_matrix.json` and `.md`.

Purpose:

- Validate the Phase 7F direction-aware follow-through rule across thresholds, pairs, horizons, and fees.
- Default pairs: `BNBUSDT|1h`, `BTCUSDT|4h`, `ETHUSDT|4h`, and `SOLUSDT|4h`.
- Thresholds: `0.20`, `0.25`, `0.30`, and `0.35`.
- Horizons: 3, 6, 12, and 24 bars.
- Fees: 2, 5, and 10 bps.
- Keep this offline; no policy or selection changes.

Initial multi-pair result:

- Variants: 16.
- Pairs: 4.
- Ready variants: 2.
- Ready pair distribution: `BNBUSDT|1h` only.
- Best variant: `BNBUSDT|1h`, threshold `0.25`.
- Best-ready variant: `BNBUSDT|1h`, threshold `0.25`.
- Recommendation in generated report: `candidate_found`.

Best BNBUSDT 1h variant:

- Threshold: `0.25`.
- Active rows: 10.
- Direction split: 5 up, 5 down.
- Passing cells: 8 / 12.
- Average directional net return: `0.0008296337916352706`.
- Worst directional net return: `-0.00025770518368077946`.
- Best cell: 3 bars / 2 bps, average directional net return `0.0024247430657479236`.
- Worst cell: 24 bars / 10 bps, average directional net return `-0.00025770518368077946`.

Threshold sensitivity on BNBUSDT 1h:

- Threshold `0.20`: active 14, fails due low passing rate, negative average return, and worst-cell loss.
- Threshold `0.25`: active 10, passes local criteria.
- Threshold `0.30`: active 10, passes local criteria with same row set as `0.25`.
- Threshold `0.35`: active 6, better average but fails support.

Cross-asset result:

- BTCUSDT 4h: all threshold variants fail, average directional returns negative.
- ETHUSDT 4h: all threshold variants fail, average directional returns negative.
- SOLUSDT 4h: all threshold variants fail, average directional returns negative.

Interpretation:

- 7G upgrades 7F from a single-run result into a threshold/pair robustness check.
- The rule is promising only as a local `BNBUSDT|1h` candidate.
- It is not a broad multi-asset breakout confirmation rule.
- Do not integrate it into live policy or generic RegimeV2 gating.
- Next step should either collect more BNBUSDT 1h out-of-sample data or make the follow-through rule asset/timeframe-conditioned before wider validation.

Validation:

- Phase 7 tests including 7G: 26 passed.
- `py_compile` passed for the 7G matrix module, CLI, and tests.

### 7H. Follow-through walk-forward validation — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_ft_wf`.
- `libs.models.regime_v2.scripts.report_ft_wf`.
- `tests/test_regime_v2_ft_wf.py`.
- Generated `research/regime_v2_phase7h_ft_wf.json` and `.md`.

Purpose:

- Validate whether the local `BNBUSDT|1h` Phase 7F/7G candidate survives chronological walk-forward splits.
- Test thresholds `0.25` and `0.30`.
- Use 4 chronological splits over the 720-row sample.
- Use horizons 3, 6, 12, and 24 bars with fees 2, 5, and 10 bps.
- Keep this offline; no policy or selection changes.

Initial BNBUSDT 1h result:

- Input rows: 720.
- Thresholds: `0.25` and `0.30`.
- Both thresholds produced the same active row set.
- Active total: 10.
- Direction split: 5 up, 5 down.
- Passed splits: 2 / 4.
- Failed splits: 2 / 4.
- Recommendation: `hold_off_walkforward_unstable`.

Split results for threshold `0.25` and `0.30`:

- Split 1: active 2, passed 12 / 12 cells, average directional return `0.004423758027398304`, worst cell `0.0003227611267069431`.
- Split 2: active 2, passed 0 / 12 cells, average directional return `-0.005686912938308922`, worst cell `-0.00765301617323444`.
- Split 3: active 3, passed 9 / 12 cells, but average directional return `-0.00033636635900216166` and worst cell `-0.009083108104077217`.
- Split 4: active 3, passed 10 / 12 cells, average directional return `0.003943915605060142`, worst cell `0.0012712894336871581`.

Interpretation:

- 7H invalidates immediate promotion of the BNBUSDT 1h follow-through candidate.
- 7G looked locally promising, but the signal is not chronologically stable.
- The instability is not caused by low support; every split met the minimum support floor.
- The failure is outcome quality in the middle windows, especially split 2 and the 24-bar worst cell in split 3.
- Threshold `0.25` and `0.30` are equivalent on this sample.
- Do not integrate 7F into policy or selection yet.

Next design direction:

- Add failure-window diagnostics for splits 2 and 3.
- Identify whether failures are direction-specific, horizon-specific, or caused by false continuation after breakout.
- Consider adding a post-confirmation invalidation/cooldown rule before any new robustness pass.

Validation:

- Phase 7 tests including 7H: 29 passed.
- `py_compile` passed for the 7H walk-forward module, CLI, and tests.

### 7I. Follow-through failure-window diagnostics — implemented

Implemented:

- `libs.models.regime_v2.evaluation.playbook_ft_diag`.
- `libs.models.regime_v2.scripts.report_ft_diag`.
- `tests/test_regime_v2_ft_diag.py`.
- Generated `research/regime_v2_phase7i_ft_diag.json` and `.md`.

Purpose:

- Diagnose why the Phase 7H walk-forward candidate fails in splits 2 and 3.
- Inspect failed windows by direction, horizon, fee, follow-through features, reversal pressure, and worst cells.
- Keep this offline; no policy or selection changes.

Initial BNBUSDT 1h result:

- Thresholds: `0.25` and `0.30`.
- Target failed splits: 2 and 3.
- Dominant hypotheses across target splits:
  - `long_horizon_directional_failure`: 4.
  - `large_worst_cell_loss`: 4.
  - `direction_specific_failure:down`: 2.
  - `direction_specific_failure:up`: 2.
  - `high_reversal_pressure`: 2.
  - `short_horizon_directional_failure`: 2.
- Matrix recommendation: `add_invalidation_or_context_filter_before_retest`.
- Per-threshold recommendation: `add_direction_specific_invalidation_filter`.

Split 2 diagnosis:

- Active rows: 2.
- Directions: 1 up, 1 down.
- Short-horizon average directional return: `-0.00544780527594638`.
- Long-horizon average directional return: `-0.005926020600671461`.
- Worst cell: 12 bars / 10 bps, average `-0.00765301617323444`.
- Reversal penalty: `0.6666666666666666`.
- Hold score: `0.5`.
- Follow score: `1.0`.
- Direction return score: `1.0`.
- Main failure: down confirmation failed badly, with direction average `-0.011987517710004397` and positive rate `0.0`.

Split 3 diagnosis:

- Active rows: 3.
- Directions: 2 up, 1 down.
- Short-horizon average directional return: `0.003122931133411381`.
- Long-horizon average directional return: `-0.0037956638514157043`.
- Worst cell: 24 bars / 10 bps, average `-0.009083108104077217`.
- Reversal penalty: `0.3333333333333333`.
- Hold score: `0.8333333333333334`.
- Follow score: `1.0`.
- Direction return score: `0.824794186870335`.
- Main failure: up confirmations decayed at long horizon, with up direction average `-0.009043207493242297` while down was strongly positive.

Interpretation:

- Split 2 is a true reversal-pressure failure, especially on down confirmations.
- Split 3 is not an immediate confirmation failure; it is a long-horizon decay problem, especially for up confirmations.
- The candidate needs an invalidation/cooldown layer before another robustness run.
- The next rule should not simply raise the threshold; 0.25 and 0.30 produce nearly the same failure profile.
- Candidate remains offline-only and not policy-ready.

Next design direction:

- Add a Phase 7J invalidation filter candidate using reversal pressure and direction-specific decay.
- Candidate should test whether filtering high reversal-pressure rows and limiting long-horizon exposure improves walk-forward stability.
- The filter must be evaluated offline first across the same split/horizon/fee grid.

Validation:

- Phase 7 tests including 7I: 32 passed.
- `py_compile` passed for the 7I diagnostics module, CLI, and tests.

Only after deterministic RegimeV2 has stable downstream logs.

Allowed scope:

- Contextual bandit/scorer as a challenger policy.
- Offline weekly retraining only.
- Never bypass hard risk gates.
- Must beat deterministic RegimeV2 out-of-sample before promotion.

Initial features:

- Regime evidence columns.
- Policy scores.
- Candidate model metadata.
- Market context.
- Realized net outcomes after fees/slippage.

## Stop Conditions

Hold RegimeV2 disabled if:

- Benefits only appear at zero-fee assumptions.
- One symbol/timeframe explains most gains.
- Lift is unstable across rolling windows.
- RegimeV2 increases conflict picks or reduces win rate materially.
- Shadow logs show stale/missing payloads or high data-quality degradation.
