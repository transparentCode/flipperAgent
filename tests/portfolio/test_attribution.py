"""Tests for libs/portfolio/attribution.py — PnL grouping."""

import pytest

from libs.contracts.schemas import ClosedTrade, PnLAttribution
from libs.portfolio.attribution import attribute_pnl


def _make_trade(pnl: float, asset: str = "BTCUSDT", model: str = "ModelA",
                timeframe: str = "1h", **kw) -> ClosedTrade:
    defaults = dict(
        trade_id="t1",
        asset=asset,
        direction=1,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        realized_pnl=pnl,
        realized_pnl_pct=pnl,
        entry_timestamp=1000.0,
        exit_timestamp=2000.0,
        duration_seconds=1000.0,
        source_model=model,
        source_timeframe=timeframe,
    )
    defaults.update(kw)
    return ClosedTrade(**defaults)


class TestAttributePnl:
    def test_empty(self):
        assert attribute_pnl([], "asset") == []

    def test_single_asset(self):
        trades = [_make_trade(10, asset="BTCUSDT", trade_id="t1")]
        result = attribute_pnl(trades, "asset")
        assert len(result) == 1
        assert result[0].group_key == "BTCUSDT"
        assert result[0].total_pnl == pytest.approx(10.0)
        assert result[0].trade_count == 1
        assert result[0].pnl_pct_of_total == pytest.approx(100.0)

    def test_multiple_assets(self):
        trades = [
            _make_trade(10, asset="BTCUSDT", trade_id="t1"),
            _make_trade(-5, asset="ETHUSDT", trade_id="t2"),
            _make_trade(20, asset="BTCUSDT", trade_id="t3"),
        ]
        result = attribute_pnl(trades, "asset")
        assert len(result) == 2
        # Sorted by total_pnl desc
        assert result[0].group_key == "BTCUSDT"
        assert result[0].total_pnl == pytest.approx(30.0)
        assert result[1].group_key == "ETHUSDT"
        assert result[1].total_pnl == pytest.approx(-5.0)

    def test_group_by_model(self):
        trades = [
            _make_trade(10, model="TrendModel", trade_id="t1"),
            _make_trade(-3, model="MeanRevert", trade_id="t2"),
            _make_trade(5, model="TrendModel", trade_id="t3"),
        ]
        result = attribute_pnl(trades, "model")
        assert len(result) == 2
        assert result[0].group_key == "TrendModel"
        assert result[0].total_pnl == pytest.approx(15.0)
        assert result[0].win_count == 2
        assert result[1].group_key == "MeanRevert"
        assert result[1].loss_count == 1

    def test_group_by_timeframe(self):
        trades = [
            _make_trade(10, timeframe="1h", trade_id="t1"),
            _make_trade(-5, timeframe="4h", trade_id="t2"),
        ]
        result = attribute_pnl(trades, "timeframe")
        assert len(result) == 2

    def test_pnl_pct_of_total(self):
        trades = [
            _make_trade(75, asset="BTCUSDT", trade_id="t1"),
            _make_trade(25, asset="ETHUSDT", trade_id="t2"),
        ]
        result = attribute_pnl(trades, "asset")
        btc = [r for r in result if r.group_key == "BTCUSDT"][0]
        eth = [r for r in result if r.group_key == "ETHUSDT"][0]
        assert btc.pnl_pct_of_total == pytest.approx(75.0)
        assert eth.pnl_pct_of_total == pytest.approx(25.0)

    def test_unknown_model_uses_placeholder(self):
        trades = [_make_trade(10, model="", trade_id="t1")]
        result = attribute_pnl(trades, "model")
        assert len(result) == 1
        assert result[0].group_key == "(unknown)"

    def test_win_loss_counts(self):
        trades = [
            _make_trade(10, asset="A", trade_id="t1"),
            _make_trade(-5, asset="A", trade_id="t2"),
            _make_trade(3, asset="A", trade_id="t3"),
        ]
        result = attribute_pnl(trades, "asset")
        assert result[0].win_count == 2
        assert result[0].loss_count == 1
        assert result[0].max_win == pytest.approx(10.0)
        assert result[0].max_loss == pytest.approx(-5.0)
