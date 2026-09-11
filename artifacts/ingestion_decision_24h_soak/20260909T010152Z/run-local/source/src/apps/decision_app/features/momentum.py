"""Pure causal RSI and MACD calculations for M3 evidence.

These functions deliberately do not read configuration or retain indicator
state.  They use the same seeded Wilder/EMA recurrences as the reviewed legacy
batch implementations, but keep the future Decision feature boundary free of
legacy indicator registries and mutable indicator objects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from numbers import Real


@dataclass(frozen=True, slots=True)
class MACDValue:
    """The final causal MACD tuple for one supplied close history."""

    line: float
    signal: float
    histogram: float


def _finite_closes(closes: Sequence[object]) -> tuple[float, ...]:
    if isinstance(closes, (str, bytes)):
        raise TypeError("closes must be a sequence of numeric values")
    try:
        values = tuple(closes)
    except TypeError as exc:
        raise TypeError("closes must be a sequence of numeric values") from exc

    normalized: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            raise TypeError(f"close[{index}] must be a finite numeric value")
        number = float(value)
        if not isfinite(number):
            raise ValueError(f"close[{index}] must be finite")
        normalized.append(number)
    return tuple(normalized)


def _positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive int")
    return value


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def calculate_rsi(closes: Sequence[object], *, period: int) -> float:
    """Calculate the final Wilder RSI using only the supplied closed bars."""

    period = _positive_int(period, field_name="period")
    values = _finite_closes(closes)
    required = period + 1
    if len(values) < required:
        raise ValueError(f"RSI requires at least {required} closes")

    gain_total = 0.0
    loss_total = 0.0
    for index in range(1, required):
        change = values[index] - values[index - 1]
        if change > 0.0:
            gain_total += change
        else:
            loss_total += abs(change)

    average_gain = gain_total / period
    average_loss = loss_total / period
    for index in range(required, len(values)):
        change = values[index] - values[index - 1]
        gain = max(0.0, change)
        loss = abs(change) if change < 0.0 else 0.0
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period

    return _rsi_from_averages(average_gain, average_loss)


def calculate_macd(
    closes: Sequence[object],
    *,
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> MACDValue:
    """Calculate the final seeded EMA MACD tuple for closed causal bars."""

    fast_period = _positive_int(fast_period, field_name="fast_period")
    slow_period = _positive_int(slow_period, field_name="slow_period")
    signal_period = _positive_int(signal_period, field_name="signal_period")
    if fast_period > slow_period:
        raise ValueError("fast_period must not exceed slow_period")

    values = _finite_closes(closes)
    required = slow_period + signal_period - 1
    if len(values) < required:
        raise ValueError(f"MACD requires at least {required} closes")

    fast_alpha = 2.0 / (fast_period + 1)
    slow_alpha = 2.0 / (slow_period + 1)
    signal_alpha = 2.0 / (signal_period + 1)

    fast_ema = sum(values[:fast_period]) / fast_period
    slow_ema = sum(values[:slow_period]) / slow_period
    for value in values[fast_period:slow_period]:
        fast_ema = (value - fast_ema) * fast_alpha + fast_ema

    macd_values: list[float | None] = [None] * len(values)
    macd_values[slow_period - 1] = fast_ema - slow_ema
    for index in range(slow_period, len(values)):
        value = values[index]
        fast_ema = (value - fast_ema) * fast_alpha + fast_ema
        slow_ema = (value - slow_ema) * slow_alpha + slow_ema
        macd_values[index] = fast_ema - slow_ema

    signal_start = slow_period - 1 + signal_period
    signal = (
        sum(
            value
            for value in macd_values[slow_period - 1 : signal_start]
            if value is not None
        )
        / signal_period
    )
    signal_values: list[float | None] = [None] * len(values)
    signal_values[signal_start - 1] = signal
    histogram = macd_values[signal_start - 1] - signal
    for index in range(signal_start, len(values)):
        macd_value = macd_values[index]
        if macd_value is None:  # pragma: no cover - guarded by the recurrence
            raise RuntimeError("MACD recurrence produced an incomplete value")
        signal = (macd_value - signal) * signal_alpha + signal
        signal_values[index] = signal
        histogram = macd_value - signal

    line = macd_values[-1]
    final_signal = signal_values[-1]
    if line is None or final_signal is None:  # pragma: no cover - length guarded
        raise RuntimeError("MACD recurrence did not produce a final value")
    return MACDValue(line=line, signal=final_signal, histogram=histogram)


__all__ = ["MACDValue", "calculate_macd", "calculate_rsi"]
