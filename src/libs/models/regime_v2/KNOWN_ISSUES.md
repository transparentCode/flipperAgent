# RegimeV2 Known Issues / Follow-up Backlog

This file tracks known limitations that are **not current blockers** for offline evaluation, but should be revisited before live promotion.

## 1. Breakout needs downstream validation

RegimeV2 now separates breakout evidence into:

- `pre_breakout_setup_score`
- `displacement_breakout_score`
- `post_breakout_retest_score`

Current stance:

- `pre_breakout_setup_score` is a watchlist/scanner signal, not a direct executable trade permission.
- `displacement_breakout_score` may be useful only when the downstream strategy confirms direction/structure.
- `post_breakout_retest_score` is likely safer for entries but needs evidence.

Open question:

> Which breakout component improves actual trendline / squeeze-breakout / price-action outcomes?

## 2. Mean reversion is active but not yet trusted

Mean reversion was previously over-suppressed. It is now active through compressed-range context, but recent Binance samples showed weak or negative short-horizon IC.

Current stance:

- Keep `policy_mean_reversion_score` available for evaluation.
- Do not let it dominate live selection until downstream ablations prove value.

Open question:

> Is MR useful only for specific assets/timeframes, or only after adding stronger range-bound/retest features?

## 3. Trend is healthier but still conservative

Trend improved after:

- Choppiness normalization fix.
- Softer uncertainty penalty.
- `trend_threshold` and `policy.trend_min_strength` moved from high defaults to `0.48`.

Current stance:

- Conservative trend permission is acceptable for regime filtering.
- Trend should be evaluated by downstream directional returns, not only label frequency.

Open question:

> Does RegimeV2 trend permission improve trend-following, trendline, momentum, or pullback models after fees/slippage?

## 4. Confidence / uncertainty calibration is still heuristic

The current confidence layer is deterministic and heuristic. It is useful for diagnostics but not statistically calibrated.

Future work:

- Add calibration curves against downstream outcomes.
- Track reliability by confidence bucket.
- Consider isotonic or Platt-style calibration after enough labeled strategy outcomes exist.

## 5. No cross-asset/live-context guarantee yet

RegimeV2 can consume existing engineered `eng_*` market-context features, but it has not been validated with full live feature context.

Future work:

- Run downstream ablations with and without market context columns.
- Evaluate BTC dominance / TOTAL3 / breadth impact separately for alts.

## 6. No ML/RL policy yet

RegimeV2 is currently deterministic. This is intentional.

Future work:

- Use downstream ablation logs to train a contextual bandit or scorer.
- Keep any RL/bandit policy as a challenger until it beats deterministic policy out-of-sample.
- Never let RL bypass hard risk gates.

## 7. PriceAction needs separate Phase 4B handling

The full Phase 4B matrix with `PriceAction` included stayed below promotion threshold: 9/16 combos, 56.25% pass rate.

The same matrix excluding `PriceAction` promoted: 10/16 combos, 62.5% pass rate.

Current stance:

- Treat `PriceAction` as a separate candidate family, not part of the first Phase 5 shadow subset.
- Do not assume RegimeV2 failed broadly; the trend + pullback + squeeze subset has enough evidence for a shadow-candidate path.
- Before re-including `PriceAction`, map it to a clearer playbook or validate it with its own thresholds/direction semantics.

Open question:

> Is PriceAction noisy because of the lightweight offline feature approximation, or because it needs its own playbook-specific gate?

## 8. Live enablement remains disabled by default

`configs/models.yaml` keeps:

```yaml
RegimeV2:
  enabled: false
```

Do not enable live usage until Phase 4 downstream ablation shows objective improvement.
