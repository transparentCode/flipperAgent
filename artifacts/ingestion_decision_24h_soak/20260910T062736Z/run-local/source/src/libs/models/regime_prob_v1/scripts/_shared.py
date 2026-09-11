"""Shared CLI helpers for RegimeProbV1 scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_prob_v1.feature_builder import build_regime_prob_feature_frame
from libs.models.regime_prob_v1.edge import build_regime_prob_edge_labels
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv


def load_ohlcv(
    *,
    asset: str,
    timeframe: str,
    input_csv: str | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> pd.DataFrame:
    """Load OHLCV from CSV or Binance and return a timestamp-indexed frame."""
    if input_csv:
        return load_ohlcv_csv(input_csv)
    since_ms = _parse_timestamp_ms(since)
    until_ms = _parse_timestamp_ms(until)
    raw = fetch_historical_ohlcv(
        asset.upper(),
        timeframe,
        since=since_ms,
        until=until_ms,
        limit=int(limit),
    )
    if raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = raw.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.set_index("timestamp").sort_index()


def load_ohlcv_csv(path: str) -> pd.DataFrame:
    """Load a timestamped OHLCV CSV into the canonical frame shape."""
    frame = pd.read_csv(path)
    timestamp_column = "timestamp" if "timestamp" in frame.columns else frame.columns[0]
    frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True)
    frame = frame.set_index(timestamp_column).sort_index()
    required = [column for column in ("open", "high", "low", "close", "volume") if column in frame.columns]
    return frame.loc[:, required].copy()


def load_context_frames(entries: list[str] | None) -> dict[str, pd.DataFrame]:
    """Load repeated KEY=PATH external-context arguments."""
    frames: dict[str, pd.DataFrame] = {}
    for item in entries or []:
        if "=" not in item:
            raise ValueError(f"Context entry must be NAME=PATH, got: {item}")
        name, path = item.split("=", 1)
        frames[name] = load_ohlcv_csv(path)
    return frames


def build_feature_and_labels(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    external_context_frames: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the standard feature and label bundle for offline studies."""
    feature_frame = build_regime_prob_feature_frame(
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        external_context_frames=external_context_frames,
    )
    label_result = build_regime_prob_edge_labels(feature_frame, ohlcv, timeframe=timeframe)
    return feature_frame, label_result.frame


def read_json(path: str | Path) -> Any:
    """Read a JSON file into Python objects."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    """Write a JSON payload with deterministic formatting."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: str | Path, text: str) -> None:
    """Write a UTF-8 text artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _parse_timestamp_ms(value: str | None) -> int | None:
    if not value:
        return None
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


__all__ = [
    "build_feature_and_labels",
    "load_context_frames",
    "load_ohlcv",
    "load_ohlcv_csv",
    "read_json",
    "write_json",
    "write_text",
]
