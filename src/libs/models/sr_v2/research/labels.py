"""Research labels over the pure runtime target function."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from ..contracts import ForecastOutcome
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..domain.zones import ZoneLineage
from ..forecast.targets import (
    ScientificReaction,
    TargetObservation,
    TwoStageTargetView,
    label_forecast,
)


def target_provenance_fingerprint(
    zone: ZoneLineage,
    target: TargetObservation,
    *,
    target_fingerprint: str,
) -> str:
    """Bind a target label to the exact zone geometry and target semantics."""

    return canonical_hash(
        {
            "target_fingerprint": target_fingerprint,
            "zone": zone,
            "target": target,
        }
    )


def label_candidates(
    zones: Iterable[ZoneLineage],
    bars: Sequence[SRBar],
    *,
    horizons: Sequence[timedelta],
    bounce_excursion_atr: Decimal,
    break_buffer_atr: Decimal,
    break_confirmation_bars: int,
    observation_timeframe: str,
    observation_duration: timedelta,
    issued_at_by_zone: Mapping[str, datetime] | None = None,
) -> tuple[TargetObservation, ...]:
    if issued_at_by_zone is None:
        raise ValueError("protected research labeling requires explicit issuance mapping")
    values = tuple(bars)
    return tuple(
        label_forecast(
            zone,
            issued_at=issued_at_by_zone[zone.zone_id],
            future_bars=values,
            horizon=horizon,
            bounce_excursion_atr=bounce_excursion_atr,
            break_buffer_atr=break_buffer_atr,
            break_confirmation_bars=break_confirmation_bars,
            observation_timeframe=observation_timeframe,
            observation_duration=observation_duration,
        )
        for zone in zones
        for horizon in horizons
    )


def two_stage_view_from_observation(observation: TargetObservation) -> TwoStageTargetView:
    """Project the compatible four-class event record into the scientific view.

    This adapter is intentionally pure and keeps legacy labels usable by
    research readers.  New scientific compilation should use
    ``label_scientific_target`` so its barriers are candidate-independent.
    """

    if not isinstance(observation, TargetObservation):
        raise TypeError("observation must be TargetObservation")
    if observation.outcome is ForecastOutcome.NO_TOUCH:
        touch: bool | None = False if observation.complete else None
        return TwoStageTargetView(
            touch=touch,
            reaction=None,
            reaction_eligible=False,
            censored=observation.censored or touch is None,
            ambiguous=observation.ambiguous,
            touch_at=observation.touch_at,
        )
    reaction = {
        ForecastOutcome.TOUCH_THEN_BOUNCE: ScientificReaction.BOUNCE,
        ForecastOutcome.TOUCH_THEN_BREAK: ScientificReaction.BREAK,
    }.get(observation.outcome)
    eligible = reaction is not None and not observation.ambiguous and not observation.censored
    return TwoStageTargetView(
        touch=True,
        reaction=reaction if eligible else None,
        reaction_eligible=eligible,
        censored=observation.censored,
        ambiguous=observation.ambiguous,
        touch_at=observation.touch_at,
    )


__all__ = [
    "label_candidates",
    "target_provenance_fingerprint",
    "two_stage_view_from_observation",
]
