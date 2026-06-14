from __future__ import annotations

from fastapi.testclient import TestClient

from apps.portfolio_app.api.app import create_app
from apps.portfolio_app.observability.service import PortfolioObservabilityService


class _FakeRedis:
    async def ping(self) -> bool:
        return True


class _FakeConn:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])

    async def fetchrow(self, query, *args):
        if "SELECT 1" in query:
            return {"ok": 1}
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetch(self, query, *args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AcquireCtx(self.conn)


def test_portfolio_api_summary_and_health_routes() -> None:
    conn = _FakeConn(
        fetchrow_results=[
            {"timestamp": 1000.0, "equity": 10000.0, "balance": 9999.5, "unrealized_pnl": 0.5,
             "drawdown_pct": 0.0, "open_position_count": 1, "net_exposure_pct": 10.0, "gross_exposure_pct": 10.0},
        ],
        fetch_results=[
            [
                {"realized_pnl": 10.0, "commission_total": 0.5, "duration_seconds": 60.0, "slippage_bps": 2.0},
                {"realized_pnl": -4.0, "commission_total": 0.25, "duration_seconds": 120.0, "slippage_bps": 4.0},
            ],
        ],
    )
    service = PortfolioObservabilityService(_FakePool(conn), _FakeRedis())
    client = TestClient(create_app(observability_service=service, redis_client=_FakeRedis(), db_pool=_FakePool(conn)))

    health_response = client.get("/portfolio/health")
    assert health_response.status_code == 200
    assert health_response.json()["db_available"] is True
    assert health_response.json()["valkey_available"] is True

    summary_response = client.get("/portfolio/summary")
    assert summary_response.status_code == 200
    body = summary_response.json()
    assert body["equity"]["status"] == "ok"
    assert body["trades"]["total_pnl"] == 5.25


def test_portfolio_api_curve_positions_and_exposure_routes() -> None:
    class _FakeService:
        async def health(self):
            return {"status": "ok"}

        async def summary(self):
            return {"equity": {"status": "ok"}, "trades": {"status": "ok"}}

        async def latest_equity(self):
            return {"status": "ok", "equity": 10100.0}

        async def equity_curve(self, **kwargs):
            assert kwargs["max_points"] == 50
            return {
                "status": "ok",
                "count": 1,
                "points": [{"timestamp": 1.0, "equity": 10000.0, "balance": 10000.0,
                            "unrealized_pnl": 0.0, "drawdown_pct": 0.0, "open_position_count": 0}],
            }

        async def open_positions(self):
            return {"status": "ok", "count": 1, "positions": [{"asset": "BTCUSDT"}]}

        async def exposure_by_asset(self):
            return {"status": "ok", "total_exposure": 2500.0, "assets": [{"asset": "BTCUSDT"}]}

        async def exposure_by_model(self):
            return {
                "status": "ok",
                "group_by": "model",
                "total_exposure": 2500.0,
                "groups": [
                    {
                        "group_key": "Trend",
                        "position_count": 1,
                        "net_notional": 2500.0,
                        "gross_notional": 2500.0,
                        "long_notional": 2500.0,
                        "short_notional": 0.0,
                        "gross_weight_pct": 100.0,
                    }
                ],
            }

        async def exposure_by_timeframe(self):
            return {
                "status": "ok",
                "group_by": "timeframe",
                "total_exposure": 2500.0,
                "groups": [
                    {
                        "group_key": "1h",
                        "position_count": 1,
                        "net_notional": 2500.0,
                        "gross_notional": 2500.0,
                        "long_notional": 2500.0,
                        "short_notional": 0.0,
                        "gross_weight_pct": 100.0,
                    }
                ],
            }

        async def sleeves_summary(self):
            return {
                "status": "ok",
                "utilization": {
                    "equity": 10000.0,
                    "gross_notional": 2500.0,
                    "gross_exposure_pct": 25.0,
                    "open_position_count": 1,
                },
                "concentration": {
                    "top_asset": "BTCUSDT",
                    "top_asset_gross_notional": 2500.0,
                    "top_asset_weight_pct": 100.0,
                    "asset_herfindahl_index": 1.0,
                },
                "counts": {"assets": 1, "models": 1, "timeframes": 1},
                "views": {
                    "asset": [
                        {
                            "group_key": "BTCUSDT",
                            "position_count": 1,
                            "net_notional": 2500.0,
                            "gross_notional": 2500.0,
                            "long_notional": 2500.0,
                            "short_notional": 0.0,
                            "gross_weight_pct": 100.0,
                        }
                    ],
                    "model": [
                        {
                            "group_key": "Trend",
                            "position_count": 1,
                            "net_notional": 2500.0,
                            "gross_notional": 2500.0,
                            "long_notional": 2500.0,
                            "short_notional": 0.0,
                            "gross_weight_pct": 100.0,
                        }
                    ],
                    "timeframe": [
                        {
                            "group_key": "1h",
                            "position_count": 1,
                            "net_notional": 2500.0,
                            "gross_notional": 2500.0,
                            "long_notional": 2500.0,
                            "short_notional": 0.0,
                            "gross_weight_pct": 100.0,
                        }
                    ],
                },
            }

        async def recommend_rebalance(self):
            return {
                "status": "ok",
                "recommendation": {
                    "status": "ok",
                    "policy_name": "capped_asset_allocator",
                    "generated_at": 123.0,
                    "summary": {"asset_count": 1, "gross_notional": 2500.0},
                    "targets": [],
                    "constraints": {"max_asset_weight_pct": 40.0, "min_rebalance_delta_pct": 5.0},
                    "notes": ["Recommendation-only output; execution stays downstream."],
                    "error": None,
                },
                "error": None,
                "sample": {"asset_count": 1, "target_count": 0},
            }

        async def closed_trades(self, **kwargs):
            assert kwargs["limit"] == 25
            return {
                "status": "ok",
                "count": 1,
                "total": 1,
                "trades": [
                    {
                        "trade_id": "t1",
                        "asset": "BTCUSDT",
                        "direction": 1,
                        "entry_price": 100.0,
                        "exit_price": 110.0,
                        "size": 1.0,
                        "realized_pnl": 10.0,
                        "realized_pnl_pct": 10.0,
                        "commission_total": 0.1,
                        "slippage_bps": 1.0,
                        "entry_timestamp": 1000.0,
                        "exit_timestamp": 2000.0,
                        "duration_seconds": 1000.0,
                        "source_model": "Trend",
                        "source_timeframe": "1h",
                        "entry_order_id": "o1",
                        "exit_order_id": "o2",
                        "mae_pct": -1.0,
                        "mfe_pct": 3.0,
                    }
                ],
            }

        async def performance_summary(self, **kwargs):
            assert kwargs["resample_interval_seconds"] == 3600
            return {
                "status": "ok",
                "performance": {
                    "start_timestamp": 1000.0,
                    "end_timestamp": 2000.0,
                    "total_trades": 1,
                    "winning_trades": 1,
                    "losing_trades": 0,
                    "win_rate": 1.0,
                    "total_pnl": 10.0,
                    "gross_profit": 10.0,
                    "gross_loss": 0.0,
                    "profit_factor": 0.0,
                    "avg_trade_pnl": 10.0,
                    "avg_win": 10.0,
                    "avg_loss": 0.0,
                    "largest_win": 10.0,
                    "largest_loss": 0.0,
                    "avg_trade_duration_seconds": 1000.0,
                    "max_drawdown_pct": 0.0,
                    "max_drawdown_duration_seconds": 0.0,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "calmar_ratio": 0.0,
                    "expectancy": 10.0,
                    "payoff_ratio": 0.0,
                    "alpha": 0.0,
                    "beta": 0.0,
                    "information_ratio": 0.0,
                    "tracking_error": 0.0,
                },
                "sample": {"trade_count": 1, "equity_points": 2, "return_points": 1},
            }

        async def pnl_attribution(self, **kwargs):
            assert kwargs["group_by"] == "asset"
            return {
                "status": "ok",
                "group_by": "asset",
                "count": 1,
                "attribution": [
                    {
                        "group_key": "BTCUSDT",
                        "group_type": "asset",
                        "total_pnl": 10.0,
                        "trade_count": 1,
                        "win_count": 1,
                        "loss_count": 0,
                        "avg_pnl": 10.0,
                        "max_win": 10.0,
                        "max_loss": 0.0,
                        "pnl_pct_of_total": 100.0,
                    }
                ],
            }

        async def benchmark_comparison(self, **kwargs):
            assert kwargs["benchmark_name"] == "TOTAL3"
            return {
                "status": "ok",
                "comparison": {
                    "benchmark_name": "TOTAL3",
                    "strategy_return_pct": 5.0,
                    "benchmark_return_pct": 3.0,
                    "alpha": 0.5,
                    "beta": 1.1,
                    "correlation": 0.8,
                    "information_ratio": 0.4,
                    "tracking_error": 0.2,
                    "start_timestamp": 1000.0,
                    "end_timestamp": 2000.0,
                },
                "sample": {"benchmark_points": 3, "strategy_return_points": 2},
            }

    client = TestClient(create_app(observability_service=_FakeService()))

    latest_response = client.get("/portfolio/equity/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["equity"] == 10100.0

    curve_response = client.get("/portfolio/equity/curve", params={"max_points": 50})
    assert curve_response.status_code == 200
    assert curve_response.json()["count"] == 1

    positions_response = client.get("/portfolio/positions/open")
    assert positions_response.status_code == 200
    assert positions_response.json()["count"] == 1

    exposure_response = client.get("/portfolio/exposure/by-asset")
    assert exposure_response.status_code == 200
    assert exposure_response.json()["total_exposure"] == 2500.0

    exposure_model_response = client.get("/portfolio/exposure/by-model")
    assert exposure_model_response.status_code == 200
    assert exposure_model_response.json()["groups"][0]["group_key"] == "Trend"

    exposure_timeframe_response = client.get("/portfolio/exposure/by-timeframe")
    assert exposure_timeframe_response.status_code == 200
    assert exposure_timeframe_response.json()["groups"][0]["group_key"] == "1h"

    sleeves_response = client.get("/portfolio/sleeves")
    assert sleeves_response.status_code == 200
    assert sleeves_response.json()["utilization"]["gross_exposure_pct"] == 25.0
    assert sleeves_response.json()["concentration"]["top_asset"] == "BTCUSDT"

    recommendation_response = client.get("/portfolio/rebalance/recommendation")
    assert recommendation_response.status_code == 200
    assert recommendation_response.json()["recommendation"]["policy_name"] == "capped_asset_allocator"
    assert recommendation_response.json()["sample"]["target_count"] == 0

    trades_response = client.get("/portfolio/trades", params={"limit": 25})
    assert trades_response.status_code == 200
    assert trades_response.json()["count"] == 1
    assert trades_response.json()["trades"][0]["asset"] == "BTCUSDT"

    performance_response = client.get("/portfolio/performance", params={"resample_interval_seconds": 3600})
    assert performance_response.status_code == 200
    assert performance_response.json()["performance"]["total_trades"] == 1

    attribution_response = client.get("/portfolio/attribution", params={"group_by": "asset"})
    assert attribution_response.status_code == 200
    assert attribution_response.json()["attribution"][0]["group_key"] == "BTCUSDT"

    benchmark_response = client.post(
        "/portfolio/benchmark",
        json={
            "benchmark_name": "TOTAL3",
            "benchmark_prices": [
                {"timestamp": 1000.0, "price": 100.0},
                {"timestamp": 4600.0, "price": 102.0},
                {"timestamp": 8200.0, "price": 103.0},
            ],
        },
    )
    assert benchmark_response.status_code == 200
    assert benchmark_response.json()["comparison"]["benchmark_name"] == "TOTAL3"
