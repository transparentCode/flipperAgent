from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from apps.decision_app.domain.market_state import (
    BarStore,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePolicy,
    compile_feature_bar_store_capacities,
    compile_feature_plan,
    merge_bar_store_capacities,
)
from apps.decision_app.features.regression_context import (
    REGRESSION_CONTEXT_FEATURE_NAME,
    REGRESSION_CONTEXT_FEATURE_VERSION,
    build_regression_context_feature_definition,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from libs.contracts.decision import CausalBarView, FeatureRequirement, ModelSpec
from libs.regression import api as regression_api
from libs.regression.channel import channel_config_fingerprint
from libs.regression.config.resolver import ConfigResolver

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1), "4h": timedelta(hours=4)},
)
CONFIG_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)


def _resolver() -> ConfigResolver:
    return ConfigResolver.from_yaml(str(CONFIG_PATH))


def _canonical_config_mapping() -> dict[str, object]:
    with CONFIG_PATH.open() as handle:
        raw = yaml.safe_load(handle)
    assert isinstance(raw, dict)
    return raw


def _lane_spec(timeframe: str, *, two_bindings: bool = False) -> DecisionLaneSpec:
    bindings = [
        ModelBindingSpec(
            slot_name="a",
            plugin_name="REGRESSION_TEST",
            plugin_version="1",
        )
    ]
    if two_bindings:
        bindings.append(
            ModelBindingSpec(
                slot_name="b",
                plugin_name="REGRESSION_TEST",
                plugin_version="1",
            )
        )
    return DecisionLaneSpec(
        lane_id=f"BTCUSDT:{timeframe}",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe=timeframe,
        trigger_timeframe=timeframe,
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        risk_profile_key="btc-default",
        bindings=tuple(bindings),
    )


def _resolved_lane(timeframe: str, *, two_bindings: bool = False):
    model = ModelSpec(
        name="REGRESSION_TEST",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="REGRESSION_TEST.v1",
        intrinsic_feature_requirements=(
            FeatureRequirement(name=REGRESSION_CONTEXT_FEATURE_NAME),
        ),
    )
    return compile_decision_plan(
        PluginCatalog([model]),
        [_lane_spec(timeframe, two_bindings=two_bindings)],
    ).lanes[0]


def _bar(
    timeframe: str, index: int, *, scale: int = 1, volume: int = 10
) -> CausalBarView:
    duration = GRID.duration(timeframe)
    opened_at = BASE + index * duration
    closed_at = opened_at + duration
    close = Decimal((100 + index) * scale)
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=close - Decimal(scale),
        high=close + Decimal(scale),
        low=close - Decimal(2 * scale),
        close=close,
        volume=Decimal(volume),
        taker_buy_base=Decimal(volume // 2),
        closed=True,
    )


def _environment(
    timeframe: str = "1h",
    *,
    count: int | None = None,
    two_bindings: bool = False,
    price_scale: int = 1,
    volume: int = 10,
):
    resolver = _resolver()
    lane = _resolved_lane(timeframe, two_bindings=two_bindings)
    definition = build_regression_context_feature_definition(resolver)
    catalog = FeatureCatalog([definition])
    policy = FeaturePolicy(
        name="regression-test",
        version="1",
        allowed_features=(REGRESSION_CONTEXT_FEATURE_NAME,),
    )
    plan = compile_feature_plan(lane, catalog, policy, GRID)
    base = compile_bar_store_capacities(
        compile_decision_plan(
            PluginCatalog(
                [
                    ModelSpec(
                        name="REGRESSION_TEST",
                        version="1",
                        stateful=False,
                        output_kind="analytical",
                        produces_artifact_type="REGRESSION_TEST.v1",
                        intrinsic_feature_requirements=(
                            FeatureRequirement(name=REGRESSION_CONTEXT_FEATURE_NAME),
                        ),
                    )
                ]
            ),
            [_lane_spec(timeframe, two_bindings=two_bindings)],
        ),
        GRID,
    )
    feature = compile_feature_bar_store_capacities(
        compile_decision_plan(
            PluginCatalog(
                [
                    ModelSpec(
                        name="REGRESSION_TEST",
                        version="1",
                        stateful=False,
                        output_kind="analytical",
                        produces_artifact_type="REGRESSION_TEST.v1",
                        intrinsic_feature_requirements=(
                            FeatureRequirement(name=REGRESSION_CONTEXT_FEATURE_NAME),
                        ),
                    )
                ]
            ),
            [_lane_spec(timeframe, two_bindings=two_bindings)],
        ),
        [plan],
        catalog,
        GRID,
    )
    store = BarStore(merge_bar_store_capacities(base, feature))
    key = next(key for key in store.series_keys if key.timeframe == timeframe)
    required = (
        count
        if count is not None
        else next(
            iter(plan.history_requirements[REGRESSION_CONTEXT_FEATURE_NAME].values())
        )
    )
    bars = tuple(
        _bar(timeframe, index, scale=price_scale, volume=volume)
        for index in range(required)
    )
    store.append_many(key, bars)
    market_as_of = bars[-1].bar_close_at
    requirements = compile_lane_market_requirements(lane, GRID)
    view = DecisionViewBuilder(store, GRID).build(lane, requirements, market_as_of)
    return resolver, lane, definition, catalog, plan, store, view, bars


def test_regression_history_is_exactly_lane_window_plus_one() -> None:
    resolver = _resolver()
    for timeframe, expected in (("1h", 74), ("4h", 114)):
        lane = _resolved_lane(timeframe)
        definition = build_regression_context_feature_definition(resolver)
        plan = compile_feature_plan(
            lane,
            FeatureCatalog([definition]),
            FeaturePolicy(
                name="regression-test",
                version="1",
                allowed_features=(REGRESSION_CONTEXT_FEATURE_NAME,),
            ),
            GRID,
        )
        key, bars = next(iter(plan.history_requirements[definition.name].items()))
        assert key.timeframe == timeframe
        assert bars == expected
        assert bars != 301


def test_regression_feature_projection_matches_public_r2c_and_provenance() -> None:
    resolver, lane, _definition, catalog, plan, store, view, bars = _environment(
        two_bindings=True
    )
    calls = 0
    original = regression_api.compute_regression_context

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    regression_api.compute_regression_context = counted
    try:
        resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    finally:
        regression_api.compute_regression_context = original

    assert calls == 1
    snapshot = resolution.shared_features[REGRESSION_CONTEXT_FEATURE_NAME]
    assert snapshot.name == REGRESSION_CONTEXT_FEATURE_NAME
    assert snapshot.version == REGRESSION_CONTEXT_FEATURE_VERSION
    assert (
        snapshot.provenance["feature_config_fingerprint"]
        == (plan.feature_config_fingerprints[REGRESSION_CONTEXT_FEATURE_NAME])
    )
    assert snapshot.provenance["projected_decision_bar"] is False
    binding_snapshots = [
        binding.features[REGRESSION_CONTEXT_FEATURE_NAME]
        for binding in resolution.bindings.values()
    ]
    assert binding_snapshots[0] is binding_snapshots[1] is snapshot

    resolved = resolver.resolve("BTCUSDT", "1h")
    frame = pd.DataFrame(
        {
            "open": [float(bar.open) for bar in bars],
            "high": [float(bar.high) for bar in bars],
            "low": [float(bar.low) for bar in bars],
            "close": [float(bar.close) for bar in bars],
            "volume": [float(bar.volume) for bar in bars],
        },
        index=pd.DatetimeIndex([bar.bar_open_at for bar in bars]),
    )
    direct = regression_api.compute_regression_context(
        frame,
        "BTCUSDT",
        "1h",
        resolved,
        resolver.structural_channel_config,
    )
    structural = direct.channel.structural
    channel = direct.channel
    expected = {
        "context_id": direct.context_id,
        "source_config_hash": structural.source_config_hash,
        "channel_config_hash": channel.channel_config_hash,
        "structural": {
            "estimator_id": structural.estimator_id,
            "window_size": structural.window_size,
            "window_started_at": structural.window_started_at,
            "bar_open_at": structural.timestamp,
            "observed_through": structural.observed_through,
            "slope_log_per_hour": structural.slope_log_per_hour,
            "center_price": structural.center_price,
            "residual_mad_log": structural.residual_mad_log,
            "fit_quality": structural.fit_quality,
        },
        "channel": {
            "channel_id": channel.channel_id,
            "inner_coverage": channel.inner_coverage,
            "outer_coverage": channel.outer_coverage,
            "lower_inner_residual_log": channel.lower_inner_residual_log,
            "upper_inner_residual_log": channel.upper_inner_residual_log,
            "lower_outer_residual_log": channel.lower_outer_residual_log,
            "upper_outer_residual_log": channel.upper_outer_residual_log,
            "lower_inner_price": channel.lower_inner_price,
            "upper_inner_price": channel.upper_inner_price,
            "lower_outer_price": channel.lower_outer_price,
            "upper_outer_price": channel.upper_outer_price,
            "current_residual_log": channel.current_residual_log,
        },
        "location": {
            "region": direct.region.value,
            "outer_channel_position": direct.outer_channel_position,
            "inner_width_log": direct.inner_width_log,
            "outer_width_log": direct.outer_width_log,
            "inner_width_fraction": direct.inner_width_fraction,
            "outer_width_fraction": direct.outer_width_fraction,
            "upper_outer_breach": direct.upper_outer_breach,
            "lower_outer_breach": direct.lower_outer_breach,
            "previous_region": direct.previous_region.value
            if direct.previous_region is not None
            else None,
            "reentered_from_upper_outer": direct.reentered_from_upper_outer,
            "reentered_from_lower_outer": direct.reentered_from_lower_outer,
        },
    }
    assert snapshot.value == expected
    assert snapshot.value.keys() == expected.keys()
    assert snapshot.value["location"]["region"] == direct.region.value
    assert snapshot.value["structural"]["observed_through"] == view.market_as_of
    assert snapshot.value["structural"]["bar_open_at"] == view.decision_bar.bar_open_at
    assert (
        snapshot.value["structural"]["estimator_id"]
        == "theil_sen_log_price_all_pairs_v1"
    )
    assert (
        snapshot.value["channel"]["channel_id"]
        == "asymmetric_residual_quantiles_linear_v1"
    )
    assert snapshot.value["source_config_hash"] == "30d530f70382"
    assert snapshot.value["channel_config_hash"] == (
        "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"
    )


def test_regression_feature_config_fingerprint_tracks_source_and_channel_identity() -> (
    None
):
    canonical_raw = _canonical_config_mapping()
    canonical_resolver = ConfigResolver.from_dict(copy.deepcopy(canonical_raw))
    lane = _resolved_lane("1h")
    policy = FeaturePolicy(
        name="regression-test",
        version="1",
        allowed_features=(REGRESSION_CONTEXT_FEATURE_NAME,),
    )

    canonical_plan = compile_feature_plan(
        lane,
        FeatureCatalog(
            [build_regression_context_feature_definition(canonical_resolver)]
        ),
        policy,
        GRID,
    )
    deterministic_plan = compile_feature_plan(
        lane,
        FeatureCatalog(
            [build_regression_context_feature_definition(canonical_resolver)]
        ),
        policy,
        GRID,
    )
    assert (
        canonical_plan.feature_config_fingerprints
        == deterministic_plan.feature_config_fingerprints
    )

    channel_raw = copy.deepcopy(canonical_raw)
    channel_raw["structural_channel"] = {
        "inner_coverage": 0.60,
        "outer_coverage": 0.90,
    }
    canonical_without_channel = copy.deepcopy(canonical_raw)
    changed_without_channel = copy.deepcopy(channel_raw)
    canonical_without_channel.pop("structural_channel")
    changed_without_channel.pop("structural_channel")
    assert canonical_without_channel == changed_without_channel

    channel_resolver = ConfigResolver.from_dict(channel_raw)
    channel_plan = compile_feature_plan(
        lane,
        FeatureCatalog([build_regression_context_feature_definition(channel_resolver)]),
        policy,
        GRID,
    )
    canonical_config = canonical_resolver.resolve("BTCUSDT", "1h")
    channel_config = channel_resolver.resolve("BTCUSDT", "1h")
    canonical_history = canonical_plan.history_requirements[
        REGRESSION_CONTEXT_FEATURE_NAME
    ]
    channel_history = channel_plan.history_requirements[REGRESSION_CONTEXT_FEATURE_NAME]
    assert canonical_config.config_hash == channel_config.config_hash == "30d530f70382"
    assert canonical_config.window_size == channel_config.window_size == 73
    assert next(iter(canonical_history.values())) == 74
    assert channel_history == canonical_history
    assert channel_config_fingerprint(channel_resolver.structural_channel_config) != (
        channel_config_fingerprint(canonical_resolver.structural_channel_config)
    )

    assert (
        channel_plan.feature_config_fingerprints
        != canonical_plan.feature_config_fingerprints
    )
    assert (
        channel_plan.feature_plan_fingerprint != canonical_plan.feature_plan_fingerprint
    )

    source_raw = copy.deepcopy(canonical_raw)
    source_raw["assets"]["BTCUSDT"]["timeframes"]["1h"]["band_multiplier"] = 1.953
    canonical_without_band = copy.deepcopy(canonical_raw)
    changed_without_band = copy.deepcopy(source_raw)
    del canonical_without_band["assets"]["BTCUSDT"]["timeframes"]["1h"][
        "band_multiplier"
    ]
    del changed_without_band["assets"]["BTCUSDT"]["timeframes"]["1h"]["band_multiplier"]
    assert canonical_without_band == changed_without_band

    source_resolver = ConfigResolver.from_dict(source_raw)
    source_plan = compile_feature_plan(
        lane,
        FeatureCatalog([build_regression_context_feature_definition(source_resolver)]),
        policy,
        GRID,
    )
    source_config = source_resolver.resolve("BTCUSDT", "1h")
    source_history = source_plan.history_requirements[REGRESSION_CONTEXT_FEATURE_NAME]
    assert source_config.config_hash != canonical_config.config_hash
    assert source_config.window_size == canonical_config.window_size == 73
    assert source_history == canonical_history
    assert channel_config_fingerprint(source_resolver.structural_channel_config) == (
        channel_config_fingerprint(canonical_resolver.structural_channel_config)
    )
    assert (
        source_plan.feature_config_fingerprints
        != canonical_plan.feature_config_fingerprints
    )
    assert (
        source_plan.feature_plan_fingerprint != canonical_plan.feature_plan_fingerprint
    )


def test_regression_projection_preserves_volume_and_price_scale_invariants() -> None:
    def projected_value(**kwargs):
        _resolver, lane, _definition, catalog, plan, store, view, _bars = _environment(
            **kwargs
        )
        return (
            FeatureEngine(catalog, store, GRID)
            .compute(plan, lane, view)
            .shared_features[REGRESSION_CONTEXT_FEATURE_NAME]
            .value
        )

    baseline = projected_value()
    volume_changed = projected_value(volume=37)
    scaled = projected_value(price_scale=17)

    assert volume_changed == baseline
    assert scaled["context_id"] == baseline["context_id"]
    assert scaled["source_config_hash"] == baseline["source_config_hash"]
    assert scaled["channel_config_hash"] == baseline["channel_config_hash"]
    assert (
        scaled["structural"]["estimator_id"] == baseline["structural"]["estimator_id"]
    )
    assert scaled["channel"]["channel_id"] == baseline["channel"]["channel_id"]

    for field_name in (
        "slope_log_per_hour",
        "residual_mad_log",
        "fit_quality",
    ):
        assert scaled["structural"][field_name] == pytest.approx(
            baseline["structural"][field_name], rel=1e-12, abs=1e-12
        )
    for field_name in (
        "inner_coverage",
        "outer_coverage",
        "lower_inner_residual_log",
        "upper_inner_residual_log",
        "lower_outer_residual_log",
        "upper_outer_residual_log",
        "current_residual_log",
    ):
        assert scaled["channel"][field_name] == pytest.approx(
            baseline["channel"][field_name], rel=1e-12, abs=1e-12
        )
    for field_name in (
        "outer_channel_position",
        "inner_width_log",
        "outer_width_log",
        "inner_width_fraction",
        "outer_width_fraction",
    ):
        assert scaled["location"][field_name] == pytest.approx(
            baseline["location"][field_name], rel=1e-12, abs=1e-12
        )
    assert scaled["location"]["region"] == baseline["location"]["region"]
    assert (
        scaled["location"]["upper_outer_breach"]
        == baseline["location"]["upper_outer_breach"]
    )
    assert (
        scaled["location"]["lower_outer_breach"]
        == baseline["location"]["lower_outer_breach"]
    )
    assert (
        scaled["location"]["previous_region"] == baseline["location"]["previous_region"]
    )
    assert (
        scaled["location"]["reentered_from_upper_outer"]
        == baseline["location"]["reentered_from_upper_outer"]
    )
    assert (
        scaled["location"]["reentered_from_lower_outer"]
        == baseline["location"]["reentered_from_lower_outer"]
    )

    assert scaled["structural"]["center_price"] == pytest.approx(
        baseline["structural"]["center_price"] * 17, rel=1e-12
    )
    for field_name in (
        "lower_inner_price",
        "upper_inner_price",
        "lower_outer_price",
        "upper_outer_price",
    ):
        assert scaled["channel"][field_name] == pytest.approx(
            baseline["channel"][field_name] * 17, rel=1e-12
        )


def test_regression_feature_fails_closed_for_projected_bar_and_insufficient_history() -> (
    None
):
    _resolver, lane, definition, catalog, plan, store, view, _bars = _environment(
        count=10
    )
    resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    assert REGRESSION_CONTEXT_FEATURE_NAME in resolution.unavailable_features
    assert REGRESSION_CONTEXT_FEATURE_NAME not in resolution.shared_features

    projected = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(hours=1),
        market_as_of=BASE + timedelta(minutes=30),
        open=Decimal(99),
        high=Decimal(101),
        low=Decimal(98),
        close=Decimal(100),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=False,
    )
    from apps.decision_app.features.engine import SharedFeatureContext

    context = SharedFeatureContext(
        lane_id=lane.lane_id,
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        market_as_of=projected.market_as_of,
        decision_timeframe="1h",
        trigger_timeframe="1h",
        decision_bar=projected,
        decision_bar_closed=False,
    )
    with pytest.raises(ValueError, match="closed Decision bar"):
        definition.calculator(context)


def test_production_composition_does_not_request_regression_context() -> None:
    from apps.decision_app.composition import build_production_composition
    from tests.decision.test_d9b_live_runtime import _sr_config

    composition = build_production_composition(_sr_config())
    assert composition.feature_catalog.get(REGRESSION_CONTEXT_FEATURE_NAME) is None
