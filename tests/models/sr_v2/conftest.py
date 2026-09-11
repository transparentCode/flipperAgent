from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from libs.models.sr_v2.config import SRV2ConfigResolver
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.features.time import grid_for


@pytest.fixture
def sr_v2_config():
    return SRV2ConfigResolver.from_yaml("configs/sr_v2.yaml").resolve()


@pytest.fixture
def sr_v2_now():
    return datetime(2024, 1, 2, 5, 15, tzinfo=UTC)


@pytest.fixture
def sr_v2_bars(sr_v2_config, sr_v2_now):
    result = {}
    for timeframe in sr_v2_config.ladder:
        duration = grid_for(timeframe).duration
        end = grid_for(timeframe).expected_closed_cutoff(sr_v2_now)
        start = end - duration * 21
        result[timeframe] = tuple(
            SRBar(
                timeframe=timeframe,
                bar_open_at=start + duration * index,
                bar_close_at=start + duration * (index + 1),
                market_as_of=start + duration * (index + 1),
                open=Decimal(100) + Decimal(index) / Decimal(10),
                high=Decimal(101) + Decimal(index) / Decimal(10),
                low=Decimal(99) + Decimal(index) / Decimal(10),
                close=Decimal("100.2") + Decimal(index) / Decimal(10),
                volume=Decimal(10),
                taker_buy_base=Decimal(5),
            )
            for index in range(21)
        )
    return result
