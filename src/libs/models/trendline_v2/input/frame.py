"""Validated, point-in-time confirmed OHLCV input."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from ..domain.identity import require_hash
from ..domain.validation import ContractValidationError, require_string, require_utc

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class ConfirmedOHLCVArrays:
    """Read-only float64 arrays derived from one validated frame."""

    timestamps: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __post_init__(self) -> None:
        arrays = {
            "timestamps": self.timestamps,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
        lengths: set[int] = set()
        for name, value in arrays.items():
            if not isinstance(value, np.ndarray) or value.ndim != 1:
                raise ContractValidationError(f"arrays.{name} must be one-dimensional")
            lengths.add(len(value))
            if name != "timestamps" and value.dtype != np.float64:
                raise ContractValidationError(f"arrays.{name} must be float64")
            value.setflags(write=False)
        if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
            raise ContractValidationError("all arrays must be non-empty and equally sized")
        object.__setattr__(self, "timestamps", self.timestamps)


def _normalized_frame(frame: pd.DataFrame, *, confirmed_through: datetime) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ContractValidationError("OHLCV input must be a non-empty DataFrame")
    missing = [column for column in _OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise ContractValidationError(f"OHLCV input missing columns: {missing}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ContractValidationError("OHLCV input must use a DatetimeIndex")
    if frame.index.tz is None:
        raise ContractValidationError("OHLCV index must be timezone-aware UTC")
    if any(timestamp.utcoffset() != timedelta(0) for timestamp in frame.index):
        raise ContractValidationError("OHLCV index must be UTC")
    if frame.index.hasnans:
        raise ContractValidationError("OHLCV index cannot contain NaT")

    # The boundary is selected before value and ordering validation. Future
    # rows are not known at this observation and must not affect the prefix.
    result = frame.loc[frame.index <= confirmed_through].copy(deep=True)
    if result.empty:
        raise ContractValidationError("confirmed OHLCV prefix is empty")
    if not result.index.is_monotonic_increasing:
        raise ContractValidationError("OHLCV index must be strictly increasing")
    if not result.index.is_unique:
        raise ContractValidationError("OHLCV index must not contain duplicates")
    result.index = result.index.tz_convert("UTC")
    for column in _OHLCV_COLUMNS:
        converted = pd.to_numeric(result[column], errors="coerce")
        if converted.isna().any():
            raise ContractValidationError(f"OHLCV column {column} contains non-numeric values")
        values = converted.to_numpy(dtype=np.float64, copy=True)
        if not np.isfinite(values).all():
            raise ContractValidationError(f"OHLCV column {column} contains non-finite values")
        result[column] = values

    high = result["high"].to_numpy(dtype=np.float64)
    low = result["low"].to_numpy(dtype=np.float64)
    open_values = result["open"].to_numpy(dtype=np.float64)
    close = result["close"].to_numpy(dtype=np.float64)
    volume = result["volume"].to_numpy(dtype=np.float64)
    if (high < low).any() or (high < open_values).any() or (high < close).any():
        raise ContractValidationError("OHLC input violates high bounds")
    if (low > open_values).any() or (low > close).any():
        raise ContractValidationError("OHLC input violates low bounds")
    if (volume < 0).any():
        raise ContractValidationError("OHLCV volume cannot be negative")
    return result.loc[:, _OHLCV_COLUMNS]


def _input_bytes(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    observed_at: datetime,
    confirmed_through: datetime,
) -> bytes:
    lines = [
        f"asset={asset}",
        f"timeframe={timeframe}",
        f"observed_at={observed_at.isoformat()}",
        f"confirmed_through={confirmed_through.isoformat()}",
        "columns=open,high,low,close,volume",
    ]
    for timestamp, row in frame.iterrows():
        values = ",".join(float(row[column]).hex() for column in _OHLCV_COLUMNS)
        lines.append(f"{timestamp.value}:{values}")
    return "\n".join(lines).encode("ascii")


@dataclass(frozen=True, slots=True)
class ConfirmedOHLCVFrame:
    """Owned normalized OHLCV prefix at an explicit confirmation boundary."""

    asset: str
    timeframe: str
    observed_at: datetime
    confirmed_through: datetime
    _frame: pd.DataFrame = field(repr=False, compare=False)
    _input_identity: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="frame.asset")
        timeframe = require_string(self.timeframe, field_name="frame.timeframe")
        observed_at = require_utc(self.observed_at, field_name="frame.observed_at")
        confirmed_through = require_utc(
            self.confirmed_through, field_name="frame.confirmed_through"
        )
        if confirmed_through > observed_at:
            raise ContractValidationError(
                "frame.confirmed_through cannot be after observed_at"
            )
        normalized = _normalized_frame(
            self._frame, confirmed_through=confirmed_through
        )
        identity = hashlib.sha256(
            _input_bytes(
                normalized,
                asset=asset,
                timeframe=timeframe,
                observed_at=observed_at,
                confirmed_through=confirmed_through,
            )
        ).hexdigest()
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "confirmed_through", confirmed_through)
        object.__setattr__(self, "_frame", normalized)
        object.__setattr__(self, "_input_identity", require_hash(identity, field_name="input_identity"))

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        confirmed_through: datetime,
    ) -> "ConfirmedOHLCVFrame":
        return cls(
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            confirmed_through=confirmed_through,
            _frame=frame,
        )

    @property
    def input_identity(self) -> str:
        return self._input_identity

    @property
    def row_count(self) -> int:
        return len(self._frame)

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def arrays(self) -> ConfirmedOHLCVArrays:
        return ConfirmedOHLCVArrays(
            timestamps=self._frame.index.view("int64").astype(np.int64, copy=True),
            open=self._frame["open"].to_numpy(dtype=np.float64, copy=True),
            high=self._frame["high"].to_numpy(dtype=np.float64, copy=True),
            low=self._frame["low"].to_numpy(dtype=np.float64, copy=True),
            close=self._frame["close"].to_numpy(dtype=np.float64, copy=True),
            volume=self._frame["volume"].to_numpy(dtype=np.float64, copy=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "confirmed_through": self.confirmed_through.isoformat().replace("+00:00", "Z"),
            "input_identity": self.input_identity,
            "row_count": self.row_count,
        }


__all__ = ["ConfirmedOHLCVArrays", "ConfirmedOHLCVFrame"]
