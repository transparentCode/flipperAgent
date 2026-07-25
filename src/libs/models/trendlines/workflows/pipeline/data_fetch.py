"""Data fetching helpers for trendlines pipeline workflows."""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from importlib import import_module
from typing import Any, Dict, Optional

import pandas as pd

from app.trendlines.data import TrendlineDataRequest, TrendlineDatasetManifest, load_dataset


def _build_default_connector() -> Any:
    connector_module = import_module("app.connectors.BinanceConnector")
    connector_cls = getattr(connector_module, "BinanceConnector")
    return connector_cls()


def download_historical_data(
    symbol: str,
    timeframe: str,
    from_date: str,
    to_date: str,
    *,
    connector: Any = None,
    quiet: bool = False,
) -> pd.DataFrame | None:
    """Paginated download of historical klines from Binance."""

    start_dt = pd.to_datetime(from_date)
    end_dt = pd.to_datetime(to_date)
    current_start = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    all_chunks = []
    client = connector or _build_default_connector()

    if not quiet:
        print(f"Fetching {symbol} {timeframe} from {start_dt.date()} to {end_dt.date()}...")

    while current_start < end_ts:
        df = client.get_futures_klines(
            symbol=symbol,
            interval=timeframe,
            start_time=current_start,
            end_time=end_ts,
            limit=1000,
        )
        if df.empty:
            break
        all_chunks.append(df)
        last_close_ts = int(df["close_time"].iloc[-1].timestamp() * 1000)
        next_start = last_close_ts + 1
        if next_start <= current_start:
            break
        current_start = next_start
        _time.sleep(0.1)

    if not all_chunks:
        return None

    full_df = pd.concat(all_chunks)
    full_df = full_df[~full_df.index.duplicated(keep="first")]
    full_df = full_df[(full_df.index >= start_dt) & (full_df.index <= end_dt)]
    return full_df


def fetch_pipeline_workflow_data(
    request: TrendlineDataRequest,
    *,
    connector: Any = None,
    quiet: bool = False,
) -> tuple[dict[str, pd.DataFrame], TrendlineDatasetManifest]:
    """Fetch multi-timeframe OHLCV data through an injected Binance connector."""

    if request.source.lower() != "binance":
        raise ValueError(f"Unsupported data source for trendlines pipeline workflow: {request.source}")

    start_date = request.start_date
    if start_date is None:
        lookback_days = request.lookback_days if request.lookback_days is not None else 120
        start_date = (datetime.now(timezone.utc) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = request.end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client = connector or _build_default_connector()

    def loader(incoming: TrendlineDataRequest) -> dict[str, pd.DataFrame]:
        mtf_data: dict[str, pd.DataFrame] = {}
        for timeframe in incoming.timeframes:
            frame = download_historical_data(
                incoming.asset,
                timeframe,
                start_date,
                end_date,
                connector=client,
                quiet=quiet,
            )
            if frame is not None and not frame.empty:
                mtf_data[timeframe] = frame
        return mtf_data

    return load_dataset(
        request,
        loader,
        start_ts=start_date,
        end_ts=end_date,
        metadata={"source": "binance", "requested_timeframes": list(request.timeframes)},
    )


__all__ = [
    "download_historical_data",
    "fetch_pipeline_workflow_data",
]
