"""Tests for browser-scroll TradingView backfill helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "tv_browser_backfill",
    Path(__file__).resolve().parents[1] / "scripts" / "tv_browser_backfill.py",
)
tv_browser_backfill = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(tv_browser_backfill)


def test_extract_series_uses_close_for_ohlc_shape():
    messages = [
        {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {
                        "s": [
                            {"v": [1717200000, 1.0, 2.0, 0.5, 1.5]},
                            {"v": [1717203600, 0.01]},
                        ]
                    }
                }
            ],
        }
    ]

    rows = tv_browser_backfill.extract_series_rows(messages)

    assert rows == [
        {"timestamp": 1717200000, "value": 1.5},
        {"timestamp": 1717203600, "value": 0.01},
    ]


def test_extract_ohlcv_ignores_auxiliary_series_by_default():
    messages = [
        {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {"s": [{"v": [1717200000, 1, 2, 0.5, 1.5, 10]}]},
                    "sds_2": {"s": [{"v": [1577836800, 9, 9, 9, 9, 0]}]},
                }
            ],
        }
    ]

    rows = tv_browser_backfill.extract_ohlcv_rows(messages)

    assert rows == [
        {
            "timestamp": 1717200000,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
    ]


def test_rows_to_frame_dedupes_and_sorts():
    rows = [
        {"timestamp": 3, "value": 3.0},
        {"timestamp": 1, "value": 1.0},
        {"timestamp": 3, "value": 9.0},
    ]

    frame = tv_browser_backfill.rows_to_frame(rows)

    assert frame["timestamp"].tolist() == [1, 3]
    assert "datetime" in frame.columns


def test_load_cookies_sanitizes_domain_without_exposing_values(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps(
            [
                {"name": "session", "value": "secret", "domain": ".tradingview.com"},
                {"name": "bad"},
            ]
        )
    )

    cookies = tv_browser_backfill.load_cookies(str(cookie_file))

    assert len(cookies) == 1
    assert cookies[0]["domain"] == "tradingview.com"
    assert cookies[0]["name"] == "session"


def test_target_bars_for_two_years_1h():
    assert tv_browser_backfill.target_bars_for_years(2, "1h") == 17_520


def test_gap_check():
    frame = pd.DataFrame({"timestamp": [1_000, 2_800, 12_000]})

    gaps = tv_browser_backfill.check_gaps(frame, expected_seconds=1800)

    assert len(gaps) == 1
