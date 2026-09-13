from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from apps.ingestion_app.planning import (
    IngestionPlan,
    compile_ingestion_plan,
)
from apps.ingestion_app.settings import IngestionSettings
from libs.common.exceptions import DataIngestionError
from tests.ingestion.runtime.test_supervisor import _settings

LIVE_PROVIDER_IDS = {"binance_native"}
HISTORICAL_PROVIDER_IDS = {"binance_native", "ccxt_binance"}


def _compile(settings: IngestionSettings) -> IngestionPlan:
    return compile_ingestion_plan(
        settings,
        live_provider_ids=LIVE_PROVIDER_IDS,
        historical_provider_ids=HISTORICAL_PROVIDER_IDS,
    )


def test_compiler_is_deterministic_and_contains_runtime_fields() -> None:
    settings = _settings(
        target_timeframes=("2h", "1h"),
        include_eth=True,
    )
    reordered = copy.deepcopy(settings.model_dump())
    reordered["assets"] = dict(reversed(list(reordered["assets"].items())))
    for asset in reordered["assets"].values():
        asset["instruments"] = dict(reversed(list(asset["instruments"].items())))

    first = _compile(settings)
    second = _compile(type(settings).model_validate(reordered))

    assert first == second
    assert isinstance(first, IngestionPlan)
    assert first.base_timeframe == "1m"
    assert first.reconnect_backoff_seconds == 0
    assert [lane_plan.lane.instrument_id for lane_plan in first.lanes] == [
        "BTC-TEST-PERP",
        "ETH-TEST-PERP",
    ]
    lane_plan = first.lanes[0]
    assert lane_plan.live_provider_id == "binance_native"
    assert lane_plan.live_symbol == "BTCUSDT"
    assert lane_plan.provider_order == ("binance_native", "ccxt_binance")
    assert tuple(lane_plan.target_durations) == ("1h", "2h")
    assert lane_plan.lookback_duration == timedelta(hours=2)
    assert first.lanes_by_lane[lane_plan.lane] is lane_plan


def test_compiled_plan_and_nested_mappings_are_immutable() -> None:
    plan = _compile(_settings(target_timeframes=("1h",)))
    lane_plan = plan.lanes[0]

    with pytest.raises(FrozenInstanceError):
        plan.base_timeframe = "5m"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.lanes_by_lane[lane_plan.lane] = lane_plan  # type: ignore[index]
    with pytest.raises(TypeError):
        lane_plan.provider_symbols["binance_native"] = "OTHER"  # type: ignore[index]
    with pytest.raises(TypeError):
        lane_plan.target_durations["1h"] = timedelta(hours=2)  # type: ignore[index]


def test_lookback_covers_base_when_target_is_shorter() -> None:
    raw = copy.deepcopy(_settings().model_dump())
    raw["base_timeframe"] = "5m"
    raw["timeframes"]["5m"] = {"duration_seconds": 300}
    raw["assets"]["BTC"]["instruments"]["BTC-TEST-PERP"]["timeframes"] = [
        "1m",
        "5m",
    ]

    plan = _compile(IngestionSettings.model_validate(raw))

    assert plan.lanes[0].base_duration == timedelta(minutes=5)
    assert plan.lanes[0].target_durations == {"1m": timedelta(minutes=1)}
    assert plan.lanes[0].lookback_duration == timedelta(minutes=5)


def test_all_disabled_settings_compile_to_an_empty_plan() -> None:
    settings = _settings()
    raw = copy.deepcopy(settings.model_dump())
    for asset in raw["assets"].values():
        asset["enabled"] = False
    settings = IngestionSettings.model_validate(raw)

    plan = compile_ingestion_plan(
        settings,
        live_provider_ids=(),
        historical_provider_ids=(),
    )

    assert plan.lanes == ()
    assert dict(plan.lanes_by_lane) == {}


def test_compiler_rejects_live_provider_not_in_composed_resources() -> None:
    with pytest.raises(DataIngestionError, match="not owned"):
        compile_ingestion_plan(
            _settings(),
            live_provider_ids=(),
            historical_provider_ids=HISTORICAL_PROVIDER_IDS,
        )


def test_compiler_rejects_historical_provider_not_owned_by_application() -> None:
    with pytest.raises(DataIngestionError, match="historical providers"):
        compile_ingestion_plan(
            _settings(),
            live_provider_ids=LIVE_PROVIDER_IDS,
            historical_provider_ids={"binance_native"},
        )
