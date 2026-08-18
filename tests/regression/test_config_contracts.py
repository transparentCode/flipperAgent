"""Current-owned canonical regression configuration evidence."""

from pathlib import Path

import pytest

from libs.regression.channel import channel_config_fingerprint
from libs.regression.config.resolver import ConfigResolver

_YAML_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)


def _resolver() -> ConfigResolver:
    return ConfigResolver.from_yaml(str(_YAML_PATH))


def test_canonical_yaml_loads_from_package_path() -> None:
    resolver = _resolver()
    assert resolver.resolve("BTCUSDT", "1h").asset == "BTCUSDT"
    assert resolver.resolve("BTCUSDT", "1h").timeframe == "1h"


def test_btcusdt_1h_source_identity_is_preserved() -> None:
    config = _resolver().resolve("BTCUSDT", "1h")

    assert config.window_size == 73
    assert config.config_hash == "30d530f70382"


def test_btcusdt_4h_source_identity_is_preserved() -> None:
    config = _resolver().resolve("BTCUSDT", "4h")

    assert config.config_hash == "218fd7f91880"


def test_resolver_cache_and_hashing_are_deterministic() -> None:
    resolver = _resolver()
    first = resolver.resolve("BTCUSDT", "1h")
    assert first is resolver.resolve("BTCUSDT", "1h")

    resolver._cache.clear()
    second = resolver.resolve("BTCUSDT", "1h")
    assert first == second
    assert first.config_hash == second.config_hash == "30d530f70382"


def test_structural_channel_policy_is_strict_and_canonical() -> None:
    resolver = _resolver()
    policy = resolver.structural_channel_config

    assert (policy.inner_coverage, policy.outer_coverage) == (0.68, 0.95)
    assert (
        channel_config_fingerprint(policy)
        == "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"
    )


@pytest.mark.parametrize(
    "raw_policy",
    (
        {"inner_coverage": 0.68},
        {"inner_coverage": 0.68, "outer_coverage": 0.95, "extra": True},
    ),
)
def test_structural_channel_policy_rejects_missing_or_unexpected_keys(
    raw_policy: dict,
) -> None:
    with pytest.raises(ValueError, match="structural_channel must contain exactly"):
        ConfigResolver.from_dict({"structural_channel": raw_policy})


def test_channel_identity_is_independent_of_source_config_hash() -> None:
    base = {
        "structural_channel": {"inner_coverage": 0.68, "outer_coverage": 0.95},
        "global": {"default_window_size": 73},
    }
    changed_source = {
        **base,
        "global": {"default_window_size": 74},
    }

    first = ConfigResolver.from_dict(base)
    second = ConfigResolver.from_dict(changed_source)
    first_config = first.resolve("BTCUSDT", "1h")
    second_config = second.resolve("BTCUSDT", "1h")

    assert first_config.config_hash != second_config.config_hash
    assert channel_config_fingerprint(
        first.structural_channel_config
    ) == channel_config_fingerprint(second.structural_channel_config)
