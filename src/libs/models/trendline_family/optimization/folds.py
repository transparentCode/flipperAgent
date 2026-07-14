"""Strict immutable historical-frame and chronological fold planning utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Iterable, Mapping

import pandas as pd

from ..contracts import ContractValidationError
from .contracts import OPTIMIZATION_SCHEMA_VERSION, primitive, semantic_id


_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def _timestamp(value: Any, *, field_name: str) -> datetime:
    converted = pd.Timestamp(value)
    if converted.tzinfo is None or converted.utcoffset() is None or converted.utcoffset().total_seconds() != 0:
        raise ContractValidationError(f"{field_name} must be timezone-aware UTC")
    return converted.to_pydatetime()


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ContractValidationError("historical frame must be a non-empty DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ContractValidationError("historical frame index must be a timezone-aware UTC DatetimeIndex")
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None or str(index.tz) not in {"UTC", "UTC+00:00"}:
        raise ContractValidationError("historical frame index must be timezone-aware UTC")
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ContractValidationError("historical frame timestamps must be strictly ordered and unique")
    missing = set(_OHLCV_COLUMNS).difference(frame.columns)
    if missing:
        raise ContractValidationError(f"historical frame missing required columns: {sorted(missing)}")
    result = frame.copy(deep=True)
    for column in _OHLCV_COLUMNS:
        converted = pd.to_numeric(result[column], errors="coerce")
        if converted.isna().any() or not converted.map(math.isfinite).all():
            raise ContractValidationError(f"historical frame {column} must be finite numeric")
        result[column] = converted.astype(float)
    if (result[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ContractValidationError("historical frame prices must be positive")
    if (result["volume"] < 0.0).any():
        raise ContractValidationError("historical frame volume cannot be negative")
    if (result["high"] < result[["open", "close", "low"]].max(axis=1)).any() or (
        result["low"] > result[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ContractValidationError("historical frame OHLC relationships are invalid")
    for marker in ("complete", "is_complete", "confirmed"):
        if marker in result.columns and not result[marker].fillna(False).astype(bool).all():
            raise ContractValidationError("historical frame contains incomplete bars")
    return result


def hash_historical_frame(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    preprocessing_version: str = "confirmed_ohlcv_v1",
) -> str:
    """Hash normalized values, labels and ordered UTC timestamps deterministically."""

    normalized = _validate_frame(frame)
    if not isinstance(asset, str) or not asset or not isinstance(timeframe, str) or not timeframe:
        raise ContractValidationError("dataset asset and timeframe must be non-empty strings")
    payload = {
        "schema_version": OPTIMIZATION_SCHEMA_VERSION,
        "asset": asset,
        "timeframe": timeframe,
        "preprocessing_version": preprocessing_version,
        "columns": tuple(str(column) for column in normalized.columns),
        "rows": [
            {
                "timestamp": _timestamp(timestamp, field_name="historical timestamp"),
                **{
                    str(column): _normalized_cell(value)
                    for column, value in row.items()
                },
            }
            for timestamp, row in normalized.iterrows()
        ],
    }
    return semantic_id("trendline-family-dataset", payload)


def _normalized_cell(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ContractValidationError("dataset values must be finite")
        return numeric
    if isinstance(value, pd.Timestamp):
        return _timestamp(value, field_name="dataset timestamp")
    return str(value)


@dataclass(frozen=True)
class ImmutableHistoricalFrame:
    """Copies incoming historical data and exposes copies only to evaluators."""

    asset: str
    timeframe: str
    _frame: pd.DataFrame
    preprocessing_version: str = "confirmed_ohlcv_v1"
    dataset_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.asset, str) or not self.asset or not isinstance(self.timeframe, str) or not self.timeframe:
            raise ContractValidationError("historical frame asset and timeframe must be non-empty strings")
        normalized = _validate_frame(self._frame)
        object.__setattr__(self, "_frame", normalized)
        if not isinstance(self.preprocessing_version, str) or not self.preprocessing_version:
            raise ContractValidationError("preprocessing_version must be non-empty")
        expected = hash_historical_frame(
            normalized,
            asset=self.asset,
            timeframe=self.timeframe,
            preprocessing_version=self.preprocessing_version,
        )
        if self.dataset_hash is not None and self.dataset_hash != expected:
            raise ContractValidationError("dataset_hash does not match normalized historical frame")
        object.__setattr__(self, "dataset_hash", expected)

    @property
    def row_count(self) -> int:
        return len(self._frame)

    @property
    def timestamps(self) -> tuple[datetime, ...]:
        return tuple(_timestamp(value, field_name="historical timestamp") for value in self._frame.index)

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    def prefix(self, end_position: int) -> pd.DataFrame:
        if isinstance(end_position, bool) or not isinstance(end_position, int) or not 0 <= end_position < self.row_count:
            raise ContractValidationError("prefix end_position is out of range")
        return self._frame.iloc[: end_position + 1].copy(deep=True)

    def slice_positions(self, start_position: int, end_position: int) -> pd.DataFrame:
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (start_position, end_position)):
            raise ContractValidationError("slice positions must be integers")
        if not 0 <= start_position <= end_position < self.row_count:
            raise ContractValidationError("slice positions are out of range")
        return self._frame.iloc[start_position : end_position + 1].copy(deep=True)


@dataclass(frozen=True)
class EvaluationWindow:
    start_position: int
    end_position: int
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for name in ("start_position", "end_position"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if self.start_position > self.end_position:
            raise ContractValidationError("window start_position cannot exceed end_position")
        object.__setattr__(self, "start", _timestamp(self.start, field_name="window start"))
        object.__setattr__(self, "end", _timestamp(self.end, field_name="window end"))
        if self.start > self.end:
            raise ContractValidationError("window start cannot exceed end")

    @property
    def bar_count(self) -> int:
        return self.end_position - self.start_position + 1

    def to_dict(self) -> dict[str, Any]:
        return primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationWindow":
        if not isinstance(value, Mapping):
            raise ContractValidationError("EvaluationWindow payload must be a mapping")
        return cls(
            start_position=value.get("start_position"),
            end_position=value.get("end_position"),
            start=value.get("start"),
            end=value.get("end"),
        )


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    asset: str
    timeframe: str
    train: EvaluationWindow
    warmup: EvaluationWindow
    validation: EvaluationWindow
    purge_bars: int
    embargo_bars: int
    data_hash: str
    fold_plan_version: str = "walk_forward_v1"
    fold_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.fold_index, bool) or not isinstance(self.fold_index, int) or self.fold_index < 0:
            raise ContractValidationError("fold_index must be non-negative")
        for name in ("asset", "timeframe", "data_hash", "fold_plan_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ContractValidationError(f"{name} must be non-empty")
        if not all(isinstance(value, EvaluationWindow) for value in (self.train, self.warmup, self.validation)):
            raise ContractValidationError("fold windows must be EvaluationWindow values")
        if self.train.end_position >= self.validation.start_position:
            raise ContractValidationError("validation must occur after training")
        if self.warmup.end_position > self.train.end_position or self.warmup.start_position < self.train.start_position:
            raise ContractValidationError("warmup must be contained within training")
        for name in ("purge_bars", "embargo_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be non-negative")
        if self.validation.start_position - self.train.end_position - 1 < self.purge_bars:
            raise ContractValidationError("fold validation does not satisfy purge")
        expected = semantic_id("trendline-family-walk-forward-fold", self.identity_payload())
        if self.fold_id is not None and self.fold_id != expected:
            raise ContractValidationError("fold_id does not match fold content")
        object.__setattr__(self, "fold_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "train": self.train.to_dict(),
            "warmup": self.warmup.to_dict(),
            "validation": self.validation.to_dict(),
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
            "data_hash": self.data_hash,
            "fold_plan_version": self.fold_plan_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "fold_id": self.fold_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WalkForwardFold":
        if not isinstance(value, Mapping):
            raise ContractValidationError("WalkForwardFold payload must be a mapping")
        return cls(
            fold_index=value.get("fold_index"),
            asset=value.get("asset"),
            timeframe=value.get("timeframe"),
            train=EvaluationWindow.from_dict(value.get("train")),
            warmup=EvaluationWindow.from_dict(value.get("warmup")),
            validation=EvaluationWindow.from_dict(value.get("validation")),
            purge_bars=value.get("purge_bars"),
            embargo_bars=value.get("embargo_bars"),
            data_hash=value.get("data_hash"),
            fold_plan_version=value.get("fold_plan_version", "walk_forward_v1"),
            fold_id=value.get("fold_id"),
        )


@dataclass(frozen=True)
class HoldoutPlan:
    asset: str
    timeframe: str
    window: EvaluationWindow
    warmup: EvaluationWindow
    data_hash: str
    selected_after_fold_plan_id: str
    label_horizon_bars: int
    holdout_plan_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("asset", "timeframe", "data_hash", "selected_after_fold_plan_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ContractValidationError(f"{name} must be non-empty")
        if not isinstance(self.window, EvaluationWindow) or not isinstance(self.warmup, EvaluationWindow):
            raise ContractValidationError("holdout window and warmup must be EvaluationWindow")
        if self.warmup.end_position >= self.window.start_position:
            raise ContractValidationError("holdout warmup must end before holdout window")
        if isinstance(self.label_horizon_bars, bool) or not isinstance(self.label_horizon_bars, int) or self.label_horizon_bars < 0:
            raise ContractValidationError("label_horizon_bars must be non-negative")
        expected = semantic_id("trendline-family-holdout-plan", self.identity_payload())
        if self.holdout_plan_id is not None and self.holdout_plan_id != expected:
            raise ContractValidationError("holdout_plan_id does not match semantic content")
        object.__setattr__(self, "holdout_plan_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "window": self.window.to_dict(),
            "warmup": self.warmup.to_dict(),
            "data_hash": self.data_hash,
            "selected_after_fold_plan_id": self.selected_after_fold_plan_id,
            "label_horizon_bars": self.label_horizon_bars,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "holdout_plan_id": self.holdout_plan_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HoldoutPlan":
        if not isinstance(value, Mapping):
            raise ContractValidationError("HoldoutPlan payload must be a mapping")
        return cls(
            asset=value.get("asset"),
            timeframe=value.get("timeframe"),
            window=EvaluationWindow.from_dict(value.get("window")),
            warmup=EvaluationWindow.from_dict(value.get("warmup")),
            data_hash=value.get("data_hash"),
            selected_after_fold_plan_id=value.get("selected_after_fold_plan_id"),
            label_horizon_bars=value.get("label_horizon_bars"),
            holdout_plan_id=value.get("holdout_plan_id"),
        )


@dataclass(frozen=True)
class FoldPlan:
    asset: str
    timeframe: str
    data_hash: str
    folds: tuple[WalkForwardFold, ...]
    holdout: HoldoutPlan
    train_mode: str
    label_horizon_bars: int
    fold_plan_version: str = "walk_forward_v1"
    fold_plan_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("asset", "timeframe", "data_hash", "fold_plan_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ContractValidationError(f"{name} must be non-empty")
        folds = tuple(self.folds)
        if not folds or any(not isinstance(fold, WalkForwardFold) for fold in folds):
            raise ContractValidationError("fold plan requires WalkForwardFold values")
        if tuple(sorted(folds, key=lambda fold: fold.fold_index)) != folds or len({fold.fold_index for fold in folds}) != len(folds):
            raise ContractValidationError("folds must have deterministic unique ordering")
        if any(fold.asset != self.asset or fold.timeframe != self.timeframe or fold.data_hash != self.data_hash for fold in folds):
            raise ContractValidationError("fold identity mismatch")
        for prior, current in zip(folds, folds[1:], strict=False):
            if prior.validation.end_position + prior.embargo_bars >= current.validation.start_position:
                raise ContractValidationError("validation windows overlap after embargo")
        if not isinstance(self.holdout, HoldoutPlan):
            raise ContractValidationError("fold plan requires HoldoutPlan")
        if self.holdout.asset != self.asset or self.holdout.timeframe != self.timeframe or self.holdout.data_hash != self.data_hash:
            raise ContractValidationError("holdout identity mismatch")
        if self.holdout.window.start_position <= folds[-1].validation.end_position + folds[-1].embargo_bars:
            raise ContractValidationError("holdout must be chronologically untouched after validation embargo")
        if self.train_mode not in {"expanding", "rolling"}:
            raise ContractValidationError("train_mode must be expanding or rolling")
        if isinstance(self.label_horizon_bars, bool) or not isinstance(self.label_horizon_bars, int) or self.label_horizon_bars < 0:
            raise ContractValidationError("label_horizon_bars must be non-negative")
        expected = semantic_id("trendline-family-fold-plan", self.identity_payload())
        if self.fold_plan_id is not None and self.fold_plan_id != expected:
            raise ContractValidationError("fold_plan_id does not match fold plan content")
        if self.holdout.selected_after_fold_plan_id not in {"pending", expected}:
            raise ContractValidationError("holdout must bind this fold plan or pending construction")
        if self.holdout.selected_after_fold_plan_id == "pending":
            bound_holdout = HoldoutPlan(
                asset=self.holdout.asset,
                timeframe=self.holdout.timeframe,
                window=self.holdout.window,
                warmup=self.holdout.warmup,
                data_hash=self.holdout.data_hash,
                selected_after_fold_plan_id=expected,
                label_horizon_bars=self.holdout.label_horizon_bars,
            )
            object.__setattr__(self, "holdout", bound_holdout)
        object.__setattr__(self, "folds", folds)
        object.__setattr__(self, "fold_plan_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "data_hash": self.data_hash,
            "folds": [fold.to_dict() for fold in self.folds],
            # The holdout carries this plan ID as audit evidence.  Exclude that
            # back-reference from the plan identity to avoid a circular hash.
            "holdout": {
                "asset": self.holdout.asset,
                "timeframe": self.holdout.timeframe,
                "window": self.holdout.window.to_dict(),
                "warmup": self.holdout.warmup.to_dict(),
                "data_hash": self.holdout.data_hash,
                "label_horizon_bars": self.holdout.label_horizon_bars,
            },
            "train_mode": self.train_mode,
            "label_horizon_bars": self.label_horizon_bars,
            "fold_plan_version": self.fold_plan_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "data_hash": self.data_hash,
            "folds": [fold.to_dict() for fold in self.folds],
            "holdout": self.holdout.to_dict(),
            "train_mode": self.train_mode,
            "label_horizon_bars": self.label_horizon_bars,
            "fold_plan_version": self.fold_plan_version,
            "fold_plan_id": self.fold_plan_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FoldPlan":
        if not isinstance(value, Mapping):
            raise ContractValidationError("FoldPlan payload must be a mapping")
        return cls(
            asset=value.get("asset"),
            timeframe=value.get("timeframe"),
            data_hash=value.get("data_hash"),
            folds=tuple(WalkForwardFold.from_dict(item) for item in value.get("folds", ())),
            holdout=HoldoutPlan.from_dict(value.get("holdout")),
            train_mode=value.get("train_mode"),
            label_horizon_bars=value.get("label_horizon_bars"),
            fold_plan_version=value.get("fold_plan_version", "walk_forward_v1"),
            fold_plan_id=value.get("fold_plan_id"),
        )


def build_walk_forward_fold_plan(
    dataset: ImmutableHistoricalFrame,
    *,
    initial_train_bars: int,
    validation_bars: int,
    fold_count: int,
    holdout_bars: int,
    warmup_bars: int,
    purge_bars: int = 0,
    embargo_bars: int = 0,
    label_horizon_bars: int = 0,
    train_mode: str = "expanding",
    rolling_train_bars: int | None = None,
) -> FoldPlan:
    """Build deterministic chronological folds with purge, embargo and untouched holdout."""

    if not isinstance(dataset, ImmutableHistoricalFrame):
        raise ContractValidationError("dataset must be ImmutableHistoricalFrame")
    numbers = {
        "initial_train_bars": initial_train_bars,
        "validation_bars": validation_bars,
        "fold_count": fold_count,
        "holdout_bars": holdout_bars,
        "warmup_bars": warmup_bars,
        "purge_bars": purge_bars,
        "embargo_bars": embargo_bars,
        "label_horizon_bars": label_horizon_bars,
    }
    for name, value in numbers.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractValidationError(f"{name} must be a non-negative integer")
    if min(initial_train_bars, validation_bars, fold_count, holdout_bars, warmup_bars) < 1:
        raise ContractValidationError("training, validation, fold, holdout, and warmup sizes must be positive")
    if purge_bars < label_horizon_bars:
        raise ContractValidationError("purge_bars must cover label_horizon_bars")
    if train_mode not in {"expanding", "rolling"}:
        raise ContractValidationError("train_mode must be expanding or rolling")
    if train_mode == "rolling":
        if isinstance(rolling_train_bars, bool) or not isinstance(rolling_train_bars, int) or rolling_train_bars < initial_train_bars:
            raise ContractValidationError("rolling_train_bars must cover initial training")
    required = initial_train_bars + fold_count * (purge_bars + validation_bars + embargo_bars) + holdout_bars
    if dataset.row_count < required:
        raise ContractValidationError("historical frame is undersized for requested folds and holdout")
    timestamps = dataset.timestamps
    cursor = initial_train_bars
    folds: list[WalkForwardFold] = []
    for fold_index in range(fold_count):
        train_end = cursor - 1
        train_start = 0 if train_mode == "expanding" else max(0, train_end - int(rolling_train_bars) + 1)
        validation_start = train_end + purge_bars + 1
        validation_end = validation_start + validation_bars - 1
        warmup_start = max(train_start, train_end - warmup_bars + 1)
        fold = WalkForwardFold(
            fold_index=fold_index,
            asset=dataset.asset,
            timeframe=dataset.timeframe,
            train=_window(timestamps, train_start, train_end),
            warmup=_window(timestamps, warmup_start, train_end),
            validation=_window(timestamps, validation_start, validation_end),
            purge_bars=purge_bars,
            embargo_bars=embargo_bars,
            data_hash=dataset.dataset_hash,
        )
        folds.append(fold)
        cursor = validation_end + embargo_bars + 1
    holdout_start = dataset.row_count - holdout_bars
    if holdout_start < cursor:
        raise ContractValidationError("holdout overlaps fold validation or embargo")
    provisional = HoldoutPlan(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        window=_window(timestamps, holdout_start, dataset.row_count - 1),
        warmup=_window(timestamps, max(0, holdout_start - warmup_bars), holdout_start - 1),
        data_hash=dataset.dataset_hash,
        selected_after_fold_plan_id="pending",
        label_horizon_bars=label_horizon_bars,
    )
    return FoldPlan(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        data_hash=dataset.dataset_hash,
        folds=tuple(folds),
        holdout=provisional,
        train_mode=train_mode,
        label_horizon_bars=label_horizon_bars,
    )


def _window(timestamps: Iterable[datetime], start: int, end: int) -> EvaluationWindow:
    values = tuple(timestamps)
    return EvaluationWindow(start_position=start, end_position=end, start=values[start], end=values[end])


__all__ = [
    "EvaluationWindow",
    "FoldPlan",
    "HoldoutPlan",
    "ImmutableHistoricalFrame",
    "WalkForwardFold",
    "build_walk_forward_fold_plan",
    "hash_historical_frame",
]
