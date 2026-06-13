from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.ingestion_app.models.tick_models import L2DepthFeatureRecord
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger
from libs.models.regime_classification.l2_features import compute_l2_features

from apps.ingestion_app.jobs.shared import (
    config_manager,
    list_schedulable_symbols,
    require_context_value,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


@retry(
    retry=retry_if_exception_type(DataIngestionError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
async def _fetch_l2_depth_snapshot(binance_adapter: Any, symbol: str, depth_limit: int = 20) -> None:
    import numpy as np

    try:
        raw = await asyncio.to_thread(binance_adapter.client.depth, symbol=symbol, limit=depth_limit)
    except Exception as exc:
        raise DataIngestionError(
            f"Binance depth API failed for {symbol}: {exc}",
            context={"symbol": symbol},
        ) from exc

    bids = np.array([[float(price), float(size)] for price, size in raw.get("bids", [])], dtype=float)
    asks = np.array([[float(price), float(size)] for price, size in raw.get("asks", [])], dtype=float)
    if bids.size == 0 or asks.size == 0:
        logger.warning(f"[{symbol}] Empty L2 snapshot, skipping.")
        return

    features = compute_l2_features(
        bids,
        asks,
        top_n=min(config_manager.get("ingestion.l2_depth.top_n_imbalance", 5), len(bids)),
    )

    def _finite_or_none(value: float):
        return float(value) if np.isfinite(value) else None

    record = L2DepthFeatureRecord(
        timestamp=datetime.now(timezone.utc),
        symbol=symbol,
        bid_ask_imbalance=_finite_or_none(features.bid_ask_imbalance),
        depth_ratio=_finite_or_none(features.depth_ratio),
        spread_bps=_finite_or_none(features.spread_bps),
        depth_decay_bid=_finite_or_none(features.depth_decay_bid),
        depth_decay_ask=_finite_or_none(features.depth_decay_ask),
        best_bid=float(bids[0, 0]),
        best_ask=float(asks[0, 0]),
        bid_depth_total=float(bids[:, 1].sum()),
        ask_depth_total=float(asks[:, 1].sum()),
        snapshot_levels=len(bids),
    )

    try:
        ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
    except RuntimeError as exc:
        raise DataIngestionError(
            f"[{symbol}] DB writer pool not initialized for L2 depth",
            context={"symbol": symbol},
        ) from exc

    await ts_writer.insert_l2_depth([record])
    logger.info(
        f"[{symbol}] L2 depth features stored: spread={features.spread_bps:.1f}bps, "
        f"imbalance={features.bid_ask_imbalance:.3f}"
    )


async def poll_l2_depth(ctx: dict[str, Any]) -> None:
    binance_adapter = require_context_value(
        ctx,
        "binance_adapter",
        error_message="Binance adapter not found in worker context for L2 depth polling",
        context={},
    )
    symbols = await list_schedulable_symbols()
    if not symbols:
        logger.info("poll_l2_depth skipped: no schedulable assets.")
        return
    depth_limit = config_manager.get("ingestion.l2_depth.snapshot_levels", 20)

    failures = 0
    for symbol in symbols:
        try:
            await _fetch_l2_depth_snapshot(binance_adapter, symbol, depth_limit)
        except Exception as exc:
            failures += 1
            logger.error(f"[{symbol}] L2 depth poll failed: {exc}", exc_info=True)
        await asyncio.sleep(0.2)

    succeeded = len(symbols) - failures
    if failures > 0:
        logger.warning(f"poll_l2_depth: {failures}/{len(symbols)} asset(s) failed.")
    if succeeded == 0:
        raise DataIngestionError(
            f"poll_l2_depth: all {len(symbols)} asset(s) failed",
            context={"symbols": symbols},
        )
    logger.info(f"poll_l2_depth completed: {succeeded}/{len(symbols)} asset(s) stored.")
