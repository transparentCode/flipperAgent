"""Causal fractal pivots owned by the trendline-family candidate model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Literal, Mapping, Protocol

import pandas as pd

from ...domain.geometry import AnchorRef
from ...domain.identity import deterministic_id
from ...domain.validation import ContractValidationError, require_utc


PIVOT_PROVIDER_NAME = "fractal"
PivotKind = Literal["high", "low"]


class PivotExtractionStatus(str, Enum):
    """Terminal result of a causal pivot extraction request."""

    VALID = "valid"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_CONFIRMED_PIVOTS = "no_confirmed_pivots"


def freeze_result_metadata(value: Mapping[str, Any] | None, *, field_name: str) -> Mapping[str, Any]:
    """Recursively freeze Phase-B result metadata before publishing it."""

    if value is None:
        return MappingProxyType({})
    frozen = _freeze_result_value(value, field_name=field_name)
    if not isinstance(frozen, Mapping):  # Defensive guard for future helper changes.
        raise ContractValidationError(f"{field_name} must be a mapping")
    return frozen


def _freeze_result_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{field_name} float must be finite")
        return value
    if isinstance(value, datetime):
        return require_utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractValidationError(f"{field_name} keys must be strings")
        return MappingProxyType(
            {
                key: _freeze_result_value(item, field_name=f"{field_name}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_result_value(item, field_name=f"{field_name} item") for item in value
        )
    raise ContractValidationError(f"unsupported {field_name} value type: {type(value)!r}")


@dataclass(frozen=True)
class ConfirmedPivot:
    """An extrema that only exists after its right-side confirmation bars close."""

    pivot_id: str
    index: int
    timestamp: datetime
    confirmation_index: int
    confirmation_time: datetime
    price: float
    kind: PivotKind

    def __post_init__(self) -> None:
        if not isinstance(self.pivot_id, str) or not self.pivot_id:
            raise ContractValidationError("pivot_id must be a non-empty string")
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ContractValidationError("pivot index must be a non-negative integer")
        if (
            isinstance(self.confirmation_index, bool)
            or not isinstance(self.confirmation_index, int)
            or self.confirmation_index < self.index
        ):
            raise ContractValidationError("pivot confirmation_index must be >= index")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="pivot timestamp"))
        object.__setattr__(
            self,
            "confirmation_time",
            require_utc(self.confirmation_time, field_name="pivot confirmation_time"),
        )
        if self.confirmation_time < self.timestamp:
            raise ContractValidationError("pivot confirmation_time cannot precede timestamp")
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float)):
            raise ContractValidationError("pivot price must be numeric")
        if not math.isfinite(float(self.price)):
            raise ContractValidationError("pivot price must be finite")
        object.__setattr__(self, "price", float(self.price))
        if self.kind not in {"high", "low"}:
            raise ContractValidationError("pivot kind must be high or low")

    def to_anchor(self) -> AnchorRef:
        return AnchorRef(
            anchor_id=self.pivot_id,
            timestamp=self.timestamp,
            price=self.price,
            pivot_kind=self.kind,
            confirmation_time=self.confirmation_time,
        )


@dataclass(frozen=True)
class PivotExtractionResult:
    """Immutable, status-safe output from one pivot provider invocation."""

    status: PivotExtractionStatus | str
    pivots: tuple[ConfirmedPivot, ...]
    input_bars: int
    confirmed_bars: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            status = PivotExtractionStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid pivot extraction status: {self.status!r}") from exc
        object.__setattr__(self, "status", status)
        if isinstance(self.input_bars, bool) or not isinstance(self.input_bars, int):
            raise ContractValidationError("input_bars must be a non-negative integer")
        if isinstance(self.confirmed_bars, bool) or not isinstance(self.confirmed_bars, int):
            raise ContractValidationError("confirmed_bars must be a non-negative integer")
        if self.input_bars < 0 or self.confirmed_bars < 0:
            raise ContractValidationError("pivot bar counts must be non-negative")
        if self.confirmed_bars > self.input_bars:
            raise ContractValidationError("confirmed_bars cannot exceed input_bars")

        pivots = tuple(self.pivots)
        if any(not isinstance(pivot, ConfirmedPivot) for pivot in pivots):
            raise ContractValidationError("pivots must contain only ConfirmedPivot values")
        if len({pivot.pivot_id for pivot in pivots}) != len(pivots):
            raise ContractValidationError("pivot IDs must be unique")
        expected_order = tuple(sorted(pivots, key=lambda pivot: (pivot.index, pivot.kind, pivot.pivot_id)))
        if pivots != expected_order:
            raise ContractValidationError("pivots must be ordered by index, kind, and ID")
        if any(
            pivot.index >= self.confirmed_bars or pivot.confirmation_index >= self.confirmed_bars
            for pivot in pivots
        ):
            raise ContractValidationError("pivot indices must be inside confirmed bars")
        if status is PivotExtractionStatus.VALID and not pivots:
            raise ContractValidationError("valid pivot extraction requires pivots")
        if status is not PivotExtractionStatus.VALID and pivots:
            raise ContractValidationError("empty pivot extraction status cannot contain pivots")
        object.__setattr__(self, "pivots", pivots)
        object.__setattr__(
            self,
            "metadata",
            freeze_result_metadata(self.metadata, field_name="pivot extraction metadata"),
        )

    @property
    def high_pivots(self) -> tuple[ConfirmedPivot, ...]:
        return tuple(pivot for pivot in self.pivots if pivot.kind == "high")

    @property
    def low_pivots(self) -> tuple[ConfirmedPivot, ...]:
        return tuple(pivot for pivot in self.pivots if pivot.kind == "low")


class PivotProvider(Protocol):
    """Small candidate-stage pivot provider boundary."""

    def extract(self, ohlcv: pd.DataFrame, *, observed_at: datetime) -> PivotExtractionResult:
        """Return pivots confirmed no later than ``observed_at``."""


def confirmed_ohlcv_window(
    ohlcv: pd.DataFrame,
    *,
    observed_at: datetime,
    required_columns: frozenset[str] = frozenset({"high", "low"}),
) -> pd.DataFrame:
    """Validate OHLCV and retain only bars available at the observed instant."""

    if not isinstance(ohlcv, pd.DataFrame):
        raise ContractValidationError("ohlcv must be a pandas DataFrame")
    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        raise ContractValidationError("ohlcv must use a DatetimeIndex")
    if ohlcv.index.tz is None:
        raise ContractValidationError("ohlcv DatetimeIndex must be timezone-aware UTC")
    if len(ohlcv) and ohlcv.index[0].utcoffset() != timedelta(0):
        raise ContractValidationError("ohlcv DatetimeIndex must be timezone-aware UTC")
    if not ohlcv.index.is_monotonic_increasing or not ohlcv.index.is_unique:
        raise ContractValidationError("ohlcv DatetimeIndex must be unique and sorted")
    missing_columns = required_columns.difference(ohlcv.columns)
    if missing_columns:
        raise ContractValidationError(
            f"ohlcv missing required columns: {', '.join(sorted(missing_columns))}"
        )

    observed = pd.Timestamp(require_utc(observed_at, field_name="observed_at"))
    window = ohlcv.loc[ohlcv.index <= observed].copy()
    for column in required_columns:
        try:
            values = pd.to_numeric(window[column], errors="raise").astype(float)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"ohlcv column {column} must be numeric") from exc
        if not pd.api.types.is_numeric_dtype(values):
            raise ContractValidationError(f"ohlcv column {column} must be numeric")
        if values.isna().any() or not values.map(math.isfinite).all():
            raise ContractValidationError(f"ohlcv column {column} must contain finite values")
        window[column] = values

    ohlc_columns = {"open", "high", "low", "close"}
    if ohlc_columns.issubset(required_columns) and not window.empty:
        high = window["high"].astype(float)
        low = window["low"].astype(float)
        open_ = window["open"].astype(float)
        close = window["close"].astype(float)
        if (high < low).any():
            raise ContractValidationError("ohlcv contains a bar where high is below low")
        if (high < open_).any() or (high < close).any():
            raise ContractValidationError("ohlcv contains a bar where high is below open or close")
        if (low > open_).any() or (low > close).any():
            raise ContractValidationError("ohlcv contains a bar where low is above open or close")
    return window


class CausalFractalPivotExtractor:
    """Extract extrema only after the configured right-side bars have closed."""

    def __init__(self, *, left_bars: int, right_bars: int) -> None:
        if isinstance(left_bars, bool) or not isinstance(left_bars, int) or left_bars < 1:
            raise ContractValidationError("left_bars must be an integer >= 1")
        if isinstance(right_bars, bool) or not isinstance(right_bars, int) or right_bars < 1:
            raise ContractValidationError("right_bars must be an integer >= 1")
        self.left_bars = left_bars
        self.right_bars = right_bars

    def extract(self, ohlcv: pd.DataFrame, *, observed_at: datetime) -> PivotExtractionResult:
        frame = confirmed_ohlcv_window(ohlcv, observed_at=observed_at)
        required_bars = self.left_bars + self.right_bars + 1
        metadata = {
            "left_bars": self.left_bars,
            "right_bars": self.right_bars,
            "plateau_policy": "leftmost_strict_left_nonstrict_right_v1",
        }
        if len(frame) < required_bars:
            return PivotExtractionResult(
                status=PivotExtractionStatus.INSUFFICIENT_DATA,
                pivots=(),
                input_bars=len(ohlcv),
                confirmed_bars=len(frame),
                metadata=metadata,
            )

        high_pivots = self._extract_kind(frame, kind="high")
        low_pivots = self._extract_kind(frame, kind="low")
        pivots = tuple(
            sorted(
                (*high_pivots, *low_pivots),
                key=lambda pivot: (pivot.index, pivot.kind, pivot.pivot_id),
            )
        )
        return PivotExtractionResult(
            status=(PivotExtractionStatus.VALID if pivots else PivotExtractionStatus.NO_CONFIRMED_PIVOTS),
            pivots=pivots,
            input_bars=len(ohlcv),
            confirmed_bars=len(frame),
            metadata=metadata,
        )

    def _extract_kind(self, frame: pd.DataFrame, *, kind: PivotKind) -> tuple[ConfirmedPivot, ...]:
        column = "high" if kind == "high" else "low"
        values = frame[column].astype(float).to_list()
        candidates: list[tuple[int, float]] = []
        for index in range(self.left_bars, len(frame) - self.right_bars):
            value = values[index]
            left_values = values[index - self.left_bars : index]
            right_values = values[index + 1 : index + self.right_bars + 1]
            # The first equal plateau bar is the only eligible representative.
            # It is strict on prior bars and non-strict on confirmed right bars,
            # so an already-published pivot cannot move as a plateau extends.
            is_extremum = (
                value > max(left_values) and value >= max(right_values)
                if kind == "high"
                else value < min(left_values) and value <= min(right_values)
            )
            if is_extremum:
                candidates.append((index, value))

        pivots: list[ConfirmedPivot] = []
        for index, price in candidates:
            timestamp = frame.index[index].to_pydatetime()
            confirmation_index = index + self.right_bars
            confirmation_time = frame.index[confirmation_index].to_pydatetime()
            pivots.append(
                ConfirmedPivot(
                    pivot_id=deterministic_id(
                        "pivot",
                        {
                            "kind": kind,
                            "timestamp": timestamp.isoformat(),
                            "confirmation_time": confirmation_time.isoformat(),
                            "price": price,
                            "left_bars": self.left_bars,
                            "right_bars": self.right_bars,
                        },
                    ),
                    index=index,
                    timestamp=timestamp,
                    confirmation_index=confirmation_index,
                    confirmation_time=confirmation_time,
                    price=price,
                    kind=kind,
                )
            )
        return tuple(pivots)
