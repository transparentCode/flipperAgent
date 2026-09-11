from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from libs.portfolio.attribution import attribute_pnl
from libs.portfolio.benchmark import build_benchmark_returns, compute_benchmark_comparison
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.metrics import compute_performance
from libs.portfolio.returns import compute_log_returns, resample_equity_curve
from libs.portfolio.trade_journal import TradeJournal
from libs.risk.position_tracker import PositionTracker


class PortfolioObservabilityService:
    def __init__(self, db_pool: Any, redis_client: Any | None = None) -> None:
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.equity_builder = EquityCurveBuilder(db_pool)
        self.trade_journal = TradeJournal(db_pool)

    async def health(self) -> dict[str, Any]:
        db_available = False
        valkey_available = False
        db_error: str | None = None
        valkey_error: str | None = None

        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchrow("SELECT 1")
            db_available = True
        except Exception as exc:
            db_error = str(exc)

        if self.redis_client is not None:
            try:
                valkey_available = bool(await self.redis_client.ping())
            except Exception as exc:
                valkey_error = str(exc)

        result: dict[str, Any] = {
            "status": "ok" if db_available else "degraded",
            "db_available": db_available,
            "valkey_available": valkey_available,
        }
        if db_error is not None:
            result["db_error"] = db_error
        if valkey_error is not None:
            result["valkey_error"] = valkey_error
        return result

    async def latest_equity(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT timestamp, equity, balance, unrealized_pnl,
                           drawdown_pct, open_position_count,
                           net_exposure_pct, gross_exposure_pct
                    FROM portfolio_equity_curve
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """
                )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if not row:
            return {"status": "no_data"}

        ts = float(row["timestamp"])
        ts_ms = ts * 1000 if ts < 1e12 else ts
        return {
            "timestamp": ts,
            "lag_ms": now_ms - int(ts_ms),
            "equity": float(row["equity"]),
            "balance": float(row["balance"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "drawdown_pct": float(row["drawdown_pct"]),
            "open_position_count": int(row["open_position_count"]),
            "net_exposure_pct": float(row["net_exposure_pct"]),
            "gross_exposure_pct": float(row["gross_exposure_pct"]),
            "status": "ok",
        }

    async def summary(self) -> dict[str, Any]:
        equity_result = await self.latest_equity()
        trades_result = await self._recent_trade_stats()
        return {"equity": equity_result, "trades": trades_result}

    async def equity_curve(
        self,
        *,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        max_points: int = 1000,
    ) -> dict[str, Any]:
        try:
            points = await self.equity_builder.get_equity_curve(
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                max_points=max_points,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "points": [], "count": 0}

        return {
            "status": "ok" if points else "no_data",
            "count": len(points),
            "points": [point.model_dump(mode="json") for point in points],
        }

    async def open_positions(self) -> dict[str, Any]:
        try:
            tracker = await PositionTracker.load_positions(self.db_pool)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "count": 0, "positions": []}

        positions = [position.model_dump(mode="json") for position in tracker.all_positions()]
        return {
            "status": "ok" if positions else "no_data",
            "count": len(positions),
            "positions": positions,
        }

    async def exposure_by_asset(self) -> dict[str, Any]:
        grouped = await self._grouped_exposure("asset")
        if grouped.get("status") == "error":
            return {"status": "error", "error": grouped["error"], "assets": []}
        return {
            "status": grouped["status"],
            "total_exposure": grouped["total_exposure"],
            "assets": grouped["groups"],
        }

    async def exposure_by_model(self) -> dict[str, Any]:
        return await self._grouped_exposure("model")

    async def exposure_by_timeframe(self) -> dict[str, Any]:
        return await self._grouped_exposure("timeframe")

    async def sleeves_summary(self) -> dict[str, Any]:
        try:
            tracker = await self._load_tracker()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        by_asset = await self._grouped_exposure_from_tracker(tracker, "asset")
        by_model = await self._grouped_exposure_from_tracker(tracker, "model")
        by_timeframe = await self._grouped_exposure_from_tracker(tracker, "timeframe")

        total_exposure = float(by_asset["total_exposure"])
        latest_equity = await self.latest_equity()
        equity_value = (
            float(latest_equity["equity"])
            if latest_equity.get("status") == "ok" and latest_equity.get("equity") is not None
            else None
        )
        gross_exposure_pct = (
            total_exposure / equity_value * 100
            if equity_value is not None and equity_value > 0
            else None
        )

        asset_groups = by_asset["groups"]
        top_bucket = asset_groups[0] if asset_groups else None
        herfindahl = 0.0
        if total_exposure > 0:
            for bucket in asset_groups:
                weight = float(bucket["gross_notional"]) / total_exposure
                herfindahl += weight * weight

        return {
            "status": "ok" if total_exposure > 0 else "no_data",
            "utilization": {
                "equity": equity_value,
                "gross_notional": total_exposure,
                "gross_exposure_pct": gross_exposure_pct,
                "open_position_count": tracker.get_position_count(),
            },
            "concentration": {
                "top_asset": top_bucket["group_key"] if top_bucket else None,
                "top_asset_gross_notional": float(top_bucket["gross_notional"]) if top_bucket else 0.0,
                "top_asset_weight_pct": float(top_bucket["gross_weight_pct"]) if top_bucket else 0.0,
                "asset_herfindahl_index": herfindahl,
            },
            "counts": {
                "assets": len(by_asset["groups"]),
                "models": len(by_model["groups"]),
                "timeframes": len(by_timeframe["groups"]),
            },
            "views": {
                "asset": by_asset["groups"],
                "model": by_model["groups"],
                "timeframe": by_timeframe["groups"],
            },
        }

    async def closed_trades(
        self,
        *,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        try:
            trades = await self.trade_journal.get_closed_trades(
                asset=asset,
                model=model,
                timeframe=timeframe,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit,
                offset=offset,
            )
            total = await self.trade_journal.get_trade_count(
                asset=asset,
                model=model,
                timeframe=timeframe,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "count": 0, "total": 0, "trades": []}

        return {
            "status": "ok" if trades else "no_data",
            "count": len(trades),
            "total": total,
            "trades": [trade.model_dump(mode="json") for trade in trades],
        }

    async def performance_summary(
        self,
        *,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        resample_interval_seconds: int = 3600,
        risk_free_rate: float = 0.0,
    ) -> dict[str, Any]:
        try:
            trades = await self.trade_journal.get_closed_trades(
                asset=asset,
                model=model,
                timeframe=timeframe,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=100000,
                offset=0,
            )
            equity_curve = await self.equity_builder.get_equity_curve(
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                max_points=100000,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if not equity_curve:
            return {"status": "no_data", "performance": None, "sample": {"trade_count": len(trades), "equity_points": 0}}

        returns = compute_log_returns(
            resample_equity_curve(equity_curve, interval_seconds=resample_interval_seconds),
        )
        performance = compute_performance(
            trades=trades,
            returns=returns,
            equity_curve=equity_curve,
            risk_free_rate=risk_free_rate,
            periods_per_year=max(1, int((365 * 24 * 3600) / resample_interval_seconds)),
        )
        return {
            "status": "ok",
            "performance": performance.model_dump(mode="json"),
            "sample": {
                "trade_count": len(trades),
                "equity_points": len(equity_curve),
                "return_points": len(returns),
                "resample_interval_seconds": resample_interval_seconds,
            },
        }

    async def pnl_attribution(
        self,
        *,
        group_by: str,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> dict[str, Any]:
        try:
            trades = await self.trade_journal.get_closed_trades(
                asset=asset,
                model=model,
                timeframe=timeframe,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=100000,
                offset=0,
            )
            grouped = attribute_pnl(trades, group_by=group_by)
        except Exception as exc:
            return {"status": "error", "group_by": group_by, "count": 0, "attribution": [], "error": str(exc)}

        return {
            "status": "ok" if grouped else "no_data",
            "group_by": group_by,
            "count": len(grouped),
            "attribution": [item.model_dump(mode="json") for item in grouped],
        }

    async def benchmark_comparison(
        self,
        *,
        benchmark_name: str,
        benchmark_prices: list[tuple[float, float]],
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        interval_seconds: int = 3600,
        risk_free_rate: float = 0.0,
    ) -> dict[str, Any]:
        try:
            equity_curve = await self.equity_builder.get_equity_curve(
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                max_points=100000,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if not equity_curve:
            return {"status": "no_data", "comparison": None, "sample": {"equity_points": 0, "benchmark_points": len(benchmark_prices)}}

        strategy_resampled = resample_equity_curve(equity_curve, interval_seconds=interval_seconds)
        strategy_returns = compute_log_returns(strategy_resampled)
        benchmark_returns = build_benchmark_returns(
            benchmark_prices=benchmark_prices,
            interval_seconds=interval_seconds,
        )
        comparison = compute_benchmark_comparison(
            strategy_returns=strategy_returns,
            benchmark_returns=benchmark_returns,
            periods_per_year=max(1, int((365 * 24 * 3600) / interval_seconds)),
            risk_free_rate=risk_free_rate,
            start_timestamp=strategy_resampled[0].timestamp if strategy_resampled else 0.0,
            end_timestamp=strategy_resampled[-1].timestamp if strategy_resampled else 0.0,
            benchmark_name=benchmark_name,
        )
        return {
            "status": "ok",
            "comparison": comparison.model_dump(mode="json"),
            "sample": {
                "equity_points": len(equity_curve),
                "strategy_return_points": len(strategy_returns),
                "benchmark_points": len(benchmark_prices),
                "benchmark_return_points": len(benchmark_returns),
                "interval_seconds": interval_seconds,
            },
        }

    async def _load_tracker(self) -> PositionTracker:
        return await PositionTracker.load_positions(self.db_pool)

    async def _grouped_exposure(self, group_by: str) -> dict[str, Any]:
        try:
            tracker = await self._load_tracker()
        except Exception as exc:
            return {"status": "error", "group_by": group_by, "total_exposure": 0.0, "groups": [], "error": str(exc)}
        return await self._grouped_exposure_from_tracker(tracker, group_by)

    async def _grouped_exposure_from_tracker(
        self,
        tracker: PositionTracker,
        group_by: str,
    ) -> dict[str, Any]:
        buckets: dict[str, dict[str, float | int | str]] = defaultdict(
            lambda: {
                "position_count": 0,
                "net_notional": 0.0,
                "gross_notional": 0.0,
                "long_notional": 0.0,
                "short_notional": 0.0,
            },
        )

        for position in tracker.all_positions():
            if group_by == "asset":
                key = position.asset
            elif group_by == "model":
                key = position.source_model or "(unknown)"
            elif group_by == "timeframe":
                key = position.source_timeframe or "(unknown)"
            else:
                raise ValueError(f"Unsupported group_by: {group_by}")

            bucket = buckets[key]
            notional = float(position.size * position.current_price)
            bucket["position_count"] = int(bucket["position_count"]) + 1
            bucket["gross_notional"] = float(bucket["gross_notional"]) + notional
            if position.direction == 1:
                bucket["long_notional"] = float(bucket["long_notional"]) + notional
                bucket["net_notional"] = float(bucket["net_notional"]) + notional
            else:
                bucket["short_notional"] = float(bucket["short_notional"]) + notional
                bucket["net_notional"] = float(bucket["net_notional"]) - notional

        total_exposure = float(tracker.get_total_exposure())
        groups = []
        for key, bucket in buckets.items():
            gross_notional = float(bucket["gross_notional"])
            groups.append(
                {
                    "group_key": key,
                    "position_count": int(bucket["position_count"]),
                    "net_notional": float(bucket["net_notional"]),
                    "gross_notional": gross_notional,
                    "long_notional": float(bucket["long_notional"]),
                    "short_notional": float(bucket["short_notional"]),
                    "gross_weight_pct": gross_notional / total_exposure * 100 if total_exposure > 0 else 0.0,
                }
            )
        groups.sort(key=lambda item: float(item["gross_notional"]), reverse=True)
        return {
            "status": "ok" if groups else "no_data",
            "group_by": group_by,
            "total_exposure": total_exposure,
            "groups": groups,
        }

    async def _recent_trade_stats(self) -> dict[str, Any]:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT realized_pnl, commission_total, duration_seconds, slippage_bps
                    FROM portfolio_closed_trades
                    ORDER BY exit_timestamp DESC
                    LIMIT 200
                    """
                )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        if not rows:
            return {"status": "no_data"}

        pnls = [
            float(row["realized_pnl"]) - float(row["commission_total"])
            for row in rows
        ]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl <= 0]
        return {
            "sample_size": len(pnls),
            "total_pnl": round(sum(pnls), 6),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 6),
            "avg_win": round(sum(wins) / len(wins), 6) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 6) if losses else 0.0,
            "avg_duration_seconds": round(
                sum(float(row["duration_seconds"]) for row in rows) / len(rows),
                2,
            ),
            "avg_slippage_bps": round(
                sum(float(row["slippage_bps"]) for row in rows) / len(rows),
                4,
            ),
            "status": "ok",
        }
