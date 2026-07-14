from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta, timezone
import logging

import pandas as pd
import pytest

from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
    summarize_trendline_family_shadow_artifacts,
)
from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
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


UTC = timezone.utc


class _SupportProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, ohlcv, *, asset, timeframe, observed_at, config, context=None):
        del ohlcv, context
        self.calls += 1
        first = observed_at - timedelta(hours=3)
        second = observed_at - timedelta(hours=1)
        geometry = LineGeometry(first, 100.0, 0.0)
        candidate = LineCandidate(
            candidate_id=f"support-{observed_at.isoformat()}",
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            geometry=geometry,
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


class _BirthThenAbstainProvider(_SupportProvider):
    def generate(self, *args, **kwargs):
        if self.calls == 0:
            return super().generate(*args, **kwargs)
        self.calls += 1
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.NO_CONFIRMED_PIVOTS,
            candidates=(),
            reason_codes=(CandidateGenerationStatus.NO_CONFIRMED_PIVOTS.value,),
        )


class _MultiSupportProvider(_SupportProvider):
    def generate(self, ohlcv, *, asset, timeframe, observed_at, config, context=None):
        result = super().generate(
            ohlcv,
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            config=config,
            context=context,
        )
        first = observed_at - timedelta(hours=3)
        second = observed_at - timedelta(hours=1)
        second_rail = LineCandidate(
            candidate_id=f"support-rail-two-{observed_at.isoformat()}",
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            geometry=LineGeometry(first, 100.4, 0.0),
            anchors=(
                AnchorRef("support-two-first", first, 100.4, "low", first),
                AnchorRef("support-two-second", second, 100.4, "low", second),
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
            source_line_index=1,
            metadata={
                "model_version": config.model_version,
                "config_version": config.config_version,
                "resolved_config_hash": config.resolved_config_hash,
            },
        )
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.VALID,
            candidates=(*result.candidates, second_rail),
            reason_codes=(),
        )


class _RepositorySpy(InMemoryTrendlineFamilyRepository):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.writes = 0

    def latest_snapshot(self, asset: str, timeframe: str):
        self.reads += 1
        return super().latest_snapshot(asset, timeframe)

    def save_snapshot(self, snapshot) -> None:
        self.writes += 1
        super().save_snapshot(snapshot)


class _InternalBugProvider:
    def __init__(self, exc_type: type[Exception]) -> None:
        self.exc_type = exc_type

    def generate(self, *args, **kwargs):
        del args, kwargs
        raise self.exc_type("internal provider bug")


class _FailingClock:
    def __init__(self, *values: int | Exception) -> None:
        self.values = iter(values)

    def __call__(self) -> int:
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


def test_disabled_shadow_does_not_touch_repository_or_provider() -> None:
    repository = _RepositorySpy()
    provider = _SupportProvider()
    producer = TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(),
        repository=repository,
        provider=provider,
    )

    features = producer.analyze(_frame())

    assert features["trendline_family_shadow_enabled"] is False
    assert features["trendline_family_valid"] is None
    assert features["trendline_family_error"] is None
    assert repository.reads == 0
    assert repository.writes == 0
    assert provider.calls == 0


def test_enabled_shadow_projects_persisted_family_and_interaction_evidence() -> None:
    repository = InMemoryTrendlineFamilyRepository()
    producer = _producer(repository=repository, clock=_clock(0, 2_000_000))

    features = producer.analyze(_frame())
    snapshot = repository.latest_snapshot("BTCUSDT", "1h")

    assert snapshot is not None
    support = snapshot.active_families[0]
    observation = snapshot.observations[0]
    assert features["trendline_family_valid"] is True
    assert features["trendline_family_snapshot_id"] == snapshot.snapshot_id
    assert features["trendline_family_previous_snapshot_id"] is None
    assert features["trendline_family_model_version"] == snapshot.model_version
    assert features["trendline_family_resolved_config_hash"] == snapshot.resolved_config_hash
    assert features["trendline_family_count_active"] == len(snapshot.active_families)
    assert features["trendline_family_births"] == 1
    assert features["nearest_support_family_id"] == support.family_id
    assert features["support_family_confidence"] == support.confidence
    assert features["support_breach_count"] == support.breach_count
    assert features["support_interaction_state"] == observation.state.value
    assert features["support_wick_penetration_atr"] == observation.wick_penetration_atr
    assert features["distance_to_support_zone_atr"] == observation.distance_to_zone_atr
    assert features["nearest_resistance_family_id"] is None
    assert features["resistance_family_confidence"] is None
    assert features["trendline_family_top_support_score_gap"] is None
    assert features["trendline_family_ambiguity_reason"] == "ranking_scores_not_persisted_phase_e"
    assert features["trendline_family_latency_ms"] == 2.0
    assert features["trendline_family_success_count"] == 1
    assert features["trendline_family_coverage"] == 1.0


def test_shadow_projects_additive_multi_rail_corridor_evidence_only() -> None:
    producer = _producer(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=_MultiSupportProvider(),
        clock=_clock(0, 2_000_000),
    )

    features = producer.analyze(_frame())
    artifacts = summarize_trendline_family_shadow_artifacts(
        ({"trendline_family_shadow": features},)
    )

    assert features["trendline_family_multi_rail_count"] == 1
    assert features["support_rail_count"] == 2
    assert features["support_ordered_member_ids"]
    assert features["support_corridor_width_atr"] > 0.0
    assert features["support_nearest_rail_member_id"] in features["support_ordered_member_ids"]
    assert artifacts["distributions"]["rail_count"] == {"2": 1}


def test_failed_update_is_fail_soft_and_preserves_repository_head() -> None:
    repository = InMemoryTrendlineFamilyRepository()
    producer = _producer(repository=repository, clock=_clock(0, 1_000_000, 2_000_000, 3_000_000))
    first = producer.analyze(_frame())

    failed = producer.analyze(_frame(), tick_size=0.0)

    assert failed["trendline_family_valid"] is False
    assert failed["trendline_family_error_type"] == "family_contract_error"
    assert failed["trendline_family_error_reason"] == "invalid_tick_size"
    assert failed["trendline_family_failure_count"] == 1
    assert failed["trendline_family_repository_head_before"] == first["trendline_family_snapshot_id"]
    assert failed["trendline_family_repository_head_after"] == first["trendline_family_snapshot_id"]
    assert failed["trendline_family_state_advanced"] is False


def test_subsequent_enabled_update_advances_the_same_repository_lineage() -> None:
    repository = InMemoryTrendlineFamilyRepository()
    producer = _producer(repository=repository, clock=_clock(0, 1, 2, 3))
    first = producer.analyze(_frame(periods=8))
    second = producer.analyze(_frame(periods=9))

    assert second["trendline_family_previous_snapshot_id"] == first["trendline_family_snapshot_id"]
    assert second["trendline_family_repository_head_before"] == first["trendline_family_snapshot_id"]
    assert second["trendline_family_repository_head_after"] == second["trendline_family_snapshot_id"]
    assert second["trendline_family_state_advanced"] is True


def test_dormant_families_are_not_exposed_as_nearest_active_families() -> None:
    config = TrendlineFamilyConfigResolver(
        {
            "version": "1",
            "model": {"enabled": True},
            "defaults": {
                "lifecycle": {
                    "active_grace_bars": 1,
                    "dormant_after_bars": 2,
                    "expire_after_bars": 4,
                }
            },
        }
    ).resolve(asset="BTCUSDT", timeframe="1h")
    producer = TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        resolved_config=config,
        provider=_BirthThenAbstainProvider(),
        clock=_clock(0, 1, 2, 3, 4, 5),
    )

    producer.analyze(_frame(periods=8))
    producer.analyze(_frame(periods=9))
    dormant = producer.analyze(_frame(periods=10))

    assert dormant["trendline_family_count_active"] == 0
    assert dormant["trendline_family_count_dormant"] == 1
    assert dormant["nearest_support_family_id"] is None
    assert dormant["support_family_confidence"] is None


def test_repository_config_lineage_mismatch_is_fail_soft() -> None:
    repository = InMemoryTrendlineFamilyRepository()
    first = _producer(repository=repository, config=_resolved_config(version="1"), clock=_clock(0, 1))
    initial = first.analyze(_frame())
    mismatched = _producer(repository=repository, config=_resolved_config(version="2"), clock=_clock(0, 1))

    failed = mismatched.analyze(_frame())

    assert failed["trendline_family_valid"] is False
    assert failed["trendline_family_error_reason"] == "repository_lineage_mismatch"
    assert failed["trendline_family_repository_head_before"] == initial["trendline_family_snapshot_id"]
    assert failed["trendline_family_repository_head_after"] == initial["trendline_family_snapshot_id"]


def test_enabled_shadow_replay_and_future_rows_are_byte_identical() -> None:
    full = _frame(periods=9)
    observed_times = (full.index[5].to_pydatetime(), full.index[6].to_pydatetime())

    def replay(*, include_future_rows: bool) -> tuple[dict, ...]:
        producer = _producer(
            repository=InMemoryTrendlineFamilyRepository(),
            clock=_clock(0, 1, 2, 3),
        )
        return tuple(
            producer.analyze(full if include_future_rows else full.loc[:observed], observed_at=observed)
            for observed in observed_times
        )

    assert replay(include_future_rows=False) == replay(include_future_rows=False)
    assert replay(include_future_rows=False) == replay(include_future_rows=True)


def test_shadow_artifact_summary_exposes_coverage_churn_errors_and_latency() -> None:
    valid = _producer(clock=_clock(0, 2_000_000)).analyze(_frame())
    invalid = _producer(clock=_clock(0, 1_000_000)).analyze(_frame(), tick_size=0.0)
    report = summarize_trendline_family_shadow_artifacts(
        ({"trendline_family_shadow": valid}, {"trendline_family_shadow": invalid})
    )

    assert report["summary"]["enabled_row_count"] == 2
    assert report["summary"]["valid_row_count"] == 1
    assert report["summary"]["invalid_or_error_row_count"] == 1
    assert report["summary"]["nearest_support_coverage_count"] == 1
    assert report["distributions"]["provider_status"] == {"valid": 1}
    assert report["distributions"]["error_reason"] == {"invalid_tick_size": 1}
    assert report["latency_ms"]["mean"] == 1.5


def test_post_persistence_projection_failure_reports_advanced_repository_state(caplog) -> None:
    def projection_bug(*args, **kwargs):
        del args, kwargs
        raise AttributeError("projection bug")

    repository = InMemoryTrendlineFamilyRepository()
    producer = _producer(
        repository=repository,
        clock=_clock(0, 2_000_000),
        feature_projector=projection_bug,
    )

    with caplog.at_level(logging.ERROR):
        payload = producer.analyze(_frame())

    snapshot = repository.latest_snapshot("BTCUSDT", "1h")
    assert snapshot is not None
    assert payload["trendline_family_valid"] is False
    assert payload["trendline_family_error_type"] == "unexpected_error"
    assert payload["trendline_family_error_reason"] == "AttributeError"
    assert payload["trendline_family_repository_head_before"] is None
    assert payload["trendline_family_repository_head_after"] == snapshot.snapshot_id
    assert payload["trendline_family_state_advanced"] is True
    assert payload["trendline_family_failure_count"] == 1
    assert payload["trendline_family_success_count"] == 0
    assert payload["trendline_family_coverage"] == 0.0
    assert payload["trendline_family_latency_ms"] >= 0.0
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("exc_type", (TypeError, ValueError, RuntimeError))
def test_provider_programming_errors_are_unexpected_and_do_not_expose_messages(
    exc_type: type[Exception], caplog
) -> None:
    producer = TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        resolved_config=_resolved_config(),
        provider=_InternalBugProvider(exc_type),
        clock=_clock(0, 1_000_000),
    )

    with caplog.at_level(logging.ERROR):
        payload = producer.analyze(_frame())

    assert payload["trendline_family_valid"] is False
    assert payload["trendline_family_error_type"] == "unexpected_error"
    assert payload["trendline_family_error_reason"] == exc_type.__name__
    assert "internal provider bug" not in repr(payload)
    assert any(record.exc_info for record in caplog.records)


def test_clock_failures_never_escape_or_hide_persisted_state() -> None:
    repository = InMemoryTrendlineFamilyRepository()
    initial_clock_failure = _producer(
        repository=repository,
        clock=_FailingClock(RuntimeError("initial clock failure"), RuntimeError("elapsed failure")),
    )
    initial = initial_clock_failure.analyze(_frame())

    snapshot = repository.latest_snapshot("BTCUSDT", "1h")
    assert snapshot is not None
    assert initial["trendline_family_valid"] is True
    assert initial["trendline_family_latency_ms"] == 0.0
    assert initial["trendline_family_repository_head_after"] == snapshot.snapshot_id
    assert initial["trendline_family_state_advanced"] is True

    success_latency_failure = _producer(
        clock=_FailingClock(0, RuntimeError("success latency clock")),
    ).analyze(_frame())
    assert success_latency_failure["trendline_family_valid"] is True
    assert success_latency_failure["trendline_family_latency_ms"] == 0.0
    assert success_latency_failure["trendline_family_state_advanced"] is True

    canonical_failure = _producer(
        repository=repository,
        clock=_FailingClock(0, RuntimeError("failure latency clock")),
    ).analyze(_frame(periods=9), tick_size=0.0)
    assert canonical_failure["trendline_family_valid"] is False
    assert canonical_failure["trendline_family_error_type"] == "family_contract_error"
    assert canonical_failure["trendline_family_latency_ms"] == 0.0
    assert canonical_failure["trendline_family_repository_head_before"] == snapshot.snapshot_id
    assert canonical_failure["trendline_family_repository_head_after"] == snapshot.snapshot_id
    assert canonical_failure["trendline_family_state_advanced"] is False


def _producer(
    *,
    repository: InMemoryTrendlineFamilyRepository | None = None,
    config: ResolvedTrendlineFamilyConfig | None = None,
    provider=None,
    clock=None,
    feature_projector=None,
) -> TrendlineFamilyFeatureProducer:
    return TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        repository=repository,
        resolved_config=config or _resolved_config(),
        provider=provider or _SupportProvider(),
        clock=clock or _clock(0, 1),
        feature_projector=feature_projector,
    )


def _resolved_config(*, version: str = "1") -> ResolvedTrendlineFamilyConfig:
    return TrendlineFamilyConfigResolver(
        {"version": version, "model": {"enabled": True}}
    ).resolve(asset="BTCUSDT", timeframe="1h")


def _frame(*, periods: int = 8) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0] * periods,
            "high": [101.0] * periods,
            "low": [99.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        },
        index=index,
    )


def _clock(*values: int):
    iterator: Iterator[int] = iter(values)
    return lambda: next(iterator)
