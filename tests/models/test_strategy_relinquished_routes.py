from __future__ import annotations

import asyncio

import pytest

from apps.strategy_app.runtime.runner import StrategyRuntimeRunner
from apps.strategy_app.runtime_pairs import build_strategy_pairs
from apps.strategy_app.settings import StrategyWorkerSettings, parse_relinquished_routes
from libs.common.config import ConfigManager


def _manager(*, relinquished: list[str] | None = None) -> ConfigManager:
    model_assets: dict[str, dict[str, dict[str, object]]] = {}
    for asset, timeframe in (
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "4h"),
        ("ETHUSDT", "4h"),
        ("XRPUSDT", "1h"),
        ("SOLUSDT", "1h"),
        ("BNBUSDT", "30m"),
        ("DOGEUSDT", "4h"),
    ):
        model_assets.setdefault(asset, {"timeframes": {}})["timeframes"][timeframe] = {
            "Momentum": {
                "enabled": True,
                "runtime": {
                    "decision_timeframe": timeframe,
                    "base_timeframe": "1m",
                    "trigger_mode": "on_bar_close",
                },
            }
        }
    manager = ConfigManager()
    manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    manager._state = {
        "models": {"assets": model_assets},
        "strategy": {"runtime": {"relinquished_routes": relinquished or []}},
    }
    return manager


def test_relinquished_routes_filter_only_exact_targets_and_preserve_catalog() -> None:
    manager = _manager(relinquished=["btcusdt:1h", "BTCUSDT:4h", "ETHUSDT:4h"])
    pairs = build_strategy_pairs(manager)

    assert {pair.key for pair in pairs} == {
        "BNBUSDT:30m",
        "DOGEUSDT:4h",
        "SOLUSDT:1h",
        "XRPUSDT:1h",
    }


def test_relinquished_route_syntax_is_strict_and_canonical() -> None:
    assert parse_relinquished_routes(["btcusdt:4h@1h", "ETHUSDT:4h"]) == (
        "BTCUSDT:4h@1h",
        "ETHUSDT:4h",
    )
    with pytest.raises(ValueError, match="duplicate"):
        parse_relinquished_routes(["BTCUSDT:1h", "btcusdt:1h"])
    with pytest.raises(ValueError, match="timeframe"):
        parse_relinquished_routes(["BTCUSDT:hour"])
    with pytest.raises(TypeError, match="list"):
        parse_relinquished_routes("BTCUSDT:1h")


def test_unknown_relinquished_route_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown"):
        build_strategy_pairs(_manager(relinquished=["ADAUSDT:1h"]))


class _FeatureGroupRedis:
    def __init__(self) -> None:
        self.groups: dict[tuple[str, str], str] = {}
        self.messages: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.acked: list[tuple[str, str, str]] = []
        self.feature_reads: list[tuple[str, str]] = []

    async def xgroup_create(
        self, stream: str, group: str, id: str = "0", mkstream: bool = True
    ) -> None:
        del mkstream
        self.groups.setdefault((stream, group), id)

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        *,
        count: int = 1,
        block: int = 1000,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        del consumer, count, block
        stream, requested = next(iter(streams.items()))
        if stream.startswith("features:"):
            self.feature_reads.append((stream, requested))
            messages = self.messages.get(stream, [])
            if not messages:
                return []
            return [(stream, [messages[0]])]
        return []

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append((stream, group, message_id))
        messages = self.messages.get(stream, [])
        self.messages[stream] = [item for item in messages if item[0] != message_id]
        return 1

    def seed(self, stream: str, message_id: str) -> None:
        self.messages.setdefault(stream, []).append((message_id, {"value": "1"}))


class _DrainFeatureWorker:
    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        settings: StrategyWorkerSettings,
        **_: object,
    ) -> None:
        self.stream = f"features:{asset}:{timeframe}"
        self.group = settings.consumer_group
        self.settings = settings
        self.redis = None

    async def connect(self, redis: _FeatureGroupRedis) -> None:
        self.redis = redis

    async def start(self) -> None:
        assert self.redis is not None
        response = await self.redis.xreadgroup(
            self.group,
            "rollback-consumer",
            {self.stream: ">"},
            count=1,
            block=1,
        )
        for stream, messages in response:
            for message_id, _payload in messages:
                await self.redis.xack(stream, self.group, message_id)
        await asyncio.Future()


@pytest.mark.asyncio
async def test_relinquishment_preserves_consumer_group_backlog_for_rollback() -> None:
    stream = "features:BTCUSDT:1h"
    redis = _FeatureGroupRedis()
    await redis.xgroup_create(stream, "strategy_d11a", id="0")
    redis.seed(stream, "1-0")
    settings = StrategyWorkerSettings(consumer_group="strategy_d11a")

    relinquished_pairs = build_strategy_pairs(_manager(relinquished=["BTCUSDT:1h"]))
    excluded_runner = StrategyRuntimeRunner(
        relinquished_pairs,
        worker_factory=_DrainFeatureWorker,
        worker_settings=settings,
    )
    await excluded_runner.connect(redis)
    await asyncio.sleep(0)
    assert stream not in {stream_key for stream_key, _cursor in redis.feature_reads}
    assert redis.messages[stream] == [("1-0", {"value": "1"})]
    await excluded_runner.stop()

    restored_runner = StrategyRuntimeRunner(
        build_strategy_pairs(_manager()),
        worker_factory=_DrainFeatureWorker,
        worker_settings=settings,
    )
    await restored_runner.connect(redis)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert (stream, ">") in redis.feature_reads
    assert redis.messages[stream] == []
    assert redis.acked == [(stream, "strategy_d11a", "1-0")]
    await restored_runner.stop()
