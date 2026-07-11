from __future__ import annotations

import pytest

from libs.models.regime_v2.config import timeframe_scaled_config
from libs.models.regime_v2.optimization import (
    extract_profile_defaults,
    get_optimization_param_schema,
    list_optimization_profiles,
    params_to_overrides,
    post_process_params,
)


class TestRegimeV2OptimizationProfiles:
    def test_profile_catalog_exposes_expected_names(self):
        profiles = list_optimization_profiles()

        assert set(profiles) == {"core", "windows", "fusion", "policy", "full"}
        assert "Default first-pass search space" in profiles["core"]

    def test_core_schema_uses_runtime_defaults(self):
        schema = get_optimization_param_schema("1h", profile="core")
        cfg = timeframe_scaled_config("1h")

        assert schema["trend.fast_ema"].default == cfg.trend.fast_ema
        assert schema["breaks.breakout_window"].default == cfg.breaks.breakout_window
        assert schema["fusion.trend_threshold"].default == cfg.fusion.trend_threshold
        assert schema["policy.min_confidence"].default == cfg.policy.min_confidence

    def test_window_schema_scales_with_timeframe_defaults_and_bounds(self):
        schema = get_optimization_param_schema("4h", profile="windows")
        cfg = timeframe_scaled_config("4h")

        assert schema["trend.fast_ema"].default == cfg.trend.fast_ema
        assert schema["trend.fast_ema"].low == 5
        assert schema["trend.fast_ema"].high == 10
        assert schema["trend.fast_ema"].step == 1
        assert schema["breaks.breakout_window"].default == cfg.breaks.breakout_window
        assert schema["breaks.breakout_window"].low == 10

    def test_extract_profile_defaults_matches_schema_defaults(self):
        defaults = extract_profile_defaults("1h", profile="fusion")
        schema = get_optimization_param_schema("1h", profile="fusion")

        assert defaults == {key: pdef.default for key, pdef in schema.items()}

    def test_post_process_params_casts_types_for_runtime_overrides(self):
        processed = post_process_params(
            {
                "trend.fast_ema": 13.7,
                "fusion.trend_threshold": "0.61",
            },
            timeframe="1h",
            profile="core",
        )

        assert processed["trend.fast_ema"] == 14
        assert processed["fusion.trend_threshold"] == pytest.approx(0.61)

    def test_params_to_overrides_rejects_unknown_keys(self):
        with pytest.raises(KeyError):
            params_to_overrides(
                {"policy.unknown": 0.5},
                timeframe="1h",
                profile="policy",
            )

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError):
            get_optimization_param_schema("1h", profile="unknown")  # type: ignore[arg-type]
