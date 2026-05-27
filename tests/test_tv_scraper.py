"""Tests for the TradingView scraper — protocol parsing, data extraction, and worker logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from apps.tv_scraper.interceptor import (
    TradingViewInterceptor,
    extract_ohlcv_from_tv_response,
    parse_tv_messages,
)
from apps.tv_scraper.worker import INDEX_KEY_MAP, TV_INDICES, fetch_tv_indices


# ---------------------------------------------------------------------------
# parse_tv_messages
# ---------------------------------------------------------------------------


class TestParseTvMessages:
    def test_single_json_message(self):
        payload = json.dumps({"m": "timescale_update", "p": []})
        raw = f"~m~{len(payload)}~m~{payload}"
        result = parse_tv_messages(raw)
        assert len(result) == 1
        assert result[0]["m"] == "timescale_update"

    def test_multiple_messages(self):
        p1 = json.dumps({"m": "du", "p": []})
        p2 = json.dumps({"m": "protocol_error"})
        raw = f"~m~{len(p1)}~m~{p1}~m~{len(p2)}~m~{p2}"
        result = parse_tv_messages(raw)
        assert len(result) == 2

    def test_non_json_payload_skipped(self):
        # Heartbeat pings are plain numbers, not JSON dicts
        raw = "~m~2~m~42"
        result = parse_tv_messages(raw)
        assert result == []

    def test_empty_string(self):
        assert parse_tv_messages("") == []

    def test_malformed_prefix_stops(self):
        assert parse_tv_messages("garbage") == []


# ---------------------------------------------------------------------------
# extract_ohlcv_from_tv_response
# ---------------------------------------------------------------------------


class TestExtractOhlcv:
    @staticmethod
    def _make_timescale_msg(bars: list[list]) -> dict:
        """Build a minimal TradingView timescale_update message."""
        return {
            "m": "timescale_update",
            "p": [
                {
                    "sds_1": {
                        "s": [{"v": bar} for bar in bars],
                    }
                }
            ],
        }

    def test_extracts_bars(self):
        ts = 1700000000
        bars_in = [[ts, 100.0, 110.0, 90.0, 105.0, 500.0]]
        msg = self._make_timescale_msg(bars_in)
        bars = extract_ohlcv_from_tv_response([msg])
        assert len(bars) == 1
        assert bars[0]["timestamp"] == ts * 1000
        assert bars[0]["open"] == 100.0
        assert bars[0]["close"] == 105.0
        assert bars[0]["volume"] == 500.0

    def test_du_message_type(self):
        ts = 1700000000
        msg = {
            "m": "du",
            "p": [{"sds_1": {"s": [{"v": [ts, 1.0, 2.0, 0.5, 1.5, 10.0]}]}}],
        }
        bars = extract_ohlcv_from_tv_response([msg])
        assert len(bars) == 1

    def test_ignores_non_chart_messages(self):
        msg = {"m": "quote_completed", "p": []}
        assert extract_ohlcv_from_tv_response([msg]) == []

    def test_handles_missing_v_gracefully(self):
        msg = {
            "m": "timescale_update",
            "p": [{"sds_1": {"s": [{"v": [1, 2]}]}}],  # too few elements
        }
        assert extract_ohlcv_from_tv_response([msg]) == []

    def test_multiple_bars(self):
        bars_in = [
            [1700000000, 100.0, 110.0, 90.0, 105.0, 500.0],
            [1700003600, 105.0, 115.0, 95.0, 110.0, 600.0],
        ]
        msg = self._make_timescale_msg(bars_in)
        bars = extract_ohlcv_from_tv_response([msg])
        assert len(bars) == 2


# ---------------------------------------------------------------------------
# TradingViewInterceptor helpers
# ---------------------------------------------------------------------------


class TestInterceptorHelpers:
    def test_map_timeframe_known(self):
        assert TradingViewInterceptor._map_timeframe("1h") == "60"
        assert TradingViewInterceptor._map_timeframe("4h") == "240"
        assert TradingViewInterceptor._map_timeframe("1D") == "D"
        assert TradingViewInterceptor._map_timeframe("1w") == "W"

    def test_map_timeframe_unknown_defaults_to_60(self):
        assert TradingViewInterceptor._map_timeframe("3h") == "60"

    def test_load_cookies_missing_file(self):
        interceptor = TradingViewInterceptor(cookies_path="/nonexistent/path.json")
        assert interceptor._load_cookies() is None

    def test_load_cookies_valid_file(self, tmp_path):
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([{"name": "session", "value": "abc"}]))
        interceptor = TradingViewInterceptor(cookies_path=str(cookie_file))
        cookies = interceptor._load_cookies()
        assert cookies == [{"name": "session", "value": "abc"}]


# ---------------------------------------------------------------------------
# TradingViewInterceptor.get_historical_ohlcv — Patchright not installed
# ---------------------------------------------------------------------------


class TestInterceptorNoPatchright:
    @pytest.mark.asyncio
    async def test_returns_empty_df_when_patchright_missing(self):
        interceptor = TradingViewInterceptor()
        # Simulate patchright not being installed
        import unittest.mock as _mock

        with _mock.patch.dict("sys.modules", {"patchright": None, "patchright.async_api": None}):
            df = await interceptor.get_historical_ohlcv("CRYPTOCAP:TOTAL2", "1h")
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# Worker — fetch_tv_indices
# ---------------------------------------------------------------------------


class TestFetchTvIndices:
    @pytest.mark.asyncio
    async def test_skips_when_no_interceptor(self):
        ctx: dict = {"redis": None, "db_pool": None, "tv_interceptor": None}
        # Should return without error
        await fetch_tv_indices(ctx)

    @pytest.mark.asyncio
    async def test_publishes_to_valkey(self):
        sample_df = pd.DataFrame(
            [
                {
                    "timestamp": 1700000000000,
                    "open": 100.0,
                    "high": 110.0,
                    "low": 90.0,
                    "close": 105.0,
                    "volume": 500.0,
                }
            ]
        )

        mock_interceptor = AsyncMock()
        mock_interceptor.get_historical_ohlcv = AsyncMock(return_value=sample_df)

        mock_redis = AsyncMock()

        ctx = {
            "redis": mock_redis,
            "db_pool": None,
            "tv_interceptor": mock_interceptor,
        }

        with patch("apps.tv_scraper.worker.asyncio.sleep", new_callable=AsyncMock):
            await fetch_tv_indices(ctx)

        # Should be called once per index (3 total)
        assert mock_redis.hset.call_count == 3

        # Check one of the calls has the right key pattern
        call_args_list = mock_redis.hset.call_args_list
        keys_called = [c.args[0] for c in call_args_list]
        assert "index:latest:TOTAL2" in keys_called
        assert "index:latest:TOTAL3" in keys_called
        assert "index:latest:BTC.D" in keys_called

    @pytest.mark.asyncio
    async def test_handles_empty_dataframe(self):
        empty_df = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        mock_interceptor = AsyncMock()
        mock_interceptor.get_historical_ohlcv = AsyncMock(return_value=empty_df)

        mock_redis = AsyncMock()

        ctx = {
            "redis": mock_redis,
            "db_pool": None,
            "tv_interceptor": mock_interceptor,
        }

        with patch("apps.tv_scraper.worker.asyncio.sleep", new_callable=AsyncMock):
            await fetch_tv_indices(ctx)

        # No Valkey writes when data is empty
        mock_redis.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_interceptor_exception(self):
        mock_interceptor = AsyncMock()
        mock_interceptor.get_historical_ohlcv = AsyncMock(
            side_effect=RuntimeError("Browser crashed")
        )
        mock_redis = AsyncMock()

        ctx = {
            "redis": mock_redis,
            "db_pool": None,
            "tv_interceptor": mock_interceptor,
        }

        with patch("apps.tv_scraper.worker.asyncio.sleep", new_callable=AsyncMock):
            # Should not raise
            await fetch_tv_indices(ctx)

        mock_redis.hset.assert_not_called()


# ---------------------------------------------------------------------------
# Worker — INDEX_KEY_MAP covers all TV_INDICES
# ---------------------------------------------------------------------------


class TestWorkerConfig:
    def test_index_key_map_covers_all_indices(self):
        for idx in TV_INDICES:
            assert idx in INDEX_KEY_MAP, f"{idx} missing from INDEX_KEY_MAP"
