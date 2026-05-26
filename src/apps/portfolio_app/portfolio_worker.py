"""PortfolioWorker — consumes fills:{asset} and builds portfolio analytics."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    ExecutionReport,
    OrderStatus,
    PositionState,
)
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.trade_journal import TradeJournal

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioWorker:
    """Consumes fills:{asset} and maintains portfolio analytics tables."""

    def __init__(
        self,
        asset: str,
        db_pool: Any,
        config_mgr: ConfigManager,
    ) -> None:
        self.asset = asset
        self.db_pool = db_pool
        self.config_mgr = config_mgr

        portfolio_cfg = config_mgr.get("portfolio", {})
        consumer_cfg = portfolio_cfg.get("consumer", {})

        self.fill_stream_key = f"fills:{asset}"
        self.group_name = consumer_cfg.get("group_name", "portfolio_app_fills_group")
        self.consumer_name = f"portfolio_worker_{asset}"
        self.batch_size = consumer_cfg.get("batch_size", 10)
        self.block_ms = consumer_cfg.get("block_ms", 2000)

        self.trade_journal = TradeJournal(db_pool)
        self.equity_builder = EquityCurveBuilder(db_pool)

        # Local position tracking for building ClosedTrade records
        self._open_positions: list[PositionState] = []
        # MAE/MFE watermarks keyed by id(position)
        self._position_watermarks: dict[int, dict[str, float]] = {}
        self.redis_client: Any = None

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer group."""
        self.redis_client = redis_client
        try:
            await self.redis_client.xgroup_create(
                self.fill_stream_key, self.group_name, id="0", mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create group: {e}")

    async def start(self) -> None:
        """Main loop — consume fills, build trade records, snapshot equity."""
        logger.info(f"Starting portfolio worker for {self.asset}")
        if not self.redis_client:
            logger.warning("No redis client — portfolio worker inactive")
            return

        streams = {self.fill_stream_key: ">"}

        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    streams,
                    count=self.batch_size,
                    block=self.block_ms,
                )
                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        try:
                            report = self._decode_report(payload)
                            await self._process_fill(report)
                        except Exception as e:
                            logger.error(f"Failed to process fill: {e}", exc_info=True)

                        sname = (
                            stream_name.decode("utf-8")
                            if isinstance(stream_name, bytes)
                            else stream_name
                        )
                        await self.redis_client.xack(
                            sname, self.group_name, message_id,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Portfolio worker error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_fill(self, report: ExecutionReport) -> None:
        """Process a single fill — update local positions, detect closes, write to DB."""
        if report.status != OrderStatus.FILLED:
            return

        if report.side == "buy":
            # Try FIFO match against open shorts
            matched_idx: int | None = None
            for i, pos in enumerate(self._open_positions):
                if pos.direction == -1:
                    matched_idx = i
                    break

            if matched_idx is not None:
                await self._close_position(matched_idx, report)
            else:
                self._open_long(report)

        elif report.side == "sell":
            # Try FIFO match against open longs
            matched_idx = None
            for i, pos in enumerate(self._open_positions):
                if pos.direction == 1:
                    matched_idx = i
                    break

            if matched_idx is not None:
                await self._close_position(matched_idx, report)
            else:
                self._open_short(report)

        # Update MAE/MFE watermarks for all remaining open positions
        for open_pos in self._open_positions:
            wm = self._position_watermarks.get(id(open_pos))
            if wm:
                if open_pos.direction == 1:
                    wm["worst_price"] = min(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = max(wm["best_price"], report.average_fill_price)
                else:
                    wm["worst_price"] = max(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = min(wm["best_price"], report.average_fill_price)

        # Snapshot equity after every fill
        await self._snapshot_equity(report.timestamp)

    def _open_long(self, report: ExecutionReport) -> None:
        """Open a new long position."""
        pos = PositionState(
            asset=report.asset,
            direction=1,
            entry_price=report.average_fill_price,
            current_price=report.average_fill_price,
            size=report.filled_size,
            unrealized_pnl=0.0,
            entry_timestamp=report.timestamp,
            source_model=report.metadata.get("model_name", ""),
            source_timeframe=report.metadata.get("timeframe", ""),
            stop_loss_price=report.stop_loss_price,
            take_profit_price=report.take_profit_price,
        )
        self._open_positions.append(pos)
        self._position_watermarks[id(pos)] = {
            "worst_price": report.average_fill_price,
            "best_price": report.average_fill_price,
        }

    def _open_short(self, report: ExecutionReport) -> None:
        """Open a new short position."""
        pos = PositionState(
            asset=report.asset,
            direction=-1,
            entry_price=report.average_fill_price,
            current_price=report.average_fill_price,
            size=report.filled_size,
            unrealized_pnl=0.0,
            entry_timestamp=report.timestamp,
            source_model=report.metadata.get("model_name", ""),
            source_timeframe=report.metadata.get("timeframe", ""),
            stop_loss_price=report.stop_loss_price,
            take_profit_price=report.take_profit_price,
        )
        self._open_positions.append(pos)
        self._position_watermarks[id(pos)] = {
            "worst_price": report.average_fill_price,
            "best_price": report.average_fill_price,
        }

    async def _close_position(self, idx: int, report: ExecutionReport) -> None:
        """Close a matched position, compute MAE/MFE, persist ClosedTrade."""
        pos = self._open_positions.pop(idx)
        watermarks = self._position_watermarks.pop(id(pos), {})

        pnl = pos.direction * (report.average_fill_price - pos.entry_price) * pos.size
        notional = pos.entry_price * pos.size
        pnl_pct = (pnl / notional) * 100 if notional > 0 else 0.0

        # Compute MAE/MFE as % of entry price
        if notional > 0 and watermarks:
            worst = watermarks.get("worst_price", pos.entry_price)
            best = watermarks.get("best_price", pos.entry_price)
            mae_pct = abs(min(0.0, pos.direction * (worst - pos.entry_price) / pos.entry_price)) * 100
            mfe_pct = abs(max(0.0, pos.direction * (best - pos.entry_price) / pos.entry_price)) * 100
        else:
            mae_pct = 0.0
            mfe_pct = 0.0

        closed = ClosedTrade(
            trade_id=uuid.uuid4().hex,
            asset=report.asset,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=report.average_fill_price,
            size=pos.size,
            realized_pnl=pnl,
            realized_pnl_pct=pnl_pct,
            commission_total=sum(f.commission for f in report.fills),
            slippage_bps=report.slippage_bps,
            entry_timestamp=pos.entry_timestamp,
            exit_timestamp=report.timestamp,
            duration_seconds=report.timestamp - pos.entry_timestamp,
            source_model=pos.source_model,
            source_timeframe=pos.source_timeframe,
            entry_order_id="",
            exit_order_id=report.order_id,
            mae_pct=mae_pct,
            mfe_pct=mfe_pct,
        )
        await self.trade_journal.save_closed_trade(closed)
        logger.info(f"Recorded closed trade — {report.asset} pnl={pnl:.4f}")

    async def _snapshot_equity(self, timestamp: float) -> None:
        """Read latest AccountSnapshot from DB and write an EquityPoint with exposure."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM risk_account_snapshots ORDER BY timestamp DESC LIMIT 1",
            )
        if not row:
            return

        equity = float(row["equity"])

        # Compute net/gross exposure from local open positions
        long_notional = sum(
            p.current_price * p.size for p in self._open_positions if p.direction == 1
        )
        short_notional = sum(
            p.current_price * p.size for p in self._open_positions if p.direction == -1
        )
        net_exposure_pct = ((long_notional - short_notional) / equity * 100) if equity > 0 else 0.0
        gross_exposure_pct = ((long_notional + short_notional) / equity * 100) if equity > 0 else 0.0

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            balance=float(row["balance"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            drawdown_pct=float(row["drawdown_pct"]),
            open_position_count=int(row["open_position_count"]),
        )
        await self.equity_builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)

    @staticmethod
    def _decode_report(payload: dict) -> ExecutionReport:
        """Decode Valkey bytes payload into ExecutionReport."""
        decoded: dict[str, Any] = {}
        for k, v in payload.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val

        fills_raw = decoded.get("fills", "[]")
        if isinstance(fills_raw, str):
            fills_raw = json.loads(fills_raw)

        metadata_raw = decoded.get("metadata", "{}")
        if isinstance(metadata_raw, str):
            metadata_raw = json.loads(metadata_raw)

        return ExecutionReport(
            order_id=decoded["order_id"],
            idempotency_key=decoded["idempotency_key"],
            asset=decoded["asset"],
            side=decoded["side"],
            requested_size=float(decoded["requested_size"]),
            filled_size=float(decoded["filled_size"]),
            requested_price=float(decoded["requested_price"]),
            average_fill_price=float(decoded["average_fill_price"]),
            status=decoded["status"],
            fills=fills_raw,
            slippage_bps=float(decoded.get("slippage_bps", 0)),
            stop_loss_price=float(decoded["stop_loss_price"]) if decoded.get("stop_loss_price") else None,
            take_profit_price=float(decoded["take_profit_price"]) if decoded.get("take_profit_price") else None,
            timestamp=float(decoded["timestamp"]),
            error_message=decoded.get("error_message", ""),
            metadata=metadata_raw,
        )
