from datetime import timedelta
import asyncio

import pytest

from libs.models.sr.research.studies.relative_salience_rank_utility.config import (
    END,
    START,
    load_relative_salience_rank_config,
)
from libs.models.sr.research.studies.relative_salience_rank_utility.source import (
    BlockedSourceError,
    canonicalize_provider_response,
    fetch_and_freeze_source,
)


class Frame:
    def __init__(self, rows, columns):
        self.columns = columns
        self._rows = rows

    def itertuples(self, *, index, name):
        assert index is False and name is None
        return iter(self._rows)


def _rows(timeframe: str):
    count = 181 if timeframe == "1d" else 362
    step = timedelta(days=1) if timeframe == "1d" else timedelta(hours=12)
    return tuple(
        (
            int((START + index * step).timestamp() * 1000),
            100.0 + index, 102.0 + index, 99.0 + index, 101.0 + index,
            10.0 + index, 5.0 + index,
        )
        for index in range(count)
    )


def test_provider_schema_includes_non_feature_taker_buy_base() -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    columns = ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base")
    bars = canonicalize_provider_response(Frame(_rows("1d"), columns), asset="TAOUSDT", timeframe="1d", config=config)
    assert len(bars) == 181
    assert bars[0].volume == 10.0


@pytest.mark.parametrize(
    "columns",
    (
        ("timestamp", "open", "high", "low", "close", "volume"),
        ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base", "unknown"),
        ("open", "timestamp", "high", "low", "close", "volume", "taker_buy_base"),
    ),
)
def test_provider_schema_fails_closed(columns) -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    with pytest.raises(BlockedSourceError):
        canonicalize_provider_response(Frame(_rows("12h"), columns), asset="TAOUSDT", timeframe="12h", config=config)


def test_provider_rejects_negative_taker_value() -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    rows = list(_rows("12h"))
    rows[0] = (*rows[0][:-1], -1.0)
    with pytest.raises(BlockedSourceError):
        canonicalize_provider_response(Frame(tuple(rows), ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base")), asset="TAOUSDT", timeframe="12h", config=config)


def test_real_adapter_parser_taker_value_does_not_change_ohlcv_bars() -> None:
    from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter

    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")

    class Client:
        def klines(self, *_args, **_kwargs):
            return [
                [row[0], str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]), row[0] + 86_399_999, "0", 1, str(row[6]), "0", "0"]
                for row in _rows("1d")
            ]

    adapter = BinanceNativeAdapter.__new__(BinanceNativeAdapter)
    adapter.client = Client()
    parsed = adapter._fetch_and_parse_klines_sync("TAOUSDT", "1d")
    original = canonicalize_provider_response(parsed, asset="TAOUSDT", timeframe="1d", config=config)
    altered = parsed.copy(deep=True)
    altered.loc[altered.index[0], "taker_buy_base"] += 99.0
    changed_taker_only = canonicalize_provider_response(altered, asset="TAOUSDT", timeframe="1d", config=config)
    assert tuple(parsed.columns) == ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base")
    assert tuple(bar.to_payload() for bar in original) == tuple(bar.to_payload() for bar in changed_taker_only)


def test_frozen_source_requires_exactly_one_call_for_each_cohort() -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    columns = ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base")

    class Adapter:
        def __init__(self):
            self.calls = []

        async def get_historical_ohlcv(self, asset, timeframe, **kwargs):
            self.calls.append((asset, timeframe, kwargs))
            return Frame(_rows(timeframe), columns)

    adapter = Adapter()
    bundle = asyncio.run(fetch_and_freeze_source(config, repo_root=".", implementation_commit="a" * 40, adapter_factory=lambda: adapter))
    assert tuple((item.asset, item.timeframe) for item in bundle.members) == (
        ("TAOUSDT", "1d"), ("ETHUSDT", "1d"), ("SOLUSDT", "1d"),
        ("TAOUSDT", "12h"), ("ETHUSDT", "12h"), ("SOLUSDT", "12h"),
    )
    assert len(adapter.calls) == 6
    assert all(call[2]["until"] == int(END.timestamp() * 1000) - 1 and call[2]["limit"] == 1000 for call in adapter.calls)
