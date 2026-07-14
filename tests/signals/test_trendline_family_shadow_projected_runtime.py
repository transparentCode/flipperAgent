from __future__ import annotations

from datetime import timedelta

import pytest

from apps.signal_app.pipeline.features import FeaturePipeline
from apps.signal_app.pipeline.regime import RegimeFeaturePipeline
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
)
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import (
    AnchorRef,
    FamilyRole,
    LineCandidate,
    LineDiagnostics,
    LineGeometry,
)
from libs.models.trendline_family.provider import (
    CandidateGenerationResult,
    CandidateGenerationStatus,
)
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository


class _RawIndicators:
    indicators: list[object] = []

    def prime(self, history) -> None:
        del history

    def get_unprimed_indicator_keys(self) -> list[str]:
        return []

    def snapshot_features(self, history) -> dict[str, float]:
        del history
        return {"RSI": 55.0}


class _ActiveRegimeV2:
    min_bars = 1

    def __init__(self) -> None:
        self.latest_features: list[dict] = []

    def analyze(self, price_history, *, latest_features):
        self.latest_features.append(dict(latest_features))
        return {"active_price_history_bars": len(price_history), "signal": "unchanged"}


class _Publisher:
    def __init__(self) -> None:
        self.feature_vectors = []

    async def publish_feature_vector(self, feature_vector, *, trigger_timeframe=None) -> None:
        self.feature_vectors.append((feature_vector, trigger_timeframe))

    async def publish_price_update(self, price_update) -> None:
        del price_update


class _SupportProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, ohlcv, *, asset, timeframe, observed_at, config, context=None):
        del ohlcv, context
        self.calls += 1
        first = observed_at - timedelta(hours=3)
        second = observed_at - timedelta(hours=1)
        candidate = LineCandidate(
            candidate_id=f"support-{observed_at.isoformat()}",
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            geometry=LineGeometry(first, 100.0, 0.0),
            anchors=(
                AnchorRef("support-first", first, 100.0, "low", first),
                AnchorRef("support-second", second, 100.0, "low", second),
            ),
            role=FamilyRole.SUPPORT,
            method="pathfinding",
            provider="native_deterministic",
            diagnostics=LineDiagnostics(
                raw_score=0.8,
                normalized_quality=0.8,
                touch_count=2,
                effective_touch_count=2,
                coverage=0.25,
            ),
            source_line_index=0,
            metadata={
                "model_version": config.model_version,
                "config_version": config.config_version,
                "resolved_config_hash": config.resolved_config_hash,
            },
        )
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.VALID,
            candidates=(candidate,),
            reason_codes=(),
        )


class _RepositorySpy(InMemoryTrendlineFamilyRepository):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def save_snapshot(self, snapshot) -> None:
        self.writes += 1
        super().save_snapshot(snapshot)


@pytest.mark.asyncio
async def test_projected_shadow_updates_only_on_confirmed_decision_close() -> None:
    shadow = await _run_projected_sequence(enable_shadow=True)
    baseline = await _run_projected_sequence(enable_shadow=False)

    provider = shadow["provider"]
    repository = shadow["repository"]
    bootstrap, intermediate_one, intermediate_two, close, next_incomplete = shadow["vectors"]

    first_head = repository.latest_snapshot("BTCUSDT", "4h")
    assert first_head is not None
    assert provider.calls == 2
    assert repository.writes == 2
    assert bootstrap["trendline_family_shadow"]["trendline_family_valid"] is True
    assert intermediate_one["trendline_family_shadow"]["trendline_family_valid"] is True
    assert intermediate_two["trendline_family_shadow"]["trendline_family_valid"] is True
    assert close["trendline_family_shadow"]["trendline_family_valid"] is True
    assert next_incomplete["trendline_family_shadow"]["trendline_family_valid"] is True

    assert intermediate_one["trendline_family_shadow"]["trendline_family_state_advanced"] is False
    assert intermediate_two["trendline_family_shadow"]["trendline_family_state_advanced"] is False
    assert close["trendline_family_shadow"]["trendline_family_state_advanced"] is True
    assert next_incomplete["trendline_family_shadow"]["trendline_family_state_advanced"] is False
    assert close["trendline_family_shadow"]["trendline_family_timestamp"] == first_head.timestamp.isoformat()
    assert next_incomplete["trendline_family_shadow"]["trendline_family_timestamp"] == first_head.timestamp.isoformat()

    assert [features["regime_v2"] for features in shadow["vectors"]] == [
        features["regime_v2"] for features in baseline["vectors"]
    ]
    assert all(
        "trendline_family_shadow" not in active_input
        for active_input in shadow["active_regime"].latest_features
    )


async def _run_projected_sequence(*, enable_shadow: bool) -> dict:
    raw = _RawIndicators()
    active_regime = _ActiveRegimeV2()
    repository = _RepositorySpy()
    provider = _SupportProvider()
    shadow_producer = None
    if enable_shadow:
        config = TrendlineFamilyConfigResolver(
            {"version": "1", "model": {"enabled": True}}
        ).resolve(asset="BTCUSDT", timeframe="4h")
        shadow_producer = TrendlineFamilyFeatureProducer(
            "BTCUSDT",
            "4h",
            shadow_config=TrendlineFamilyShadowConfig(enabled=True),
            repository=repository,
            resolved_config=config,
            provider=provider,
        )
    regime = RegimeFeaturePipeline(
        "BTCUSDT",
        "4h",
        min_bars=1,
        orchestrator=None,
        classifier=None,
        regime_v2=active_regime,
        trendline_family_shadow=shadow_producer,
    )
    pipeline = FeaturePipeline(raw_indicators=raw, regime_features=regime)
    publisher = _Publisher()
    worker = SignalRuntimeWorker(
        "BTCUSDT",
        "4h",
        pipeline=pipeline,
        publisher=publisher,
        trigger_timeframe="1h",
        trigger_mode="on_base_bar_close",
    )
    decision_history = _decision_history()
    regime.prime(decision_history)
    worker._prime_projection_history(decision_history)
    worker._prime_source_history([_source_bar(115_200.0)])

    await worker.publish_bootstrap_snapshot(decision_history)
    vectors = [publisher.feature_vectors[-1][0].features]
    for timestamp in (118_800.0, 122_400.0, 126_000.0, 129_600.0):
        worker._source_history.append(_source_bar(timestamp))
        projected = worker._current_projected_bar()
        assert projected is not None
        feature_vector, _ = await worker._process_projected_candle(
            candle=worker._projected_candle_from_projection(projected),
            ltf_context_profiles=None,
        )
        vectors.append(feature_vector.features)

    return {
        "active_regime": active_regime,
        "provider": provider,
        "repository": repository,
        "vectors": vectors,
    }


def _decision_history() -> list[tuple[float, ...]]:
    return [
        (100.0, 101.0, 99.0, 100.0, 1_000.0, float(index * 14_400), 10.0)
        for index in range(8)
    ]


def _source_bar(timestamp: float) -> tuple[float, ...]:
    return (100.0, 101.0, 99.0, 100.0, 10.0, timestamp, 2.0)
