from __future__ import annotations

from arq.cron import cron

from apps.ingestion_app.jobs import (
    poll_binance_ohlcv,
    poll_l2_depth,
    scheduled_asset_cleanup,
    scheduled_gap_fill,
)
from libs.common.config import ConfigManager
from libs.common.scheduling import BaseScheduler


class IngestionScheduler(BaseScheduler):
    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self.config_manager = config_manager or ConfigManager()

    def get_cron_jobs(self) -> list:
        schedules = self.config_manager.get("ingestion.orchestration.schedules", {})

        gap_fill_minutes = set(
            schedules.get("gap_fill_minutes", [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
        )
        gap_fill_timeout = schedules.get("gap_fill_timeout", 300)

        ohlcv_minutes = set(schedules.get("ohlcv_minutes", [0, 15, 30, 45]))
        ohlcv_timeout = schedules.get("ohlcv_timeout", 120)

        l2_depth_minutes = set(
            schedules.get("l2_depth_minutes", [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
        )
        l2_depth_timeout = schedules.get("l2_depth_timeout", 60)

        cleanup_minutes = set(schedules.get("cleanup_minutes", [2, 17, 32, 47]))
        cleanup_timeout = schedules.get("cleanup_timeout", 300)

        return [
            cron(
                scheduled_gap_fill,
                minute=gap_fill_minutes,
                run_at_startup=True,
                unique=True,
                timeout=gap_fill_timeout,
            ),
            cron(
                poll_binance_ohlcv,
                minute=ohlcv_minutes,
                run_at_startup=True,
                unique=True,
                timeout=ohlcv_timeout,
            ),
            cron(
                poll_l2_depth,
                minute=l2_depth_minutes,
                run_at_startup=True,
                unique=True,
                timeout=l2_depth_timeout,
            ),
            cron(
                scheduled_asset_cleanup,
                minute=cleanup_minutes,
                run_at_startup=True,
                unique=True,
                timeout=cleanup_timeout,
            ),
        ]
