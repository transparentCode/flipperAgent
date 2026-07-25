from __future__ import annotations

import pytest

from apps.signal_app.pipeline import regime as regime_module
from apps.signal_app.pipeline.regime import (
    RegimeFeaturePipeline,
    _create_trendline_family_shadow,
    _trendline_family_frame,
)
from libs.contracts.signal import FeatureVector, ModelOutput
from libs.models.regime_v2 import RegimeV2Orchestrator
from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
)
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.selection.selection_layer import SelectionLayer
from libs.selection.strategies import ConvictionWeightedStrategy

from .test_trendline_family_feature_producer import _SupportProvider, _clock, _frame


class _ActiveRegimeV2:
    min_bars = 1

    def __init__(self) -> None:
        self.latest_features = None

    def analyze(self, price_history, *, latest_features):
        self.latest_features = dict(latest_features)
        return {"evidence": {"confidence": 0.6}, "policy": {"allow_trend_following": True}}


class _TrendGateRegimeV2(_ActiveRegimeV2):
    def analyze(self, price_history, *, latest_features):
        self.latest_features = dict(latest_features)
        return {
            "evidence": {"trend_direction": "bull", "confidence": 0.8},
            "policy": {"allow_trend_following": True, "trend_score": 0.6},
        }


class _ConfigResolver:
    def __init__(self, payload=None, *, exc: Exception | None = None) -> None:
        self.payload = payload
        self.exc = exc

    def resolve(self, asset, timeframe, producer_name):
        del asset, timeframe
        if producer_name != "TrendlineFamilyShadow":
            return None
        if self.exc is not None:
            raise self.exc
        return self.payload


class _RaisingShadowProducer:
    min_bars = 0

    def analyze(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("shadow adapter bug")


@pytest.mark.asyncio
async def test_shadow_namespace_is_excluded_from_active_regime_and_selection_inputs() -> None:
    active_disabled = _ActiveRegimeV2()
    active_enabled = _ActiveRegimeV2()
    history = _history()
    disabled = RegimeFeaturePipeline(
        "BTCUSDT", "1h", min_bars=1, orchestrator=None, classifier=None, regime_v2=active_disabled
    )
    enabled = RegimeFeaturePipeline(
        "BTCUSDT",
        "1h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=active_enabled,
        trendline_family_shadow=_shadow_producer(),
    )
    disabled.prime(history)
    enabled.prime(history)

    baseline = await disabled.enrich({"RSI": 55.0})
    shadowed = await enabled.enrich({"RSI": 55.0})

    assert {key: value for key, value in shadowed.items() if key != "trendline_family_shadow"} == baseline
    assert "trendline_family_shadow" not in active_enabled.latest_features
    assert active_enabled.latest_features == active_disabled.latest_features
    assert shadowed["trendline_family_shadow"]["trendline_family_valid"] is True

    baseline_vector = FeatureVector(
        asset="BTCUSDT", timeframe="1h", timestamp=1.0, features=baseline, bar_data={"close": 100.0}
    )
    shadow_vector = FeatureVector(
        asset="BTCUSDT", timeframe="1h", timestamp=1.0, features=shadowed, bar_data={"close": 100.0}
    )
    output = ModelOutput(
        model_name="Momentum", asset="BTCUSDT", timeframe="1h", timestamp=1.0, direction=1, conviction=0.8
    )
    layer = SelectionLayer("BTCUSDT", "1h")
    layer._config = {"strategy": "conviction_weighted", "overlays": {"regime_v2_trend_gate": {"enabled": False}}}
    layer._strategy = ConvictionWeightedStrategy()

    assert [item.model_dump() for item in layer.select([output], None, baseline_vector)] == [
        item.model_dump() for item in layer.select([output], None, shadow_vector)
    ]


def test_independent_shadow_call_does_not_change_regime_v2_probability_or_policy_output() -> None:
    frame = _frame(periods=140)
    orchestrator = RegimeV2Orchestrator.create("BTCUSDT", "1h")
    before = orchestrator.analyze(frame).to_dict()

    _shadow_producer().analyze(frame, observed_at=frame.index[-1].to_pydatetime())

    after = orchestrator.analyze(frame).to_dict()
    assert after == before


def test_disabled_shadow_factory_does_not_import_optional_adapter(monkeypatch) -> None:
    def import_bug():
        raise AssertionError("optional adapter must not import while disabled")

    monkeypatch.setattr(regime_module, "_load_trendline_family_shadow_adapter", import_bug)

    assert _create_trendline_family_shadow(
        "BTCUSDT", "1h", config_resolver=_ConfigResolver(None)
    ) is None
    assert _create_trendline_family_shadow(
        "BTCUSDT", "1h", config_resolver=_ConfigResolver({"enabled": False})
    ) is None
    pipeline = RegimeFeaturePipeline.create_optional(
        "BTCUSDT",
        "1h",
        config_resolver=_ConfigResolver({"enabled": False}),
    )
    assert pipeline.trendline_family_shadow is None


def test_optional_pipeline_does_not_construct_enabled_shadow(monkeypatch) -> None:
    orchestrator = object()
    classifier = object()
    regime_v2 = object()
    resolver = _ConfigResolver({"enabled": True})

    def create_classifier(_asset, _timeframe, *, config_resolver):
        assert config_resolver is resolver
        return classifier

    def create_regime_v2(_asset, _timeframe, *, config_resolver):
        assert config_resolver is resolver
        return regime_v2

    monkeypatch.setattr(
        regime_module,
        "_create_regime_orchestrator",
        lambda _asset, _timeframe: orchestrator,
    )
    monkeypatch.setattr(
        regime_module,
        "_create_regime_classifier",
        create_classifier,
    )
    monkeypatch.setattr(
        regime_module,
        "_create_regime_v2",
        create_regime_v2,
    )

    def unexpected_shadow_creation(*args, **kwargs):
        del args, kwargs
        raise AssertionError("automatic shadow construction must be retired")

    monkeypatch.setattr(
        regime_module,
        "_create_trendline_family_shadow",
        unexpected_shadow_creation,
    )

    assert resolver.resolve("BTCUSDT", "1h", "TrendlineFamilyShadow") == {"enabled": True}
    pipeline = RegimeFeaturePipeline.create_optional(
        "BTCUSDT",
        "1h",
        config_resolver=resolver,
    )

    assert pipeline.orchestrator is orchestrator
    assert pipeline.classifier is classifier
    assert pipeline.regime_v2 is regime_v2
    assert pipeline.trendline_family_shadow is None


@pytest.mark.parametrize(
    "payload, reason",
    (
        ({"enabled": True, "unknown": 1}, "invalid_shadow_config"),
        ({"enabled": True, "config_path": 1}, "invalid_shadow_config"),
    ),
)
def test_enabled_invalid_shadow_config_retains_diagnostic_payload(payload, reason) -> None:
    producer = _create_trendline_family_shadow(
        "BTCUSDT", "1h", config_resolver=_ConfigResolver(payload)
    )

    assert producer is not None
    diagnostic = producer.analyze(_frame())
    assert diagnostic["trendline_family_shadow_enabled"] is True
    assert diagnostic["trendline_family_valid"] is False
    assert diagnostic["trendline_family_error_type"] == "config_resolution_error"
    assert diagnostic["trendline_family_error_reason"] == reason
    assert diagnostic["trendline_family_failure_count"] == 1
    assert diagnostic["trendline_family_success_count"] == 0
    assert diagnostic["trendline_family_state_advanced"] is False
    assert diagnostic["trendline_family_repository_head_before"] is None
    assert diagnostic["trendline_family_repository_head_after"] is None


def test_enabled_import_or_construction_failure_retains_diagnostic_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        regime_module,
        "_load_trendline_family_shadow_adapter",
        lambda: (_ for _ in ()).throw(ImportError("optional adapter unavailable")),
    )
    imported_failed = _create_trendline_family_shadow(
        "BTCUSDT", "1h", config_resolver=_ConfigResolver({"enabled": True})
    )
    assert imported_failed is not None
    assert imported_failed.analyze(_frame())["trendline_family_error_reason"] == "shadow_adapter_import_failure"

    from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
        FailedTrendlineFamilyShadowProducer,
        TrendlineFamilyShadowConfig,
    )

    class _BrokenProducer:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise RuntimeError("constructor bug")

    monkeypatch.setattr(
        regime_module,
        "_load_trendline_family_shadow_adapter",
        lambda: (
            FailedTrendlineFamilyShadowProducer,
            _BrokenProducer,
            TrendlineFamilyShadowConfig,
        ),
    )
    construction_failed = _create_trendline_family_shadow(
        "BTCUSDT", "1h", config_resolver=_ConfigResolver({"enabled": True})
    )
    assert construction_failed is not None
    assert (
        construction_failed.analyze(_frame())["trendline_family_error_reason"]
        == "shadow_adapter_construction_failure"
    )


def test_shadow_config_resolution_failure_retains_diagnostic_payload() -> None:
    producer = _create_trendline_family_shadow(
        "BTCUSDT",
        "1h",
        config_resolver=_ConfigResolver(exc=RuntimeError("resolver bug")),
    )

    assert producer is not None
    diagnostic = producer.analyze(_frame())
    assert diagnostic["trendline_family_shadow_enabled"] is True
    assert diagnostic["trendline_family_valid"] is False
    assert diagnostic["trendline_family_error_type"] == "config_resolution_error"
    assert diagnostic["trendline_family_error_reason"] == "config_resolution_failure"


@pytest.mark.asyncio
async def test_pipeline_catch_preserves_enabled_shadow_failure_and_active_regime() -> None:
    history = _history()
    baseline_active = _ActiveRegimeV2()
    failing_active = _ActiveRegimeV2()
    baseline = RegimeFeaturePipeline(
        "BTCUSDT", "1h", min_bars=1, orchestrator=None, classifier=None, regime_v2=baseline_active
    )
    failing = RegimeFeaturePipeline(
        "BTCUSDT",
        "1h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=failing_active,
        trendline_family_shadow=_RaisingShadowProducer(),
    )
    baseline.prime(history)
    failing.prime(history)

    baseline_features = await baseline.enrich({"RSI": 55.0})
    failed_features = await failing.enrich({"RSI": 55.0})

    assert failed_features["regime_v2"] == baseline_features["regime_v2"]
    assert failing_active.latest_features == baseline_active.latest_features
    diagnostic = failed_features["trendline_family_shadow"]
    assert diagnostic["trendline_family_valid"] is False
    assert diagnostic["trendline_family_error_type"] == "unexpected_error"
    assert diagnostic["trendline_family_error_reason"] == "RuntimeError"
    assert diagnostic["trendline_family_state_advanced"] is False


@pytest.mark.asyncio
async def test_stale_shadow_input_is_reserved_output_only_namespace() -> None:
    active = _ActiveRegimeV2()
    pipeline = RegimeFeaturePipeline(
        "BTCUSDT",
        "1h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=active,
        trendline_family_shadow=_shadow_producer(),
    )
    pipeline.prime(_history())
    supplied = {"RSI": 55.0, "trendline_family_shadow": {"stale": "leak"}}

    enriched = await pipeline.enrich(supplied)

    assert supplied == {"RSI": 55.0, "trendline_family_shadow": {"stale": "leak"}}
    assert "trendline_family_shadow" not in active.latest_features
    assert active.latest_features == {"RSI": 55.0}
    assert enriched["trendline_family_shadow"] != supplied["trendline_family_shadow"]
    assert enriched["trendline_family_shadow"]["trendline_family_valid"] is True


def test_shadow_timestamp_requirement_is_atomic_and_disabled_mode_remains_compatible() -> None:
    shadowed = RegimeFeaturePipeline(
        "BTCUSDT", "1h", trendline_family_shadow=_shadow_producer()
    )
    original_prices = shadowed.price_history
    with pytest.raises(ValueError, match="timestamp is required"):
        shadowed.append_bar(_bar())
    assert shadowed.price_history == original_prices
    assert shadowed._trendline_family_history == []

    for timestamp in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="timestamp must be finite"):
            shadowed.append_bar(_bar(), timestamp=timestamp)
    assert shadowed.price_history == original_prices
    assert shadowed._trendline_family_history == []

    disabled = RegimeFeaturePipeline("BTCUSDT", "1h")
    disabled.append_bar(_bar())
    assert len(disabled.price_history) == 1


@pytest.mark.asyncio
async def test_shadow_history_normalizes_seconds_and_milliseconds_and_rejects_order_ambiguity() -> None:
    seconds = RegimeFeaturePipeline("BTCUSDT", "1h", trendline_family_shadow=_shadow_producer())
    seconds.append_bar(_bar(), timestamp=1_704_067_200.0)
    seconds_frame = _trendline_family_frame(seconds._trendline_family_history)
    assert str(seconds_frame.index.tz) == "UTC"
    assert seconds_frame.index.is_monotonic_increasing

    milliseconds = RegimeFeaturePipeline("BTCUSDT", "1h", trendline_family_shadow=_shadow_producer())
    milliseconds.append_bar(_bar(), timestamp=1_704_067_200_000.0)
    milliseconds_frame = _trendline_family_frame(milliseconds._trendline_family_history)
    assert milliseconds_frame.index.equals(seconds_frame.index)

    seconds.prime(_history())
    seconds.append_bar(_bar(), timestamp=_history()[-1][5] + 3600.0)
    primed_frame = _trendline_family_frame(seconds._trendline_family_history)
    assert str(primed_frame.index.tz) == "UTC"
    assert primed_frame.index.is_monotonic_increasing

    milliseconds.append_bar(_bar(), timestamp=1_704_067_200_000.0)
    ambiguous = await milliseconds.enrich({"RSI": 55.0})
    diagnostic = ambiguous["trendline_family_shadow"]
    assert diagnostic["trendline_family_valid"] is False
    assert diagnostic["trendline_family_error_reason"] == "non_monotonic_shadow_timestamp"


@pytest.mark.asyncio
async def test_enabled_trend_gate_is_invariant_and_does_not_read_shadow_namespace() -> None:
    history = _history()
    active_disabled = _TrendGateRegimeV2()
    active_enabled = _TrendGateRegimeV2()
    baseline_pipeline = RegimeFeaturePipeline(
        "BTCUSDT", "1h", min_bars=1, orchestrator=None, classifier=None, regime_v2=active_disabled
    )
    shadow_pipeline = RegimeFeaturePipeline(
        "BTCUSDT",
        "1h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=active_enabled,
        trendline_family_shadow=_shadow_producer(),
    )
    baseline_pipeline.prime(history)
    shadow_pipeline.prime(history)
    base_input = {"RSI": 55.0, "trendline": {"legacy": "unchanged"}}

    baseline = await baseline_pipeline.enrich(base_input)
    shadowed = await shadow_pipeline.enrich(base_input)

    assert active_enabled.latest_features == active_disabled.latest_features
    assert "trendline_family_shadow" not in active_enabled.latest_features
    assert shadowed["regime_v2"] == baseline["regime_v2"]
    assert shadowed["trendline"] == baseline["trendline"]

    baseline_vector = FeatureVector(
        asset="BTCUSDT", timeframe="1h", timestamp=1.0, features=baseline, bar_data={"close": 100.0}
    )
    shadow_vector = FeatureVector(
        asset="BTCUSDT", timeframe="1h", timestamp=1.0, features=shadowed, bar_data={"close": 100.0}
    )
    output = [
        ModelOutput(
            model_name="Momentum", asset="BTCUSDT", timeframe="1h", timestamp=1.0, direction=1, conviction=0.8
        ),
        ModelOutput(
            model_name="TrendFollowing", asset="BTCUSDT", timeframe="1h", timestamp=1.0, direction=-1, conviction=0.8
        ),
    ]
    layer = SelectionLayer("BTCUSDT", "1h")
    layer._config = {
        "strategy": "conviction_weighted",
        "overlays": {
            "regime_v2_trend_gate": {
                "enabled": True,
                "mode": "gated",
                "target_models": ["Momentum", "TrendFollowing"],
                "min_trend_score": 0.24,
                "min_confidence": 0.0,
            }
        },
    }
    layer._strategy = ConvictionWeightedStrategy()

    assert [item.model_dump() for item in layer.select(output, None, baseline_vector)] == [
        item.model_dump() for item in layer.select(output, None, shadow_vector)
    ]


def _shadow_producer() -> TrendlineFamilyFeatureProducer:
    config = TrendlineFamilyConfigResolver(
        {"version": "1", "model": {"enabled": True}}
    ).resolve(asset="BTCUSDT", timeframe="1h")
    return TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        resolved_config=config,
        provider=_SupportProvider(),
        clock=_clock(0, 1),
    )


def _history() -> list[tuple[float, ...]]:
    frame = _frame()
    return [
        (
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
            float(index.timestamp()),
            0.0,
        )
        for index, row in frame.iterrows()
    ]


def _bar() -> dict[str, float]:
    return {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1000.0,
    }
