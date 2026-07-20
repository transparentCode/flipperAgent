"""Deterministic V2.4 study construction; no provider or artifact I/O."""

from __future__ import annotations

from libs.models.sr.detection.causal_swing_salience import detect_causal_swing_salience
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey, ZoneSide
from libs.models.sr.research.metrics.first_revisit import first_revisit_outcome, prior_close_control_candidate
from libs.models.sr.research.replay.atr import compute_atr_series

from .config import END, START, RelativeSalienceRankConfig
from .contracts import CaseStatus, ControlRecord, RankCase, RankStudy, SourceBundle, SourceMember
from .metrics import SaliencePoint, assess, quartile, relative_salience_rank


def _model_bars(member: SourceMember) -> tuple[ClosedBar, ...]:
    atr = compute_atr_series(member.bars, 14)
    if len(atr) != len(member.bars) or len(member.bars) <= 28:
        raise ContractValidationError("source cannot satisfy V2.4 common ATR start")
    key = SRStateKey("binance_usdm", member.asset, member.timeframe)
    result = []
    for index in range(28, len(member.bars)):
        value = atr[index]
        if value is None:
            raise ContractValidationError("V2.4 ATR is unavailable at common start")
        source = member.bars[index]
        result.append(ClosedBar(key, source.bar_id, source.closed_at, source.open, source.high, source.low, source.close, value))
    return tuple(result)


def _status(outcome: object | None) -> CaseStatus:
    if outcome is None:
        return CaseStatus.NO_TOUCH
    return CaseStatus.COMPLETED if outcome.completed else CaseStatus.RIGHT_CENSORED


def _first_revisit(candidate, *, confirmation_index: int, bars: tuple[ClosedBar, ...]):
    return first_revisit_outcome(candidate, confirmation_index=confirmation_index, fold_end=END, bars=bars, first_touch_offset_bars=1, touch_search_bars=50, horizon_bars=10)


def _case_for(
    member: SourceMember,
    bars: tuple[ClosedBar, ...],
    *,
    confirmation_index: int,
    candidate,
    raw_salience: float,
    rank: float,
    prior_count: int,
) -> RankCase:
    real = _first_revisit(candidate, confirmation_index=confirmation_index, bars=bars)
    controls = []
    prior = bars[confirmation_index - 1]
    for side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
        control = prior_close_control_candidate(candidate, prior_bar=prior, side=side, source="prior_close_naive_v2_4")
        outcome = _first_revisit(control, confirmation_index=confirmation_index, bars=bars)
        controls.append(ControlRecord(side, control, _status(outcome), outcome))
    same = next(item.outcome for item in controls if item.side is candidate.side)
    status = _status(real)
    excess = None
    if status is CaseStatus.COMPLETED and same is not None and same.completed:
        excess = real.quality_reference_atr - same.quality_reference_atr
    return RankCase(
        member.asset, member.timeframe, confirmation_index, candidate, raw_salience,
        rank, prior_count, quartile(rank), status, real, tuple(controls), same, excess,
        candidate.available_at.strftime("%Y-%m"),
    )


def _member_cases(member: SourceMember) -> tuple[RankCase, ...]:
    bars = _model_bars(member)
    confirmations = detect_causal_swing_salience(bars)
    points = tuple(
        SaliencePoint(member.asset, member.timeframe, bars[item.confirmation_index].closed_at, item.raw_salience_atr, item.candidate.candidate_id)
        for item in confirmations if item.candidate is not None
    )
    cases = []
    for item in confirmations:
        candidate = item.candidate
        if candidate is None or candidate.available_at < START or candidate.available_at >= END:
            continue
        current = SaliencePoint(member.asset, member.timeframe, candidate.available_at, item.raw_salience_atr, candidate.candidate_id)
        rank, prior_count = relative_salience_rank(current, points)
        cases.append(_case_for(member, bars, confirmation_index=item.confirmation_index, candidate=candidate, raw_salience=item.raw_salience_atr, rank=rank, prior_count=prior_count))
    return tuple(sorted(cases, key=lambda case: (case.candidate.available_at, case.case_id)))


def compute_study(
    config: RelativeSalienceRankConfig,
    *,
    source_bundle: SourceBundle,
    implementation_commit: str,
) -> RankStudy:
    if type(config) is not RelativeSalienceRankConfig or type(source_bundle) is not SourceBundle:
        raise ContractValidationError("V2.4 study requires typed config/source")
    if source_bundle.config_hash != config.config_hash:
        raise ContractValidationError("V2.4 source/config identity mismatch")
    if implementation_commit != source_bundle.implementation_commit:
        raise ContractValidationError("V2.4 source/evaluation implementation identity mismatch")
    cases = tuple(case for member in source_bundle.members for case in _member_cases(member))
    metrics, gates, disposition = assess(cases, config=config)
    return RankStudy(implementation_commit, config.config_hash, source_bundle.bundle_id, cases, gates, disposition, metrics)


__all__ = ["compute_study"]
