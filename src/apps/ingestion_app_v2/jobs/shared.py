from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from apps.ingestion_app.models.tick_models import OHLCVRecord
from libs.common.config import ConfigManager
from libs.common.exceptions import DataIngestionError

config_manager = ConfigManager()


def require_context_value(
    ctx: dict[str, Any],
    key: str,
    *,
    error_message: str,
    context: dict[str, Any],
) -> Any:
    value = ctx.get(key)
    if value is None:
        raise DataIngestionError(error_message, context=context)
    return value


def build_ohlcv_records(symbol: str, frame: pd.DataFrame) -> list[OHLCVRecord]:
    return [
        OHLCVRecord(
            symbol=symbol,
            timestamp=int(row.timestamp),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in frame.itertuples(index=False)
    ]


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
