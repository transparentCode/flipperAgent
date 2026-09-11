from __future__ import annotations

from copy import deepcopy

import pytest

from libs.models.sr_v2.config import (
    SRV2ConfigError,
    SRV2ConfigResolver,
    load_sr_v2_yaml,
)


def test_config_resolves_exact_ladder_and_catalog_owned_history(sr_v2_config):
    assert sr_v2_config.ladder == ("1d", "6h", "4h", "1h", "30m", "15m")
    assert dict(sr_v2_config.history_requirements()) == {
        "1d": 21,
        "6h": 21,
        "4h": 21,
        "1h": 21,
        "30m": 21,
        "15m": 21,
    }
    assert tuple(item.identifier for item in sr_v2_config.kernels) == (
        "previous_period_anchor@1",
        "plateau_sweep_reclaim@1",
    )


def test_config_rejects_unknown_root_and_legacy_forecast_keys():
    raw = load_sr_v2_yaml("configs/sr_v2.yaml")
    with pytest.raises(SRV2ConfigError, match="unknown"):
        SRV2ConfigResolver({**raw, "unexpected": True}).resolve()
    with pytest.raises(SRV2ConfigError, match="unknown"):
        SRV2ConfigResolver({**raw, "forecast": {}}).resolve()


def test_config_accepts_a_yaml_selected_ladder_without_code_ladder_duplication():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    ladder = ["1d", "4h", "1h", "15m"]
    raw["runtime"]["ladder"] = ladder
    for kernel in raw["kernels"].values():
        kernel["timeframes"] = {
            timeframe: kernel["timeframes"][timeframe] for timeframe in ladder
        }
    resolved = SRV2ConfigResolver(raw).resolve()
    assert resolved.ladder == tuple(ladder)
    assert resolved.trigger_timeframe == "15m"


def test_config_alignment_uses_the_yaml_selected_trigger():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    ladder = ["1d", "4h", "1h"]
    raw["runtime"]["ladder"] = ladder
    raw["runtime"]["trigger_timeframe"] = "1h"
    for kernel in raw["kernels"].values():
        kernel["timeframes"] = {
            timeframe: kernel["timeframes"][timeframe] for timeframe in ladder
        }
    raw["lifecycle"]["expiry"] = "90d"
    resolved = SRV2ConfigResolver(raw).resolve()
    assert resolved.trigger_duration.total_seconds() == 3600


@pytest.mark.parametrize(
    "ladder,trigger",
    [
        (["1d", "4h", "1h", "1h"], "1h"),
        (["1d", "6h", "4h", "1h", "30m", "5m"], "5m"),
        (["1d", "6h", "4h"], "4h"),
        ([], "15m"),
    ],
)
def test_config_rejects_invalid_yaml_ladder(ladder, trigger):
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["runtime"]["ladder"] = ladder
    raw["runtime"]["trigger_timeframe"] = trigger
    with pytest.raises(SRV2ConfigError, match="ladder|multiple"):
        SRV2ConfigResolver(raw).resolve()


def test_config_rejects_missing_or_extra_kernel_parameters():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["kernels"]["previous_period_anchor@1"]["timeframes"]["15m"].pop("atr_period")
    with pytest.raises(ValueError, match="missing"):
        SRV2ConfigResolver(raw).resolve()
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    raw["kernels"]["previous_period_anchor@1"]["timeframes"]["15m"]["surprise"] = 1
    with pytest.raises(ValueError, match="unknown"):
        SRV2ConfigResolver(raw).resolve()


def test_any_behavioral_lifecycle_value_changes_identity():
    raw = deepcopy(load_sr_v2_yaml("configs/sr_v2.yaml"))
    baseline = SRV2ConfigResolver(raw).resolve()
    raw["lifecycle"]["break_buffer_atr"] = 0.75
    changed = SRV2ConfigResolver(raw).resolve()
    assert changed.config_fingerprint != baseline.config_fingerprint
    assert changed.break_buffer_atr != baseline.break_buffer_atr


def test_checked_in_state_capacity_changes_model_identity_only():
    raw = load_sr_v2_yaml("configs/sr_v2.yaml")
    resolved = SRV2ConfigResolver(raw).resolve()
    previous_raw = deepcopy(raw)
    previous_raw["state_bounds"]["active_lineages"] = 512
    previous = SRV2ConfigResolver(previous_raw).resolve()

    assert (resolved.max_active_lineages, resolved.max_terminal_tombstones) == (
        1024,
        512,
    )
    assert (
        resolved.config_fingerprint
        == "c38c37bf4ac877056976f908b1d3106eb1dbbea979e3bf0fe89d0302adb732bd"
    )
    assert resolved.config_fingerprint != previous.config_fingerprint
    assert resolved.catalog_fingerprint == previous.catalog_fingerprint
