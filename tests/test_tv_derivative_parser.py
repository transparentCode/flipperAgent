"""Tests for TradingView derivative single-series parsing."""

from __future__ import annotations

import json

from apps.scraper_app.providers.tradingview.interceptor import (
    extract_single_series_from_tv_response,
    parse_tv_messages,
)


def _frame(payload: dict) -> str:
    text = json.dumps(payload)
    return f"~m~{len(text)}~m~{text}"


def test_extract_single_series_from_timescale_update():
    raw = _frame(
        {
            "m": "timescale_update",
            "p": [
                {},
                {
                    "sds_1": {
                        "s": [
                            {"v": [1717200000, 123.45]},
                            {"v": [1717203600, 125.0]},
                        ]
                    }
                },
            ],
        }
    )

    messages = parse_tv_messages(raw)
    points = extract_single_series_from_tv_response(messages)

    assert points == [
        {"timestamp": 1717200000000, "value": 123.45},
        {"timestamp": 1717203600000, "value": 125.0},
    ]


def test_single_series_parser_uses_close_for_oi_ohlc_shape():
    raw = _frame(
        {
            "m": "du",
            "p": [
                {
                    "sds_1": {
                        "s": [
                            {"v": [1717200000, 10.0, 12.0, 9.5, 11.5]},
                        ]
                    }
                }
            ],
        }
    )

    messages = parse_tv_messages(raw)
    points = extract_single_series_from_tv_response(messages)

    assert points == [{"timestamp": 1717200000000, "value": 11.5}]


def test_single_series_parser_ignores_ohlcv_candles_and_auxiliary_series():
    raw = _frame(
        {
            "m": "du",
            "p": [
                {
                    "sds_1": {
                        "s": [
                            {"v": [1717200000, 1.0]},
                            {"v": [1717203600, 10, 11, 9, 10.5, 2000]},
                        ]
                    },
                    "sds_2": {"s": [{"v": [1577836800, 99.0]}]},
                }
            ],
        }
    )

    messages = parse_tv_messages(raw)
    points = extract_single_series_from_tv_response(messages)

    assert points == [{"timestamp": 1717200000000, "value": 1.0}]
