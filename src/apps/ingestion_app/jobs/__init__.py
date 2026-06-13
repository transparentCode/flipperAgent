"""Modular ingestion worker jobs for the v2 mirror."""

from apps.ingestion_app.jobs.cleanup import purge_removed_asset, scheduled_asset_cleanup
from apps.ingestion_app.jobs.gap_fill import run_rest_gap_fill, scheduled_gap_fill
from apps.ingestion_app.jobs.l2_depth import poll_l2_depth
from apps.ingestion_app.jobs.topup import poll_binance_ohlcv

__all__ = [
    "poll_binance_ohlcv",
    "run_rest_gap_fill",
    "scheduled_gap_fill",
    "purge_removed_asset",
    "scheduled_asset_cleanup",
    "poll_l2_depth",
]
