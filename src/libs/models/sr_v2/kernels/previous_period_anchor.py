"""Previous-period high/low anchor kernel.

The evaluator owns its mathematics, parameter parser, history requirement and
the exact feature evidence it consumed.  The structural engine only invokes
the frozen catalog contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ..contracts import ZoneSide
from ..domain.bars import SRBar
from ..domain.candidates import Candidate
from ..features.price import true_range, wilder_atr

if TYPE_CHECKING:
    from .registry import KernelEvaluation

IDENTIFIER = "previous_period_anchor@1"
KERNEL_ID = "previous_period_anchor"
VERSION = "1"


def parse_parameters(raw: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{path} must be a mapping")
    required = {"enabled", "atr_period", "zone_half_width_atr"}
    if set(raw) != required:
        unknown = sorted(set(raw) - required)
        missing = sorted(required - set(raw))
        detail = f"unknown keys: {', '.join(unknown)}" if unknown else f"missing keys: {', '.join(missing)}"
        raise ValueError(f"{path} {detail}")
    if not isinstance(raw["enabled"], bool):
        raise TypeError(f"{path}.enabled must be bool")
    period = raw["atr_period"]
    if isinstance(period, bool) or not isinstance(period, int) or not 1 <= period <= 512:
        raise ValueError(f"{path}.atr_period must be an integer in [1, 512]")
    try:
        width = raw["zone_half_width_atr"] if isinstance(raw["zone_half_width_atr"], Decimal) else Decimal(str(raw["zone_half_width_atr"]))
    except Exception as exc:
        raise ValueError(f"{path}.zone_half_width_atr must be numeric") from exc
    if not width.is_finite() or width <= 0 or width > 20:
        raise ValueError(f"{path}.zone_half_width_atr must be in (0, 20]")
    return {"enabled": raw["enabled"], "atr_period": period, "zone_half_width_atr": width}


def history_required(parameters: Mapping[str, Any]) -> int:
    return int(parameters["atr_period"]) + 1


def evaluate(
    bars: Sequence[SRBar],
    *,
    market_identity: Mapping[str, str],
    parameters: Mapping[str, Any],
) -> KernelEvaluation:
    # Importing the small contract here avoids a registry cycle at module load.
    from .registry import KernelEvaluation

    values = tuple(bars)
    period = int(parameters["atr_period"])
    width_multiple = parameters["zone_half_width_atr"]
    if not isinstance(width_multiple, Decimal):
        width_multiple = Decimal(str(width_multiple))
    if len(values) < history_required(parameters):
        return KernelEvaluation(candidates=(), consumed_feature_rows=())
    current = values[-1]
    atr = wilder_atr(values, period)
    width = atr * width_multiple
    previous_close = values[-2].close if len(values) > 1 else None
    feature_row = {
        "cutoff": current.bar_close_at,
        "timeframe": current.timeframe,
        "kernel_id": KERNEL_ID,
        "kernel_version": VERSION,
        "bar_open_at": current.bar_open_at,
        "bar_close_at": current.bar_close_at,
        "bar_id": current.identity,
        "open": current.open,
        "high": current.high,
        "low": current.low,
        "close": current.close,
        "volume": current.volume,
        "previous_close": previous_close,
        "true_range": true_range(current, previous_close),
        "atr_period": period,
        "atr": atr,
        "zone_half_width_atr": width_multiple,
        "zone_half_width": width,
    }
    candidates = tuple(
        Candidate(
            candidate_key=f"{current.identity}:{suffix}",
            venue=market_identity["venue"],
            instrument_id=market_identity["instrument_id"],
            asset=market_identity["asset"],
            source_timeframe=current.timeframe,
            kernel_id=KERNEL_ID,
            kernel_version=VERSION,
            side=side,
            center=center,
            lower=center - width,
            upper=center + width,
            formed_at=current.bar_close_at,
            available_at=current.bar_close_at,
            source_evidence_id=current.identity,
            creation_atr=atr,
        )
        for side, center, suffix in (
            (ZoneSide.RESISTANCE, current.high, "high"),
            (ZoneSide.SUPPORT, current.low, "low"),
        )
    )
    return KernelEvaluation(candidates=candidates, consumed_feature_rows=(feature_row,))


__all__ = [
    "IDENTIFIER",
    "KERNEL_ID",
    "evaluate",
    "history_required",
    "parse_parameters",
]
