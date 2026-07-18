"""Strict provider-result validation and causal ATR/ClosedBar mapping."""

from __future__ import annotations

from datetime import datetime
from numbers import Integral, Real
from typing import Any, Protocol

import pandas as pd

from libs.features.indicators.volatility.atr import ATR
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey
from libs.models.sr.research.source.contracts import SourceBar

from .contracts import (
    ATR_IMPLEMENTATION,
    ATR_IMPLEMENTATION_CONTRACT,
    ATRProvenance,
    ResolvedInputConfig,
    TrialSpec,
    ValidatedDataset,
    effective_provider_request_bounds,
    epoch_milliseconds,
)


DAY_MS = 86_400_000
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class HistoricalOHLCVAdapter(Protocol):
    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Fetch one bounded historical OHLCV response."""


def _as_float(value: Any, *, field_name: str, row_number: int) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ContractValidationError(
            f"row {row_number} {field_name} must be numeric without coercion"
        )
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ContractValidationError(
            f"row {row_number} {field_name} must be numeric without coercion"
        ) from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise ContractValidationError(f"row {row_number} {field_name} must be finite")
    return 0.0 if result == 0.0 else result


def _timestamp_ms(value: Any, *, row_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ContractValidationError(
            f"row {row_number} timestamp must be an exact integer milliseconds value"
        )
    return int(value)


def _timestamp_to_ms(timestamp: datetime) -> int:
    return epoch_milliseconds(timestamp)


def validate_raw_dataset(frame: Any, trial: TrialSpec) -> ValidatedDataset:
    """Validate one adapter response without sorting, repair, or coercion."""
    if type(trial) is not TrialSpec:
        raise ContractValidationError("trial must be exactly TrialSpec")
    if type(frame) is not pd.DataFrame:
        raise ContractValidationError("adapter result must be exactly pandas.DataFrame")
    if frame.empty:
        raise ContractValidationError("adapter result must not be empty")
    if len(set(frame.columns)) != len(frame.columns):
        raise ContractValidationError("adapter result columns must be unique")
    missing = set(_REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ContractValidationError(
            f"adapter result missing required columns: {sorted(missing)}"
        )
    if len(frame) >= trial.adapter_limit:
        raise ContractValidationError(
            "adapter result length must be below configured adapter_limit"
        )

    requested_since_ms = _timestamp_to_ms(trial.requested_since)
    requested_until_ms = _timestamp_to_ms(trial.requested_until)
    bars: list[SourceBar] = []
    previous_timestamp_ms: int | None = None
    rows = frame.loc[:, _REQUIRED_COLUMNS].itertuples(index=False, name=None)
    for row_number, row in enumerate(rows):
        timestamp_ms = _timestamp_ms(row[0], row_number=row_number)
        if timestamp_ms < requested_since_ms:
            raise ContractValidationError(
                f"row {row_number} timestamp precedes requested_since"
            )
        if timestamp_ms >= requested_until_ms:
            raise ContractValidationError(
                f"row {row_number} open_time must be strictly before requested_until"
            )
        closed_at_ms = timestamp_ms + DAY_MS
        if closed_at_ms > requested_until_ms:
            raise ContractValidationError(
                f"row {row_number} closed_at exceeds requested_until"
            )
        if previous_timestamp_ms is not None:
            if timestamp_ms <= previous_timestamp_ms:
                raise ContractValidationError(
                    "adapter timestamps must be strictly increasing and unique"
                )
            if timestamp_ms - previous_timestamp_ms != DAY_MS:
                raise ContractValidationError("adapter timestamps contain a gap")
        previous_timestamp_ms = timestamp_ms

        open_price = _as_float(row[1], field_name="open", row_number=row_number)
        high = _as_float(row[2], field_name="high", row_number=row_number)
        low = _as_float(row[3], field_name="low", row_number=row_number)
        close = _as_float(row[4], field_name="close", row_number=row_number)
        volume = _as_float(row[5], field_name="volume", row_number=row_number)
        try:
            open_time = pd.Timestamp(timestamp_ms, unit="ms", tz="UTC").to_pydatetime()
            closed_at = pd.Timestamp(closed_at_ms, unit="ms", tz="UTC").to_pydatetime()
        except (OverflowError, ValueError) as exc:
            raise ContractValidationError(
                f"row {row_number} timestamp is outside supported datetime range"
            ) from exc
        bar_id = f"{trial.venue}:{trial.symbol}:{trial.timeframe}:{timestamp_ms}"
        bars.append(
            SourceBar(
                open_time=open_time,
                closed_at=closed_at,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                bar_id=bar_id,
            )
        )

    return ValidatedDataset(
        bars=tuple(bars),
        requested_since=trial.requested_since,
        requested_until=trial.requested_until,
        actual_since=bars[0].open_time,
        actual_until=bars[-1].closed_at,
        raw_row_count=len(bars),
        adapter_limit=trial.adapter_limit,
        gap_policy=trial.gap_policy,
    )


async def fetch_validated_dataset(
    adapter: HistoricalOHLCVAdapter,
    trial: TrialSpec,
) -> ValidatedDataset:
    """Call provider exactly once, then validate response in caller order."""
    if type(trial) is not TrialSpec:
        raise ContractValidationError("trial must be exactly TrialSpec")
    provider_since_ms, provider_until_ms = effective_provider_request_bounds(
        trial.requested_since,
        trial.requested_until,
    )
    frame = await adapter.get_historical_ohlcv(
        trial.symbol,
        trial.timeframe,
        since=provider_since_ms,
        until=provider_until_ms,
        limit=trial.adapter_limit,
    )
    return validate_raw_dataset(frame, trial)


def build_model_bars(
    dataset: ValidatedDataset,
    resolved_input: ResolvedInputConfig,
    trial: TrialSpec,
) -> tuple[tuple[ClosedBar, ...], ATRProvenance]:
    """Compute existing causal ATR and map only finite post-warmup bars."""
    if resolved_input.asset != trial.symbol or resolved_input.timeframe != trial.timeframe:
        raise ContractValidationError("input configuration does not match trial")
    atr = ATR(period=resolved_input.atr_period)
    atr_values = atr.batch(
        tuple((bar.high, bar.low, bar.close) for bar in dataset.bars)
    )
    if len(atr_values) != len(dataset.bars):
        raise ContractValidationError("ATR output length does not match source bars")
    warmup_count = resolved_input.atr_period
    if len(atr_values) <= warmup_count:
        raise ContractValidationError("dataset does not contain a valid ATR value")
    if any(value is not None for value in atr_values[:warmup_count]):
        raise ContractValidationError("ATR warmup boundary is not causal")
    first_valid_index = next(
        (index for index, value in enumerate(atr_values) if value is not None),
        None,
    )
    if first_valid_index != warmup_count:
        raise ContractValidationError("ATR first valid index does not match period")
    for index, value in enumerate(atr_values[first_valid_index:], start=first_valid_index):
        if value is None:
            raise ContractValidationError(f"ATR missing after warmup at row {index}")
        try:
            numeric = float(value)
        except (OverflowError, ValueError) as exc:
            raise ContractValidationError(f"ATR invalid at row {index}") from exc
        if numeric != numeric or numeric in {float("inf"), float("-inf")} or numeric <= 0:
            raise ContractValidationError(f"ATR must be finite and positive at row {index}")

    state_key = SRStateKey("binance_usdm", trial.symbol, trial.timeframe)
    model_bars = tuple(
        ClosedBar(
            state_key=state_key,
            bar_id=bar.bar_id,
            closed_at=bar.closed_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            atr_at_close=float(atr_values[index]),
        )
        for index, bar in enumerate(dataset.bars[first_valid_index:], start=first_valid_index)
    )
    provenance = ATRProvenance(
        method=resolved_input.atr_method,
        period=resolved_input.atr_period,
        seed=resolved_input.atr_seed,
        implementation=ATR_IMPLEMENTATION,
        implementation_contract=ATR_IMPLEMENTATION_CONTRACT,
        warmup_count=first_valid_index,
        first_valid_at=dataset.bars[first_valid_index].closed_at,
        raw_bar_count=len(dataset.bars),
        model_bar_count=len(model_bars),
    )
    return model_bars, provenance


__all__ = [
    "DAY_MS",
    "HistoricalOHLCVAdapter",
    "build_model_bars",
    "fetch_validated_dataset",
    "validate_raw_dataset",
]
