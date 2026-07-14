from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.trendline_family.api import update_trendline_families
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_api_accepts_resolved_config_and_provider_without_yaml_runtime_read() -> None:
    config = tracker_config()
    observed = timestamp()
    output = update_trendline_families(
        tracker_ohlcv(observed),
        asset=config.asset,
        timeframe=config.timeframe,
        repository=InMemoryTrendlineFamilyRepository(),
        config=config,
        provider=SequenceProvider((valid_result(candidate(config, observed)),)),
    )

    assert output.snapshot.asset == config.asset
    assert len(output.snapshot.active_families) == 1


def test_api_can_resolve_canonical_yaml_when_config_is_not_supplied() -> None:
    observed = timestamp()
    config_path = Path("configs/trendline_family.yaml")
    resolved = TrendlineFamilyConfigResolver.from_path(config_path).resolve(
        asset="BTCUSDT",
        timeframe="1h",
    )
    output = update_trendline_families(
        tracker_ohlcv(observed),
        asset="BTCUSDT",
        timeframe="1h",
        repository=InMemoryTrendlineFamilyRepository(),
        config_path=config_path,
        provider=SequenceProvider((valid_result(candidate(resolved, observed)),)),
    )

    assert output.snapshot.config_version == "1"


def test_api_forwards_runtime_tick_size_to_typed_interaction_observation() -> None:
    config = tracker_config()
    observed = timestamp()
    output = update_trendline_families(
        tracker_ohlcv(observed),
        asset=config.asset,
        timeframe=config.timeframe,
        repository=InMemoryTrendlineFamilyRepository(),
        config=config,
        provider=SequenceProvider((valid_result(candidate(config, observed)),)),
        tick_size=0.25,
    )

    assert output.snapshot.observations[0].tick_size == 0.25


def test_api_rejects_invalid_tick_size_before_provider_execution() -> None:
    config = tracker_config()
    observed = timestamp()
    provider = SequenceProvider((valid_result(candidate(config, observed)),))

    with pytest.raises(ContractValidationError, match="tick_size"):
        update_trendline_families(
            tracker_ohlcv(observed),
            asset=config.asset,
            timeframe=config.timeframe,
            repository=InMemoryTrendlineFamilyRepository(),
            config=config,
            provider=provider,
            tick_size=0.0,
        )

    assert provider.calls == []


def test_api_rejects_resolved_config_for_a_different_request_before_provider_execution() -> None:
    config = tracker_config()
    observed = timestamp()
    repository = InMemoryTrendlineFamilyRepository()
    provider = SequenceProvider((valid_result(candidate(config, observed)),))

    with pytest.raises(ContractValidationError, match="identity"):
        update_trendline_families(
            tracker_ohlcv(observed),
            asset="ETHUSDT",
            timeframe="4h",
            repository=repository,
            config=config,
            provider=provider,
        )

    assert provider.calls == []
    assert repository.latest_snapshot("BTCUSDT", "1h") is None
    assert repository.latest_snapshot("ETHUSDT", "4h") is None


def test_api_rejects_runtime_override_when_config_is_already_resolved() -> None:
    config = tracker_config()
    observed = timestamp()
    provider = SequenceProvider((valid_result(candidate(config, observed)),))

    with pytest.raises(ContractValidationError, match="runtime_override"):
        update_trendline_families(
            tracker_ohlcv(observed),
            asset=config.asset,
            timeframe=config.timeframe,
            repository=InMemoryTrendlineFamilyRepository(),
            config=config,
            runtime_override={},
            provider=provider,
        )

    assert provider.calls == []


@pytest.mark.parametrize("asset,timeframe", (("", "1h"), ("BTCUSDT", ""), (None, "1h")))
def test_api_rejects_empty_request_identity(asset: str | None, timeframe: str) -> None:
    with pytest.raises(ContractValidationError, match="non-empty"):
        update_trendline_families(
            tracker_ohlcv(timestamp()),
            asset=asset,  # type: ignore[arg-type]
            timeframe=timeframe,
            repository=InMemoryTrendlineFamilyRepository(),
            provider=SequenceProvider(()),
        )
