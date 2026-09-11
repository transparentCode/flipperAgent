"""Equal-extrema plateau plus sweep/reclaim kernel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from ..contracts import ZoneSide
from ..domain.bars import SRBar
from ..domain.candidates import Candidate
from ..features.price import true_range, wilder_atr

IDENTIFIER = "plateau_sweep_reclaim@1"
KERNEL_ID = "plateau_sweep_reclaim"
VERSION = "1"


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _best_cluster(
    values: Sequence[tuple[Decimal, str]],
    *,
    tolerance: Decimal,
    minimum: int,
    side: ZoneSide,
) -> tuple[Decimal, tuple[str, ...]] | None:
    candidates: list[tuple[int, Decimal, tuple[str, ...]]] = []
    for seed, _ in values:
        first = tuple(item for item in values if abs(item[0] - seed) <= tolerance)
        if not first:
            continue
        center = _median(tuple(item[0] for item in first))
        retained = tuple(item for item in first if abs(item[0] - center) <= tolerance)
        if len(retained) < minimum:
            continue
        candidates.append((len(retained), center, tuple(sorted(item[1] for item in retained))))
    if not candidates:
        return None
    greatest = max(item[0] for item in candidates)
    candidates = [item for item in candidates if item[0] == greatest]
    preferred_center = max(item[1] for item in candidates) if side is ZoneSide.RESISTANCE else min(item[1] for item in candidates)
    return min((item for item in candidates if item[1] == preferred_center), key=lambda item: item[2])[1:]


def parse_parameters(raw: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{path} must be a mapping")
    required = {
        "enabled", "atr_period", "lookback_bars", "minimum_plateau_touches",
        "equality_tolerance_atr", "minimum_sweep_atr", "zone_half_width_atr",
    }
    if set(raw) != required:
        unknown = sorted(set(raw) - required)
        missing = sorted(required - set(raw))
        detail = f"unknown keys: {', '.join(unknown)}" if unknown else f"missing keys: {', '.join(missing)}"
        raise ValueError(f"{path} {detail}")
    if not isinstance(raw["enabled"], bool):
        raise TypeError(f"{path}.enabled must be bool")
    values: dict[str, Any] = {"enabled": raw["enabled"]}
    for name, minimum, maximum in (
        ("atr_period", 1, 512),
        ("lookback_bars", 2, 4096),
        ("minimum_plateau_touches", 2, 64),
    ):
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{path}.{name} must be an integer in [{minimum}, {maximum}]")
        values[name] = value
    if values["minimum_plateau_touches"] > values["lookback_bars"]:
        raise ValueError(f"{path}.minimum_plateau_touches cannot exceed lookback_bars")
    for name in ("equality_tolerance_atr", "minimum_sweep_atr", "zone_half_width_atr"):
        try:
            value = _decimal(raw[name])
        except Exception as exc:
            raise ValueError(f"{path}.{name} must be numeric") from exc
        if not value.is_finite() or value <= 0 or value > 20:
            raise ValueError(f"{path}.{name} must be in (0, 20]")
        values[name] = value
    return values


def history_required(parameters: Mapping[str, Any]) -> int:
    return max(int(parameters["atr_period"]) + 1, int(parameters["lookback_bars"]) + 1)


def evaluate(
    bars: Sequence[SRBar],
    *,
    market_identity: Mapping[str, str],
    parameters: Mapping[str, Any],
):
    from .registry import KernelEvaluation

    values = tuple(bars)
    if len(values) < history_required(parameters):
        return KernelEvaluation(candidates=(), consumed_feature_rows=())
    period = int(parameters["atr_period"])
    lookback = int(parameters["lookback_bars"])
    minimum = int(parameters["minimum_plateau_touches"])
    equality = _decimal(parameters["equality_tolerance_atr"])
    sweep_amount = _decimal(parameters["minimum_sweep_atr"])
    width_multiple = _decimal(parameters["zone_half_width_atr"])
    sweep = values[-1]
    prior = values[-lookback - 1 : -1]
    atr = wilder_atr(values, period)
    tolerance = atr * equality
    sweep_distance = atr * sweep_amount
    clusters: dict[str, Mapping[str, Any]] = {}
    results: list[Candidate] = []
    for side in (ZoneSide.RESISTANCE, ZoneSide.SUPPORT):
        extrema = tuple((bar.high if side is ZoneSide.RESISTANCE else bar.low, bar.identity) for bar in prior)
        cluster = _best_cluster(extrema, tolerance=tolerance, minimum=minimum, side=side)
        if cluster is None:
            continue
        center, members = cluster
        reclaimed = (
            sweep.high >= center + sweep_distance and sweep.close <= center + tolerance
            if side is ZoneSide.RESISTANCE
            else sweep.low <= center - sweep_distance and sweep.close >= center - tolerance
        )
        clusters[side.value] = {
            "center": center,
            "cluster_member_bar_ids": members,
            "reclaimed": reclaimed,
        }
        if not reclaimed:
            continue
        width = atr * width_multiple
        results.append(
            Candidate(
                candidate_key=f"{sweep.identity}:{side.value}:{center}",
                venue=market_identity["venue"],
                instrument_id=market_identity["instrument_id"],
                asset=market_identity["asset"],
                source_timeframe=sweep.timeframe,
                kernel_id=KERNEL_ID,
                kernel_version=VERSION,
                side=side,
                center=center,
                lower=center - width,
                upper=center + width,
                formed_at=sweep.bar_close_at,
                available_at=sweep.bar_close_at,
                source_evidence_id=sweep.identity,
                creation_atr=atr,
            )
        )
    previous_close = values[-2].close if len(values) > 1 else None
    feature_row = {
        "cutoff": sweep.bar_close_at,
        "timeframe": sweep.timeframe,
        "kernel_id": KERNEL_ID,
        "kernel_version": VERSION,
        "bar_open_at": sweep.bar_open_at,
        "bar_close_at": sweep.bar_close_at,
        "bar_id": sweep.identity,
        "open": sweep.open,
        "high": sweep.high,
        "low": sweep.low,
        "close": sweep.close,
        "volume": sweep.volume,
        "previous_close": previous_close,
        "true_range": true_range(sweep, previous_close),
        "atr_period": period,
        "atr": atr,
        "lookback_bars": lookback,
        "minimum_plateau_touches": minimum,
        "equality_tolerance_atr": equality,
        "minimum_sweep_atr": sweep_amount,
        "zone_half_width_atr": width_multiple,
        "plateau_clusters": clusters,
    }
    return KernelEvaluation(
        candidates=tuple(sorted(results, key=lambda item: (item.available_at, item.side.value, item.candidate_key))),
        consumed_feature_rows=(feature_row,),
    )


__all__ = [
    "IDENTIFIER",
    "KERNEL_ID",
    "evaluate",
    "history_required",
    "parse_parameters",
]
