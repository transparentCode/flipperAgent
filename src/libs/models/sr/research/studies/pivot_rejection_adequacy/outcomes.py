"""Causal pivot-rejection candidates and matched naïve-band outcomes."""

from __future__ import annotations

import math
from datetime import datetime

from libs.models.sr.detection.pivot_rejection import detect_pivot_rejection_bands
from libs.models.sr.domain import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    SRStateKey,
)
from libs.models.sr.research.metrics.first_revisit import (
    first_revisit_outcome,
    prior_close_control_candidate,
)
from libs.models.sr.research.replay.atr import compute_atr_series
from libs.models.sr.research.source.capsules import SourceCapsule

from .config import PivotRejectionAdequacyConfig
from .contracts import CandidateCase, NaiveControl, OutcomeStatus


_NAIVE_SOURCE = "prior_close_naive_v2_1"


def build_model_bars(
    capsule: SourceCapsule, *, config: PivotRejectionAdequacyConfig
) -> tuple[ClosedBar, ...]:
    if (
        type(capsule) is not SourceCapsule
        or type(config) is not PivotRejectionAdequacyConfig
    ):
        raise ContractValidationError("V2.1 model requires typed capsule/configuration")
    atr_values = compute_atr_series(capsule, config.atr.to_payload()["period"])
    common_start = config.atr.to_payload()["common_start_index"]
    if len(atr_values) != len(capsule.bars) or len(capsule.bars) <= common_start:
        raise ContractValidationError("frozen source cannot satisfy common ATR start")
    key = SRStateKey(config.venue, config.asset, config.timeframe)
    bars: list[ClosedBar] = []
    for index in range(common_start, len(capsule.bars)):
        source, atr = capsule.bars[index], atr_values[index]
        if atr is None:
            raise ContractValidationError("ATR is unavailable at frozen common start")
        bars.append(
            ClosedBar(
                state_key=key,
                bar_id=source.bar_id,
                closed_at=source.closed_at,
                open=source.open,
                high=source.high,
                low=source.low,
                close=source.close,
                atr_at_close=atr,
            )
        )
    return tuple(bars)


def _fold_for(timestamp: datetime, config: PivotRejectionAdequacyConfig) -> str | None:
    return next(
        (fold.name for fold in config.folds if fold.start <= timestamp < fold.end), None
    )


def _fold_end(name: str, config: PivotRejectionAdequacyConfig) -> datetime:
    for fold in config.folds:
        if fold.name == name:
            return fold.end
    raise ContractValidationError("band references unknown V2.1 fold")


def _status(
    candidate: CandidateLevel,
    *,
    confirmation_index: int,
    fold: str,
    bars: tuple[ClosedBar, ...],
    config: PivotRejectionAdequacyConfig,
) -> tuple[OutcomeStatus, object | None]:
    outcome = first_revisit_outcome(
        candidate,
        confirmation_index=confirmation_index,
        fold_end=_fold_end(fold, config),
        bars=bars,
        **{
            key: value
            for key, value in config.outcome.to_payload().items()
            if key != "window_policy"
        },
    )
    if outcome is None:
        return OutcomeStatus.NO_TOUCH, None
    return (
        OutcomeStatus.COMPLETED if outcome.completed else OutcomeStatus.RIGHT_CENSORED
    ), outcome


def evaluate_candidates(
    bars: tuple[ClosedBar, ...], *, config: PivotRejectionAdequacyConfig
) -> tuple[CandidateCase, ...]:
    if type(bars) is not tuple or any(type(bar) is not ClosedBar for bar in bars):
        raise ContractValidationError("V2.1 candidates require ClosedBar tuple")
    positions = {bar.closed_at: index for index, bar in enumerate(bars)}
    cases: list[CandidateCase] = []
    for candidate in detect_pivot_rejection_bands(bars, config.detector):
        confirmation_index, pivot_index = (
            positions.get(candidate.available_at),
            positions.get(candidate.formed_at),
        )
        if (
            confirmation_index is None
            or pivot_index is None
            or pivot_index >= confirmation_index
        ):
            raise ContractValidationError(
                "candidate timing cannot be aligned to V2.1 bars"
            )
        width_atr = (
            candidate.geometry.upper_bound - candidate.geometry.lower_bound
        ) / candidate.atr_at_creation
        if not math.isfinite(width_atr) or width_atr <= 0.0:
            raise ContractValidationError(
                "candidate zone width in ATR must be finite and positive"
            )
        fold = _fold_for(candidate.available_at, config)
        status, outcome = (
            (OutcomeStatus.OUTSIDE_FOLDS, None)
            if fold is None
            else _status(
                candidate,
                confirmation_index=confirmation_index,
                fold=fold,
                bars=bars,
                config=config,
            )
        )
        cases.append(
            CandidateCase(
                candidate=candidate,
                confirmation_bar_id=bars[confirmation_index].bar_id,
                confirmation_index=confirmation_index,
                pivot_index=pivot_index,
                fold=fold,
                status=status,
                outcome=outcome,
                zone_width_atr=width_atr,
            )
        )
    if len({case.candidate.candidate_id for case in cases}) != len(cases):
        raise ContractValidationError("V2.1 candidates must be unique")
    return tuple(cases)


def build_naive_controls(
    cases: tuple[CandidateCase, ...],
    bars: tuple[ClosedBar, ...],
    *,
    config: PivotRejectionAdequacyConfig,
) -> tuple[NaiveControl, ...]:
    if (
        type(cases) is not tuple
        or any(type(case) is not CandidateCase for case in cases)
        or type(bars) is not tuple
        or any(type(bar) is not ClosedBar for bar in bars)
    ):
        raise ContractValidationError("V2.1 controls require typed cases/bars")
    controls: list[NaiveControl] = []
    for case in cases:
        if case.fold is None:
            continue
        if (
            case.confirmation_index <= 0
            or bars[case.confirmation_index].bar_id != case.confirmation_bar_id
        ):
            raise ContractValidationError("control confirmation cannot be aligned")
        prior = bars[case.confirmation_index - 1]
        for side in config.control_side_order:
            candidate = prior_close_control_candidate(
                case.candidate, prior_bar=prior, side=side, source=_NAIVE_SOURCE
            )
            status, outcome = _status(
                candidate,
                confirmation_index=case.confirmation_index,
                fold=case.fold,
                bars=bars,
                config=config,
            )
            controls.append(
                NaiveControl(
                    real_case_id=case.case_id,
                    candidate=candidate,
                    confirmation_bar_id=case.confirmation_bar_id,
                    confirmation_index=case.confirmation_index,
                    fold=case.fold,
                    prior_close=prior.close,
                    status=status,
                    outcome=outcome,
                    zone_width_atr=case.zone_width_atr,
                )
            )
    expected = (
        sum(case.fold is not None for case in cases)
        * config.controls_per_real_candidate
    )
    if len(controls) != expected:
        raise ContractValidationError(
            "naive control count does not reconcile to in-fold candidates"
        )
    return tuple(controls)


__all__ = ["build_model_bars", "build_naive_controls", "evaluate_candidates"]
