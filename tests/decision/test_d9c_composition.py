from __future__ import annotations

from apps.decision_app.composition import build_production_composition
from apps.decision_app.settings import (
    DecisionConfig,
    DecisionGlobalSettings,
    FeaturePolicySettings,
)
from tests.decision.test_d9b_live_runtime import _sr_config


def test_d9c_production_composition_is_explicit_and_closed() -> None:
    composition = build_production_composition(_sr_config())

    assert [(item.name, item.version) for item in composition.plugin_catalog] == [
        ("sr", "1")
    ]
    assert [
        (item.plugin_name, item.plugin_version)
        for item in composition.runtime_plugin_catalog
    ] == [("sr", "1")]
    assert [item.name for item in composition.feature_catalog] == ["ATR"]
    assert composition.policy_catalog.resolve("passthrough", "1").kind == "passthrough"
    assert composition.policy_catalog.resolve("priority", "1").kind == "priority"
    assert len(composition.data_source_catalog) == 0
    assert composition.data_policy.concepts == {}
    assert composition.feature_policy.allowed_features == ()


def test_d9c_non_default_feature_policy_reaches_shared_composition() -> None:
    original = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            feature_policy=FeaturePolicySettings(
                name="operator-policy",
                version="7",
                allowed_features=("ATR",),
            )
        ),
        assets=original.assets,
        timeframe_grid=original.timeframe_grid,
        instruments=original.instruments,
    )

    composition = build_production_composition(config)

    assert composition.feature_policy.name == "operator-policy"
    assert composition.feature_policy.version == "7"
    assert composition.feature_policy.allowed_features == ("ATR",)
