from __future__ import annotations

import pytest

from libs.models.trendline_family.config import (
    CandidateConfig,
    InteractionConfig,
    LifecycleConfig,
    MatchingConfig,
    MTFConfig,
    ModelConfig,
    RailsConfig,
)
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError


def _resolver(tmp_path, body: str) -> TrendlineFamilyConfigResolver:
    path = tmp_path / "trendline_family.yaml"
    path.write_text(body, encoding="utf-8")
    return TrendlineFamilyConfigResolver.from_path(path)


def test_resolver_applies_documented_precedence_and_provenance(tmp_path) -> None:
    resolver = _resolver(tmp_path, """
version: 1
defaults:
  candidate: {lookback_bars: 200}
timeframes:
  4h:
    candidate: {lookback_bars: 220}
assets:
  BTCUSDT:
    defaults:
      candidate: {lookback_bars: 240}
    timeframes:
      4h:
        candidate: {lookback_bars: 260}
""")
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="4h", runtime_override={"candidate": {"lookback_bars": 280}})
    assert resolved.candidate.lookback_bars == 280
    assert resolved.field_provenance["candidate.lookback_bars"] == "runtime_override"
    assert resolved.field_provenance["candidate.min_bars"] == "schema_fallback"


@pytest.mark.parametrize(("factory", "kwargs", "message"), [
    (ModelConfig, {"enabled": 1}, "boolean"),
    (CandidateConfig, {"lookback_bars": True}, "integer"),
    (CandidateConfig, {"min_candidate_quality": "0.4"}, "numeric"),
    (CandidateConfig, {"birth_quality_threshold": 0.2, "min_candidate_quality": 0.3}, "birth_quality"),
    (MatchingConfig, {"minimum_match_score": 1.1}, "at most"),
    (MatchingConfig, {"level_weight": True}, "numeric"),
    (LifecycleConfig, {"expire_after_bars": False}, "integer"),
    (LifecycleConfig, {"reactivation_min_score": 1.1}, "at most"),
    (InteractionConfig, {"atr_window": "14"}, "integer"),
    (InteractionConfig, {"approaching_distance_atr": 0.1, "tolerance_atr": 0.2}, "approaching"),
    (RailsConfig, {"max_group_slope_delta_atr_per_hour": "0.1"}, "numeric"),
    (RailsConfig, {"minimum_spacing_atr": 0.75, "max_adjacent_gap_atr": 0.75}, "minimum_spacing"),
])
def test_config_sections_reject_wrong_types_and_ranges(factory, kwargs, message) -> None:
    with pytest.raises(ContractValidationError, match=message):
        factory(**kwargs)


@pytest.mark.parametrize("body", [
    "version: true\n",
    "version: []\n",
    "version: 1\ndefaults:\n  candidate:\n    unknown: true\n",
    "version: 1\ndefaults: []\n",
    "version: 1\ndefaults:\n  candidate:\n    lookback_bars: true\n",
    "version: 1\nmodel:\n  enabled: 1\n",
])
def test_resolver_rejects_invalid_yaml_shapes_and_scalars(tmp_path, body) -> None:
    with pytest.raises(ContractValidationError):
        _resolver(tmp_path, body).resolve(asset="BTCUSDT", timeframe="4h")


def test_resolved_config_hash_is_stable_and_input_sensitive(tmp_path) -> None:
    first = _resolver(tmp_path, "version: 1\ndefaults:\n  interaction:\n    tolerance_atr: 0.25\n")
    result = first.resolve(asset="ETHUSDT", timeframe="1h")
    assert result.resolved_config_hash == first.resolve(asset="ETHUSDT", timeframe="1h").resolved_config_hash
    changed = _resolver(tmp_path, "version: 1\ndefaults:\n  interaction:\n    tolerance_atr: 0.30\n").resolve(asset="ETHUSDT", timeframe="1h")
    assert result.resolved_config_hash != changed.resolved_config_hash


def test_rail_settings_follow_normal_override_precedence(tmp_path) -> None:
    resolver = _resolver(tmp_path, """
version: 1
defaults:
  rails: {max_adjacent_gap_atr: 0.40}
timeframes:
  4h:
    rails: {max_adjacent_gap_atr: 0.30}
""")

    resolved = resolver.resolve(
        asset="BTCUSDT",
        timeframe="4h",
        runtime_override={"rails": {"max_adjacent_gap_atr": 0.20}},
    )

    assert resolved.rails.max_adjacent_gap_atr == 0.20
    assert resolved.field_provenance["rails.max_adjacent_gap_atr"] == "runtime_override"


def test_runtime_override_is_strictly_validated(tmp_path) -> None:
    with pytest.raises(ContractValidationError, match="integer"):
        _resolver(tmp_path, "version: 1\n").resolve(asset="BTCUSDT", timeframe="4h", runtime_override={"candidate": {"lookback_bars": True}})


def test_enabled_mtf_requires_nonempty_unique_duration_allowlist() -> None:
    assert MTFConfig().source_timeframes == ()
    with pytest.raises(ContractValidationError, match="must not be empty"):
        MTFConfig(enabled=True)

    for aliases in (("1h", "60m"), ("1d", "24h"), ("1w", "7d")):
        with pytest.raises(ContractValidationError, match="equivalent-duration"):
            MTFConfig(enabled=True, source_timeframes=aliases)

    config = MTFConfig(enabled=True, source_timeframes=("1d", "4h", "1h"))
    assert config.source_timeframes == ("1h", "4h", "1d")


def test_resolver_deep_copies_caller_owned_config() -> None:
    raw_config = {"version": 1, "defaults": {"candidate": {"lookback_bars": 240}}}
    resolver = TrendlineFamilyConfigResolver(raw_config)
    raw_config["defaults"]["candidate"]["lookback_bars"] = 999

    assert resolver.resolve(asset="BTCUSDT", timeframe="4h").candidate.lookback_bars == 240
