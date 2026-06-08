"""Tests for direct TradingView backfill helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


_SPEC = importlib.util.spec_from_file_location(
    "tv_backfill",
    Path(__file__).resolve().parents[1] / "scripts" / "tv_backfill.py",
)
tv_backfill = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(tv_backfill)


def test_bars_for_two_years_1h_and_30m():
    assert tv_backfill._bars_for_years(2, "1h") == 17_520
    assert tv_backfill._bars_for_years(2, "30m") == 35_040


def test_symbol_parsing_accepts_full_or_default_exchange():
    assert tv_backfill._split_symbol("CRYPTOCAP:TOTAL2", "BINANCE") == (
        "TOTAL2",
        "CRYPTOCAP",
    )
    assert tv_backfill._split_symbol("BNBUSDTPERP_OI", "BINANCE") == (
        "BNBUSDTPERP_OI",
        "BINANCE",
    )
    assert tv_backfill._full_symbol("TOTAL3", "CRYPTOCAP") == "CRYPTOCAP:TOTAL3"


def test_extract_ohlcv_and_single_series_values():
    messages = [
        {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {
                        "s": [
                            {"v": [1717200000, 10, 11, 9, 10.5, 1000]},
                            {"v": [1717203600, 580787.75]},
                        ]
                    }
                }
            ],
        }
    ]

    bars = tv_backfill._extract_bars(messages)
    points = tv_backfill._extract_single_series(messages)

    assert bars == [
        {
            "timestamp": 1717200000,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        }
    ]
    assert points == [
        {"timestamp": 1717200000, "value": 10.5},
        {"timestamp": 1717203600, "value": 580787.75},
    ]


def test_extract_ignores_auxiliary_series_by_default():
    messages = [
        {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {
                        "s": [{"v": [1717200000, 10, 11, 9, 10.5, 1000]}]
                    },
                    "sds_2": {
                        "s": [{"v": [1577836800, 1, 1, 1, 1, 0]}]
                    },
                }
            ],
        }
    ]

    bars = tv_backfill._extract_bars(messages)

    assert len(bars) == 1
    assert bars[0]["timestamp"] == 1717200000


def test_extract_single_series_uses_close_for_ohlc_shaped_derivatives():
    messages = [
        {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {
                        "s": [
                            {
                                "v": [
                                    1717200000,
                                    646747.16,
                                    646747.16,
                                    645629.38,
                                    645744.8,
                                ]
                            }
                        ]
                    }
                }
            ],
        }
    ]

    points = tv_backfill._extract_single_series(messages)

    assert points == [{"timestamp": 1717200000, "value": 645744.8}]


def test_gap_check_uses_timeframe_seconds():
    df = pd.DataFrame(
        {
            "timestamp": [1717200000, 1717201800, 1717210800],
            "value": [1.0, 1.1, 1.2],
        }
    )

    gaps = tv_backfill.check_gaps(df, expected_interval_seconds=1800)

    assert len(gaps) == 1
    assert "2.5h" in gaps[0]
