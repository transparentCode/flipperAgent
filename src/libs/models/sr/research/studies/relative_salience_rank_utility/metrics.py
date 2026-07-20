"""Pure causal rank, utility, and hierarchical-bootstrap calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Iterable

import numpy as np

from libs.models.sr.domain import ContractValidationError

from .config import COHORTS, RelativeSalienceRankConfig
from .contracts import Gate, Quartile, RankCase, RankDisposition


@dataclass(frozen=True)
class SaliencePoint:
    asset: str
    timeframe: str
    confirmation_at: datetime
    raw_salience_atr: float
    identity: str

    def __post_init__(self) -> None:
        if (self.asset, self.timeframe) not in COHORTS or type(self.identity) is not str or not self.identity:
            raise ContractValidationError("salience point identity is invalid")
        if self.confirmation_at.tzinfo is None or self.confirmation_at.utcoffset() is None:
            raise ContractValidationError("salience point timestamp must be UTC-aware")
        if not isinstance(self.raw_salience_atr, (int, float)) or isinstance(self.raw_salience_atr, bool) or not math.isfinite(float(self.raw_salience_atr)) or self.raw_salience_atr < 0.0:
            raise ContractValidationError("salience point value must be finite and non-negative")


def relative_salience_rank(current: SaliencePoint, history: tuple[SaliencePoint, ...]) -> tuple[float, int]:
    """Deterministic causal midrank using only earlier same-cohort points."""

    if type(current) is not SaliencePoint or type(history) is not tuple or any(type(point) is not SaliencePoint for point in history):
        raise ContractValidationError("relative rank requires typed salience points")
    lower = current.confirmation_at - timedelta(days=365)
    prior = tuple(
        point.raw_salience_atr
        for point in history
        if (point.asset, point.timeframe) == (current.asset, current.timeframe)
        and lower <= point.confirmation_at < current.confirmation_at
    )
    if not prior:
        raise ContractValidationError("relative rank requires causal same-cohort history")
    value = current.raw_salience_atr
    return ((sum(item < value for item in prior) + 0.5 * sum(item == value for item in prior)) / len(prior), len(prior))


def quartile(rank: float) -> Quartile:
    if not isinstance(rank, (int, float)) or isinstance(rank, bool) or not math.isfinite(float(rank)) or not 0.0 <= float(rank) <= 1.0:
        raise ContractValidationError("relative salience rank must be in [0, 1]")
    return Quartile.Q1 if rank < 0.25 else Quartile.Q2 if rank < 0.50 else Quartile.Q3 if rank < 0.75 else Quartile.Q4


def rank_auc(cases: tuple[RankCase, ...]) -> float:
    """Tie-aware AUC for completed cases, using rank only as a reporting score."""

    completed = _completed(cases)
    positives = tuple(case for case in completed if case.paired_excess_quality_atr > 0.0)
    negatives = tuple(case for case in completed if case.paired_excess_quality_atr <= 0.0)
    if not positives or not negatives:
        raise ContractValidationError("rank AUC requires both success classes")
    wins = sum(
        1.0 if positive.relative_salience_rank > negative.relative_salience_rank else 0.5 if positive.relative_salience_rank == negative.relative_salience_rank else 0.0
        for positive in positives for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _completed(cases: Iterable[RankCase]) -> tuple[RankCase, ...]:
    result = tuple(case for case in cases if type(case) is RankCase and case.completed)
    if any(type(case) is not RankCase for case in cases):
        raise ContractValidationError("metrics require RankCase records")
    return result


def _success_rate(cases: tuple[RankCase, ...]) -> float:
    if not cases:
        raise ContractValidationError("success rate requires cases")
    return sum(case.paired_excess_quality_atr > 0.0 for case in cases) / len(cases)


def _q_metrics(cases: tuple[RankCase, ...]) -> tuple[float, float]:
    q4 = tuple(case for case in cases if case.quartile is Quartile.Q4)
    lower = tuple(case for case in cases if case.quartile in {Quartile.Q1, Quartile.Q2})
    if not q4 or not lower:
        raise ContractValidationError("quartile utility requires Q4 and Q1-Q2 cases")
    lift = _success_rate(q4) - _success_rate(lower)
    return lift, sum(case.paired_excess_quality_atr for case in q4) / len(q4)


def _cohort_lifts(cases: tuple[RankCase, ...]) -> tuple[float, ...]:
    grouped: dict[tuple[str, str], list[RankCase]] = defaultdict(list)
    for case in cases:
        grouped[(case.asset, case.timeframe)].append(case)
    lifts = []
    for cohort in COHORTS:
        cohort_cases = tuple(grouped[cohort])
        q4 = tuple(case for case in cohort_cases if case.quartile is Quartile.Q4)
        lower = tuple(case for case in cohort_cases if case.quartile in {Quartile.Q1, Quartile.Q2})
        if q4 and lower:
            lifts.append(_success_rate(q4) - _success_rate(lower))
    if not lifts:
        raise ContractValidationError("median cohort rank lift requires comparable cohorts")
    return tuple(lifts)


def _metrics(cases: tuple[RankCase, ...]) -> dict[str, float]:
    lift, q4_excess = _q_metrics(cases)
    lifts = _cohort_lifts(cases)
    return {
        "rank_auc": rank_auc(cases),
        "q4_success_lift": lift,
        "q4_mean_paired_excess_quality_atr": q4_excess,
        "median_cohort_rank_lift": float(np.median(np.asarray(lifts, dtype=float))),
    }


def hierarchical_bootstrap(cases: tuple[RankCase, ...], *, draws: int = 10_000, seed: int = 2404) -> dict[str, tuple[float, float]]:
    """Resample every asset/timeframe/month-cell replica independently."""

    completed = _completed(cases)
    if type(draws) is not int or draws != 10_000 or type(seed) is not int or seed != 2404:
        raise ContractValidationError("V2.4 bootstrap parameters are fixed")
    cells: dict[tuple[str, str, str], tuple[RankCase, ...]] = {}
    grouped: dict[tuple[str, str, str], list[RankCase]] = defaultdict(list)
    for case in completed:
        grouped[(case.asset, case.timeframe, case.month)].append(case)
    for key, value in grouped.items():
        cells[key] = tuple(sorted(value, key=lambda case: case.case_id))
    if not cells:
        raise ContractValidationError("bootstrap requires completed cases")
    ordered_cells = tuple(cells[key] for key in sorted(cells))
    generator = np.random.Generator(np.random.PCG64(seed))
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(draws):
        replica: list[RankCase] = []
        for chosen_index in generator.integers(0, len(ordered_cells), size=len(ordered_cells)):
            cell = ordered_cells[int(chosen_index)]
            sampled = generator.integers(0, len(cell), size=len(cell))
            replica.extend(cell[int(index)] for index in sampled)
        try:
            current = _metrics(tuple(replica))
        except ContractValidationError:
            continue
        for name, value in current.items():
            values[name].append(value)
    expected = {"rank_auc", "q4_success_lift", "q4_mean_paired_excess_quality_atr", "median_cohort_rank_lift"}
    if set(values) != expected or any(len(values[name]) != draws for name in expected):
        raise ContractValidationError("bootstrap generated undefined metric replicas")
    return {name: tuple(float(value) for value in np.quantile(np.asarray(values[name], dtype=float), (0.05, 0.95))) for name in sorted(values)}


def assess(cases: tuple[RankCase, ...], *, config: RelativeSalienceRankConfig) -> tuple[dict[str, object], tuple[Gate, ...], RankDisposition]:
    """Apply exact readiness and uncertainty disposition precedence."""

    if type(config) is not RelativeSalienceRankConfig or type(cases) is not tuple:
        raise ContractValidationError("V2.4 assessment requires typed cases/configuration")
    completed = _completed(cases)
    by_cohort = {f"{asset}/{timeframe}": sum(case.completed and (case.asset, case.timeframe) == (asset, timeframe) for case in cases) for asset, timeframe in COHORTS}
    q4_count = sum(case.quartile is Quartile.Q4 for case in completed)
    readiness = len(completed) >= 350 and q4_count >= 60 and all(count >= 20 for count in by_cohort.values())
    monthly: dict[str, dict[str, int]] = {}
    for case in cases:
        key = f"{case.asset}/{case.timeframe}/{case.month}"
        current = monthly.setdefault(key, {"completed": 0, "right_censored": 0, "no_touch": 0})
        if case.completed:
            current["completed"] += 1
        elif case.real_status.value == "RIGHT_CENSORED":
            current["right_censored"] += 1
        else:
            current["no_touch"] += 1
    counts = {"scored_completed_cases": len(completed), "completed_q4_cases": q4_count, "completed_by_cohort": by_cohort, "cases_by_asset_timeframe_month": {key: monthly[key] for key in sorted(monthly)}, "censored_cases": sum(case.real_status.value == "RIGHT_CENSORED" for case in cases)}
    if not readiness:
        return counts, (), RankDisposition.INSUFFICIENT_SOURCE_DENSITY
    try:
        point = _metrics(completed)
        intervals = hierarchical_bootstrap(completed)
    except ContractValidationError:
        return {**counts, "rank_metrics": "undefined"}, (), RankDisposition.INSUFFICIENT_RANK_EVIDENCE
    rules = (
        ("utility.rank_auc", "rank_auc", 0.50),
        ("utility.q4_success_lift", "q4_success_lift", 0.0),
        ("utility.q4_mean_paired_excess_quality_atr", "q4_mean_paired_excess_quality_atr", 0.0),
        ("stability.median_cohort_rank_lift", "median_cohort_rank_lift", 0.0),
    )
    gates = tuple(Gate(name, point[key], intervals[key][0], intervals[key][1], intervals[key][0] > threshold) for name, key, threshold in rules)
    if all(gate.passed for gate in gates):
        disposition = RankDisposition.RELATIVE_SALIENCE_SUPPORTED_FOR_SHADOW
    elif any(gate.upper_90 <= threshold for gate, (_, _, threshold) in zip(gates[:3], rules[:3])):
        disposition = RankDisposition.RELATIVE_SALIENCE_NOT_SUPPORTED
    else:
        disposition = RankDisposition.INSUFFICIENT_RANK_EVIDENCE
    return {**counts, **point, "bootstrap_90": {name: {"lower": bounds[0], "upper": bounds[1]} for name, bounds in intervals.items()}}, gates, disposition


__all__ = ["SaliencePoint", "assess", "hierarchical_bootstrap", "quartile", "rank_auc", "relative_salience_rank"]
