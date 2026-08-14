from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.decision_app.identity import (
    binding_config_fingerprint,
    decision_id,
    effective_lane_revision,
    make_binding_id,
    sha256_fingerprint,
)

AS_OF = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)


def test_fingerprint_is_stable_across_mapping_and_sequence_representation() -> None:
    first = {"thresholds": {"upper": 2, "lower": 1}, "features": ["a", "b"]}
    second = {"features": ("a", "b"), "thresholds": {"lower": 1, "upper": 2}}
    assert sha256_fingerprint(first) == sha256_fingerprint(second)
    assert binding_config_fingerprint(first) == binding_config_fingerprint(second)


def test_configuration_and_policy_changes_change_their_identities() -> None:
    binding_a = binding_config_fingerprint({"threshold": 1})
    binding_b = binding_config_fingerprint({"threshold": 2})
    assert binding_a != binding_b

    revision_a = effective_lane_revision(
        "BTCUSDT:1h",
        {"bindings": ["boundary"]},
        {"policy": "single"},
    )
    revision_b = effective_lane_revision(
        "BTCUSDT:1h",
        {"bindings": ["boundary"]},
        {"policy": "ensemble"},
    )
    assert revision_a != revision_b
    assert decision_id(
        lane_id="BTCUSDT:1h", lane_revision=revision_a, market_as_of=AS_OF
    ) != decision_id(
        lane_id="BTCUSDT:1h",
        lane_revision=revision_b,
        market_as_of=AS_OF,
    )

    identity_a = make_binding_id(
        lane_id="BTCUSDT:1h",
        slot_name="boundary",
        plugin_name="BoundaryModel",
        plugin_version="1",
        binding_fingerprint=binding_a,
    )
    identity_b = make_binding_id(
        lane_id="BTCUSDT:1h",
        slot_name="boundary",
        plugin_name="BoundaryModel",
        plugin_version="2",
        binding_fingerprint=binding_a,
    )
    assert identity_a != identity_b


def test_identity_rejects_ambiguous_or_unstable_values() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        sha256_fingerprint({"value": float("nan")})
    with pytest.raises(TypeError, match="unordered sets"):
        sha256_fingerprint({"value": {"a", "b"}})
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        decision_id(
            lane_id="BTCUSDT:1h",
            lane_revision="revision",
            market_as_of=AS_OF.replace(tzinfo=None),
        )


def test_binding_id_is_repeatable() -> None:
    fingerprint = binding_config_fingerprint({"alpha": 1, "beta": [2, 3]})
    values = {
        make_binding_id(
            lane_id="BTCUSDT:1h",
            slot_name="boundary",
            plugin_name="BoundaryModel",
            plugin_version="1",
            binding_fingerprint=fingerprint,
        )
        for _ in range(4)
    }
    assert len(values) == 1
