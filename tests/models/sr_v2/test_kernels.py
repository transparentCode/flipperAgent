from __future__ import annotations

import pytest

from libs.models.sr_v2.kernels.registry import KERNEL_CATALOG


def test_catalog_evaluates_both_kernels_and_records_exact_consumed_rows(
    sr_v2_config,
    sr_v2_bars,
):
    identity = {"venue": "binance_usdm", "instrument_id": "BTCUSDT", "asset": "BTCUSDT"}
    for kernel in sr_v2_config.kernels:
        timeframe = "15m"
        evaluation = kernel.spec.evaluate(
            sr_v2_bars[timeframe],
            market_identity=identity,
            parameters=kernel.parameters_for(timeframe),
        )
        assert evaluation.consumed_feature_rows
        for row in evaluation.consumed_feature_rows:
            assert row["timeframe"] == timeframe
            assert row["kernel_id"] == kernel.kernel_id
            assert row["kernel_version"] == kernel.kernel_version
            assert row["bar_close_at"] == sr_v2_bars[timeframe][-1].bar_close_at
        assert all(item.kernel_id == kernel.kernel_id for item in evaluation.candidates)


def test_kernel_parameters_are_explicit_and_parser_rejects_unknown_or_missing_keys():
    spec = KERNEL_CATALOG["previous_period_anchor@1"]
    with pytest.raises(ValueError, match="unknown|missing"):
        spec.parse_parameters({"enabled": True, "atr_period": 14}, "fixture")
    with pytest.raises(ValueError, match="unknown|missing"):
        spec.parse_parameters(
            {
                "enabled": True,
                "atr_period": 14,
                "zone_half_width_atr": 0.25,
                "default": 1,
            },
            "fixture",
        )


def test_unknown_kernel_fails_closed():
    with pytest.raises(KeyError):
        KERNEL_CATALOG["does_not_exist@1"]
