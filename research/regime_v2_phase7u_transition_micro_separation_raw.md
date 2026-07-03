# RegimeV2 Phase 7U Transition Micro-Regime Separation

- Variants: 243
- Groups: 3
- Decision: separate_breakout_setup_from_compressed_wait
- Best group: {'phase_group': 'breakout_setup', 'variant_count': 81, 'assets': ['BNBUSDT', 'BTCUSDT', 'ETHUSDT'], 'ready_count': 0, 'promising_count': 6, 'watch_count': 9, 'grade_distribution': {'blocked': 66, 'watch': 9, 'promising': 6}, 'max_post_active_count': 39, 'best_passed_split_count': 3, 'avg_split_directional_return': 0.0027802186339219628, 'best_avg_split_directional_return': 0.007382640965507925, 'worst_split_directional_return': -0.018818934271775577, 'best_worst_split_directional_return': -0.0019351374847817401, 'best_variant': {'asset': 'ETHUSDT', 'timeframe': '1h', 'phase_group': 'breakout_setup', 'grade': 'promising', 'post_active_count': 15, 'supported_split_count': 3, 'passed_split_count': 3, 'split_count': 4, 'avg_split_directional_return': 0.007382640965507925, 'worst_split_directional_return': -0.0019351374847817401, 'blockers': ['total_support_low', 'split_support_low', 'passed_splits_low', 'worst_loss_too_negative'], 'config': {'allowed_directions': ['up', 'down'], 'allowed_market_phases': ['breakout_setup'], 'lookback_bars': 8, 'max_conflict_count': 1, 'max_continuation_score': None, 'max_risk_score': 0.72, 'max_volatility_quantile': 0.85, 'min_attempt_score': 0.5, 'min_candidate_score': 0.62, 'min_context_score': 0.7, 'min_score_gap': 0.0, 'min_wick_score': 0.35}}, 'asset_summary': {'BNBUSDT': {'variant_count': 27, 'best_grade': 'watch', 'max_post_active_count': 39, 'best_passed_split_count': 2, 'best_avg_split_directional_return': 0.0029997781838642275, 'best_worst_split_directional_return': -0.004766930445069356}, 'BTCUSDT': {'variant_count': 27, 'best_grade': 'blocked', 'max_post_active_count': 39, 'best_passed_split_count': 1, 'best_avg_split_directional_return': 0.0037205453606499023, 'best_worst_split_directional_return': -0.006199472918887353}, 'ETHUSDT': {'variant_count': 27, 'best_grade': 'promising', 'max_post_active_count': 18, 'best_passed_split_count': 3, 'best_avg_split_directional_return': 0.007382640965507925, 'best_worst_split_directional_return': -0.0019351374847817401}}, 'recommendation': 'keep_as_research_candidate'}

## Groups

| Group | Variants | Assets | Ready | Promising | Max active | Best passed | Avg split return | Worst split return | Recommendation |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| breakout_setup | 81 | BNBUSDT,BTCUSDT,ETHUSDT | 0 | 6 | 39 | 3 | 0.0027802186339219628 | -0.018818934271775577 | keep_as_research_candidate |
| all | 81 | BNBUSDT,BTCUSDT,ETHUSDT | 0 | 3 | 83 | 3 | 0.0007493417752237013 | -0.028108162456439937 | diagnostic_only |
| compressed_wait | 81 | BNBUSDT,BTCUSDT,ETHUSDT | 0 | 0 | 44 | 2 | -0.0009066273850703485 | -0.04197438881769332 | separate_as_observation_only |

## Asset by group

| Group | Asset | Variants | Best grade | Max active | Best passed | Best avg | Best worst |
|---|---|---:|---|---:|---:|---:|---:|
| breakout_setup | BNBUSDT | 27 | watch | 39 | 2 | 0.0029997781838642275 | -0.004766930445069356 |
| breakout_setup | BTCUSDT | 27 | blocked | 39 | 1 | 0.0037205453606499023 | -0.006199472918887353 |
| breakout_setup | ETHUSDT | 27 | promising | 18 | 3 | 0.007382640965507925 | -0.0019351374847817401 |
| all | BNBUSDT | 27 | watch | 83 | 2 | 0.004587636075841864 | -0.003977057988241181 |
| all | BTCUSDT | 27 | blocked | 71 | 0 | 0.0007623416562533783 | -0.0040799415997798015 |
| all | ETHUSDT | 27 | promising | 61 | 3 | 0.00482404598918966 | -0.0036750222971532417 |
| compressed_wait | BNBUSDT | 27 | watch | 44 | 2 | 0.003053957325049265 | -0.006472525210943193 |
| compressed_wait | BTCUSDT | 27 | blocked | 32 | 0 | -0.0008349306628318265 | -0.012433765390005513 |
| compressed_wait | ETHUSDT | 27 | blocked | 43 | 0 | 0.004676232582096775 | -0.004511152249982155 |
