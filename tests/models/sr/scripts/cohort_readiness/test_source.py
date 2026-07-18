from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.cohort_readiness.source import (
    effective_provider_request_bounds,
    fetch_new_asset_sources,
    validate_provider_frame,
)

from .conftest import frame_for_asset


class SpyAdapter:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    async def get_historical_ohlcv(self, symbol, timeframe, since=None, until=None, limit=None):
        self.calls.append((symbol, timeframe, since, until, limit))
        return self.frames[symbol]


class ProviderFrameSubclass(pd.DataFrame):
    pass


def test_tao_source_is_exact_and_provider_free(tao_source):
    assert tao_source.source_id == "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
    assert tao_source.bars_sha256 == "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
    assert tao_source.row_count == 629
    assert tao_source.provider_calls == 0
    assert tao_source.bars[0].open_time.isoformat() == "2024-04-11T00:00:00+00:00"
    assert tao_source.bars[-1].closed_at.isoformat() == "2025-12-31T00:00:00+00:00"


def test_three_provider_calls_are_bounded_and_canonical(cohort_config, tao_source, resolved_configs):
    _, _, hashes = resolved_configs
    frames = {asset: frame_for_asset(tao_source, asset) for asset in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
    adapter = SpyAdapter(frames)
    sources = asyncio.run(fetch_new_asset_sources(cohort_config, adapter=adapter, expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_hashes=hashes))
    since, until = effective_provider_request_bounds(cohort_config)
    assert [call[0] for call in adapter.calls] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert all(call[1:] == ("1d", since, until, 1000) for call in adapter.calls)
    assert [source.provider_calls for source in sources] == [1, 1, 1]


def test_documented_binance_taker_column_is_allowed(cohort_config, tao_source, resolved_configs):
    _, _, hashes = resolved_configs
    frame = frame_for_asset(tao_source, "BTCUSDT")
    frame["taker_buy_base"] = frame["volume"]
    source = validate_provider_frame(frame, config=cohort_config, asset="BTCUSDT", expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_sr_config_hash=hashes["BTCUSDT"][0], resolved_input_hash=hashes["BTCUSDT"][1])
    assert source.row_count == 629


def test_real_pandas_dataframe_is_accepted_exactly(cohort_config, tao_source, resolved_configs):
    _, _, hashes = resolved_configs
    frame = frame_for_asset(tao_source, "BTCUSDT")
    assert type(frame) is pd.DataFrame
    source = validate_provider_frame(frame, config=cohort_config, asset="BTCUSDT", expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_sr_config_hash=hashes["BTCUSDT"][0], resolved_input_hash=hashes["BTCUSDT"][1])
    assert source.row_count == 629


@pytest.mark.parametrize("frame_factory", [ProviderFrameSubclass, lambda frame: object()])
def test_provider_frame_lookalikes_and_subclasses_are_rejected(cohort_config, tao_source, resolved_configs, frame_factory):
    _, _, hashes = resolved_configs
    frame = frame_factory(frame_for_asset(tao_source, "BTCUSDT"))
    with pytest.raises(ContractValidationError, match="provider result must be exactly pandas.DataFrame"):
        validate_provider_frame(frame, config=cohort_config, asset="BTCUSDT", expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_sr_config_hash=hashes["BTCUSDT"][0], resolved_input_hash=hashes["BTCUSDT"][1])


@pytest.mark.parametrize("column", ["unknown", "taker_buy_base_asset_volume"])
def test_unsupported_provider_columns_are_rejected(cohort_config, tao_source, resolved_configs, column):
    _, _, hashes = resolved_configs
    frame = frame_for_asset(tao_source, "BTCUSDT")
    frame[column] = frame["volume"]
    with pytest.raises(ContractValidationError):
        validate_provider_frame(frame, config=cohort_config, asset="BTCUSDT", expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_sr_config_hash=hashes["BTCUSDT"][0], resolved_input_hash=hashes["BTCUSDT"][1])


@pytest.mark.parametrize(
    "change",
    [
        lambda frame: frame.drop(frame.index[-1], inplace=True),
        lambda frame: frame.iloc.__setitem__((1, 0), frame.iloc[1, 0] + 86_400_000),
        lambda frame: frame.iloc.__setitem__((0, 1), float("inf")),
        lambda frame: frame.iloc.__setitem__((0, 4), -1.0),
    ],
)
def test_provider_data_mutations_fail_closed(cohort_config, tao_source, resolved_configs, change):
    _, _, hashes = resolved_configs
    frame = frame_for_asset(tao_source, "BTCUSDT")
    change(frame)
    with pytest.raises(ContractValidationError):
        validate_provider_frame(frame, config=cohort_config, asset="BTCUSDT", expected_grid=tuple(bar.open_time for bar in tao_source.bars), resolved_sr_config_hash=hashes["BTCUSDT"][0], resolved_input_hash=hashes["BTCUSDT"][1])
