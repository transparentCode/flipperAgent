# Trendline Family Configuration

The canonical semantic source remains [`configs/trendline_family.yaml`](../trendline_family.yaml) for this makeover. There is no second editable model file. The canonical loader lives under `libs.models.trendline.configuration`; the integration loader is a forwarding seam.

Resolution precedence remains:

```text
schema compatibility fallback
-> YAML model/global
-> YAML defaults
-> equally specific asset or timeframe values
-> explicit asset-timeframe resolution
-> typed research/invocation override
```

Asset and timeframe values at equal specificity may coexist when they address different fields or agree. A differing value for the same field requires an asset-timeframe entry. The production canonical YAML is checked for complete semantic ownership. Sparse mappings remain supported only as the documented schema-compatibility and isolated-test path.

`model.enabled` remains deployment activation metadata and `model.model_version` remains release-contract metadata. Their existing runtime and hash behavior is intentionally unchanged. Runtime-only backend controls, derived values, exchange metadata, and tick size are not semantic YAML fields.

Derived values are exposed by `derive_configuration` and are not writable through YAML: canonical timeframe duration, minimum warm-up bars, and maximum historical horizon. Runtime execution controls are intentionally absent until an execution backend requires them.

## Field policy

| field | owner section | classification | allowed scopes | semantic | default source | derivation source | hash participation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `model.enabled` | model | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `model.model_version` | model | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.pivot_provider` | candidate | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.fitter` | candidate | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.lookback_bars` | candidate | timeframe | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.min_bars` | candidate | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.fractal_left_bars` | candidate | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.fractal_right_bars` | candidate | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.min_pivots_per_side` | candidate | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.min_candidate_quality` | candidate | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `candidate.birth_quality_threshold` | candidate | asset | asset, asset_timeframe, global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.normalization_atr_window` | matching | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.max_distance_atr` | matching | asset_timeframe | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.max_slope_delta_atr_per_hour` | matching | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.minimum_match_score` | matching | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.level_weight` | matching | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.slope_weight` | matching | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.anchor_weight` | matching | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `matching.role_weight` | matching | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.active_grace_bars` | lifecycle | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.dormant_after_bars` | lifecycle | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.expire_after_bars` | lifecycle | timeframe | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.confidence_decay_per_unmatched_bar` | lifecycle | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.reactivation_min_score` | lifecycle | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `lifecycle.max_active_families_per_role` | lifecycle | global | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `interaction.atr_window` | interaction | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `interaction.tolerance_atr` | interaction | asset_timeframe | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `interaction.approaching_distance_atr` | interaction | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `interaction.minimum_zone_ticks` | interaction | asset | asset, asset_timeframe, global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `interaction.close_confirmation_bars` | interaction | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `events.pressure_min_bars` | events | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `events.rejection_recovery_bars` | events | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `events.retest_window_bars` | events | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `events.retest_confirmation_bars` | events | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `rails.max_group_slope_delta_atr_per_hour` | rails | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `rails.max_adjacent_gap_atr` | rails | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `rails.max_corridor_width_atr` | rails | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `rails.minimum_spacing_atr` | rails | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | tracking |
| `rails.representative_policy` | rails | global | global, research_override | semantic | configs/trendline_family.yaml | - | tracking |
| `mtf.enabled` | mtf | global | global, research_override | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.source_timeframes` | mtf | global | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.minimum_confluence_timeframes` | mtf | global | global, research_override | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.max_source_age_bars` | mtf | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.stale_include_age_bars` | mtf | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.max_level_distance_atr` | mtf | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.max_corridor_separation_atr` | mtf | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.max_slope_delta_atr_per_hour` | mtf | global | asset, asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.intersection_horizon_bars` | mtf | timeframe | asset_timeframe, global, research_override, timeframe | semantic | configs/trendline_family.yaml | - | mtf |
| `mtf.normalization_policy` | mtf | global | global, research_override | semantic | configs/trendline_family.yaml | - | mtf |
