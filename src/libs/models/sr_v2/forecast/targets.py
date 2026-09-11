"""Point-in-time mutually exclusive SR event labels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from itertools import pairwise

from ..config.schema import TIMEFRAME_DURATIONS
from ..contracts import ForecastOutcome, ZoneSide, require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..domain.zones import ZoneLineage
from ..features.time import ContinuousUTCGrid, grid_for

TARGET_SCHEMA = "sr_v2.event_targets.v1"

# The scientific target surface is deliberately separate from the historical
# Phase-1 label below.  These constants identify a calculation, they are not a
# catalogue of tunable parameters.
REFERENCE_VOLATILITY_ID = "simple_true_range_mean@1"
SCIENTIFIC_TARGET_SCHEMA = "sr_v2.two_stage_targets.v2"


class ScientificReaction(str, Enum):
    """The only ordered reactions admitted by the scientific target view."""

    BOUNCE = "BOUNCE"
    BREAK = "BREAK"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedTargetSpec:
    """Fully resolved, candidate-independent target semantics.

    All scientific numeric choices are caller supplied.  The reference
    algorithm and schema are code-owned identities so a target receipt cannot
    be silently compared with a different implementation.
    """

    source_timeframe: str
    source_horizon_bars: int
    reference_lookback: int
    barrier_multiplier: Decimal
    observation_timeframe: str
    observation_duration: timedelta

    def __post_init__(self) -> None:
        if self.source_timeframe not in TIMEFRAME_DURATIONS:
            raise ValueError("source_timeframe must be a supported timeframe")
        if (
            isinstance(self.source_horizon_bars, bool)
            or not isinstance(self.source_horizon_bars, int)
            or self.source_horizon_bars <= 0
        ):
            raise ValueError("source_horizon_bars must be a positive integer")
        if (
            isinstance(self.reference_lookback, bool)
            or not isinstance(self.reference_lookback, int)
            or self.reference_lookback <= 0
        ):
            raise ValueError("reference_lookback must be a positive integer")
        _validate_threshold(self.barrier_multiplier, "barrier_multiplier")
        _observation_grid(self.observation_timeframe, self.observation_duration)
        horizon = TIMEFRAME_DURATIONS[self.source_timeframe] * self.source_horizon_bars
        if horizon % self.observation_duration != timedelta(0):
            raise ValueError(
                "target horizon must be an exact multiple of observation duration"
            )

    @property
    def horizon(self) -> timedelta:
        return TIMEFRAME_DURATIONS[self.source_timeframe] * self.source_horizon_bars

    @property
    def reference_volatility_id(self) -> str:
        return REFERENCE_VOLATILITY_ID

    @property
    def target_fingerprint(self) -> str:
        return scientific_target_fingerprint(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetReferenceVolatility:
    """Causal volatility receipt used by one scientific target episode."""

    algorithm_id: str
    lookback: int
    source_timeframe: str
    issuance_cutoff: datetime
    source_bar_identities: tuple[str, ...]
    value: Decimal
    source_fingerprint: str

    def __post_init__(self) -> None:
        if self.algorithm_id != REFERENCE_VOLATILITY_ID:
            raise ValueError("unsupported reference volatility algorithm")
        if (
            isinstance(self.lookback, bool)
            or not isinstance(self.lookback, int)
            or self.lookback <= 0
        ):
            raise ValueError("reference volatility lookback must be positive")
        if self.source_timeframe not in TIMEFRAME_DURATIONS:
            raise ValueError("reference volatility timeframe is unsupported")
        require_utc(self.issuance_cutoff, field_name="issuance_cutoff")
        if len(self.source_bar_identities) != self.lookback + 1:
            raise ValueError(
                "reference volatility receipt must retain exact N+1 identities"
            )
        if len(set(self.source_bar_identities)) != len(self.source_bar_identities):
            raise ValueError("reference volatility source identities must be unique")
        if any(
            not isinstance(identity, str) or not identity.strip()
            for identity in self.source_bar_identities
        ):
            raise ValueError("reference volatility source identities must be non-empty")
        _validate_threshold(self.value, "reference volatility value")
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint) != 64
        ):
            raise ValueError("reference volatility source fingerprint must be SHA-256")
        try:
            int(self.source_fingerprint, 16)
        except ValueError as exc:
            raise ValueError(
                "reference volatility source fingerprint must be hexadecimal"
            ) from exc

    @property
    def issuance_at(self) -> datetime:
        return self.issuance_cutoff


@dataclass(frozen=True, slots=True, kw_only=True)
class TwoStageTargetView:
    """Scientific touch/reaction projection of the compatible event label."""

    touch: bool | None
    reaction: ScientificReaction | None
    reaction_eligible: bool
    censored: bool
    ambiguous: bool = False
    touch_at: datetime | None = None
    reaction_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.touch not in (True, False, None):
            raise TypeError("touch must be bool or None")
        if not isinstance(self.reaction_eligible, bool) or not isinstance(
            self.censored, bool
        ):
            raise TypeError("reaction_eligible and censored must be bool")
        if not isinstance(self.ambiguous, bool):
            raise TypeError("ambiguous must be bool")
        if self.reaction is not None and not isinstance(
            self.reaction, ScientificReaction
        ):
            raise TypeError("reaction must be ScientificReaction or None")
        if self.reaction is not None and (
            self.touch is not True or not self.reaction_eligible or self.censored
        ):
            raise ValueError("a reaction requires an uncensored touched observation")
        if self.reaction_at is not None:
            require_utc(self.reaction_at, field_name="reaction_at")
        if self.touch_at is not None:
            require_utc(self.touch_at, field_name="touch_at")
        if self.touch is False and self.touch_at is not None:
            raise ValueError("untouched observation cannot have touch_at")
        if self.touch is None and self.reaction is not None:
            raise ValueError("censored touch cannot have a reaction")

    @property
    def touch_label(self) -> bool | None:
        return self.touch


@dataclass(frozen=True, slots=True, kw_only=True)
class ScientificTargetResult:
    """One immutable target receipt and its two-stage view."""

    zone_id: str
    horizon: timedelta
    issued_at: datetime
    observation_end_at: datetime
    last_observed_cutoff: datetime | None
    complete: bool
    view: TwoStageTargetView
    target_reference_volatility: TargetReferenceVolatility
    event_observation: TargetObservation

    def __post_init__(self) -> None:
        if not isinstance(self.zone_id, str) or not self.zone_id.strip():
            raise ValueError("zone_id must be non-empty")
        if not isinstance(self.horizon, timedelta) or self.horizon <= timedelta(0):
            raise ValueError("horizon must be positive")
        require_utc(self.issued_at, field_name="issued_at")
        require_utc(self.observation_end_at, field_name="observation_end_at")
        if self.observation_end_at != self.issued_at + self.horizon:
            raise ValueError("observation_end_at must equal issued_at plus horizon")
        if self.last_observed_cutoff is not None:
            require_utc(self.last_observed_cutoff, field_name="last_observed_cutoff")
            if (
                self.last_observed_cutoff <= self.issued_at
                or self.last_observed_cutoff > self.observation_end_at
            ):
                raise ValueError(
                    "last_observed_cutoff must be inside observation horizon"
                )
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")
        if not isinstance(self.view, TwoStageTargetView):
            raise TypeError("view must be TwoStageTargetView")
        if not isinstance(self.target_reference_volatility, TargetReferenceVolatility):
            raise TypeError("target_reference_volatility must be a receipt")
        if self.target_reference_volatility.issuance_cutoff != self.issued_at:
            raise ValueError("target receipt and issuance differ")
        if not isinstance(self.event_observation, TargetObservation):
            raise TypeError("event_observation must be TargetObservation")
        if (
            self.event_observation.zone_id != self.zone_id
            or self.event_observation.issued_at != self.issued_at
        ):
            raise ValueError(
                "event observation identity differs from scientific result"
            )

    @property
    def reaction(self) -> ScientificReaction | None:
        return self.view.reaction

    @property
    def touch(self) -> bool | None:
        return self.view.touch

    @property
    def reaction_eligible(self) -> bool:
        return self.view.reaction_eligible

    @property
    def censored(self) -> bool:
        return self.view.censored


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetObservation:
    zone_id: str
    horizon: timedelta
    issued_at: datetime
    observation_end_at: datetime
    last_observed_cutoff: datetime | None
    complete: bool
    outcome: ForecastOutcome
    touch_at: datetime | None
    censored: bool
    ambiguous: bool
    favorable_excursion_atr: Decimal
    adverse_excursion_atr: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.zone_id, str) or not self.zone_id.strip():
            raise ValueError("zone_id must be non-empty")
        if not isinstance(self.horizon, timedelta) or self.horizon <= timedelta(0):
            raise ValueError("horizon must be positive")
        require_utc(self.issued_at, field_name="issued_at")
        require_utc(self.observation_end_at, field_name="observation_end_at")
        if self.observation_end_at != self.issued_at + self.horizon:
            raise ValueError("observation_end_at must equal issued_at plus horizon")
        if self.last_observed_cutoff is not None:
            require_utc(self.last_observed_cutoff, field_name="last_observed_cutoff")
            if self.last_observed_cutoff <= self.issued_at:
                raise ValueError("last_observed_cutoff must follow issuance")
            if self.last_observed_cutoff > self.observation_end_at:
                raise ValueError("last_observed_cutoff cannot exceed observation end")
        if not isinstance(self.complete, bool) or not isinstance(self.censored, bool):
            raise TypeError("complete and censored must be bool")
        if not isinstance(self.ambiguous, bool):
            raise TypeError("ambiguous must be bool")
        if not isinstance(self.outcome, ForecastOutcome):
            raise TypeError("outcome must be ForecastOutcome")


class _IndexedSequence(Sequence[SRBar]):
    """Read-only view over a shared bar tuple without per-episode copying."""

    __slots__ = ("_start", "_stop", "_values")

    def __init__(self, values: Sequence[SRBar], start: int, stop: int) -> None:
        self._values = values
        self._start = start
        self._stop = stop

    def __len__(self) -> int:
        return self._stop - self._start

    def __getitem__(self, index: int | slice) -> SRBar | Sequence[SRBar]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step != 1:
                return tuple(self[index] for index in range(start, stop, step))
            return _IndexedSequence(
                self._values, self._start + start, self._start + stop
            )
        if not isinstance(index, int):
            raise TypeError("indexed bar view indices must be integers or slices")
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError("indexed bar view index out of range")
        return self._values[self._start + index]


def _validate_threshold(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive Decimal")


def _observation_grid(
    observation_timeframe: str,
    observation_duration: timedelta,
) -> ContinuousUTCGrid:
    if (
        not isinstance(observation_timeframe, str)
        or observation_timeframe not in TIMEFRAME_DURATIONS
    ):
        raise ValueError("observation_timeframe must be a supported timeframe")
    if not isinstance(
        observation_duration, timedelta
    ) or observation_duration <= timedelta(0):
        raise ValueError("observation_duration must be positive")
    expected = TIMEFRAME_DURATIONS[observation_timeframe]
    if observation_duration != expected:
        raise ValueError("observation_duration must derive from observation_timeframe")
    return grid_for(observation_timeframe)


def _is_aligned(bar: SRBar, grid: ContinuousUTCGrid) -> bool:
    return (
        bar.timeframe == grid.timeframe
        and bar.bar_close_at - bar.bar_open_at == grid.duration
        and grid.is_aligned(bar.bar_open_at)
        and grid.is_aligned(bar.bar_close_at)
        and bar.closed
        and bar.market_as_of == bar.bar_close_at
    )


def _overlap(zone: ZoneLineage, bar: SRBar) -> bool:
    return bar.high >= zone.lower and bar.low <= zone.upper


def _bounce_excursion(zone: ZoneLineage, bar: SRBar) -> Decimal:
    if zone.side is ZoneSide.RESISTANCE:
        return max(Decimal(0), (zone.lower - bar.low) / zone.creation_atr)
    return max(Decimal(0), (bar.high - zone.upper) / zone.creation_atr)


def _break_close(zone: ZoneLineage, bar: SRBar, break_buffer_atr: Decimal) -> bool:
    threshold = zone.creation_atr * break_buffer_atr
    if zone.side is ZoneSide.RESISTANCE:
        return bar.close > zone.upper + threshold
    return bar.close < zone.lower - threshold


def _ordered_window(
    future_bars: Sequence[SRBar],
    *,
    issued_at: datetime,
    observation_end_at: datetime,
    observation_timeframe: str,
    observation_duration: timedelta,
) -> Sequence[SRBar]:
    """Return the usable prefix, stopping at the first invalid/gapped bar."""

    grid = _observation_grid(observation_timeframe, observation_duration)
    values = tuple(future_bars)
    if any(not isinstance(bar, SRBar) for bar in values):
        raise TypeError("future_bars must contain only SRBar values")
    # Retain input order and only discard bars which are wholly before the
    # issuance or wholly after the requested horizon.  In particular, do not
    # filter a leading gap/overlap away: the first usable interval is part of
    # the causal contract and must open exactly at ``issued_at``.
    selected = tuple(
        bar
        for bar in values
        if bar.bar_close_at > issued_at and bar.bar_close_at <= observation_end_at
    )
    usable: list[SRBar] = []
    previous: SRBar | None = None
    for bar in selected:
        if not _is_aligned(bar, grid):
            break
        if previous is None and bar.bar_open_at != issued_at:
            break
        if previous is not None:
            if bar.bar_close_at <= previous.bar_close_at:
                break
            if bar.bar_open_at != previous.bar_close_at:
                break
        usable.append(bar)
        previous = bar
    return tuple(usable)


def label_forecast(
    zone: ZoneLineage,
    *,
    issued_at: datetime,
    future_bars: Sequence[SRBar],
    horizon: timedelta,
    bounce_excursion_atr: Decimal,
    break_buffer_atr: Decimal,
    break_confirmation_bars: int,
    observation_timeframe: str,
    observation_duration: timedelta,
) -> TargetObservation:
    """Label one forecast using only bars after its issuance cutoff.

    The first touching bar establishes the episode and is deliberately excluded
    from excursion accumulation. A terminal event before the horizon is
    complete even when the remaining future window is unavailable.
    """

    if not isinstance(zone, ZoneLineage):
        raise TypeError("zone must be ZoneLineage")
    require_utc(issued_at, field_name="issued_at")
    if issued_at < zone.available_at:
        raise ValueError("issued_at cannot precede zone availability")
    if not isinstance(horizon, timedelta) or horizon <= timedelta(0):
        raise ValueError("horizon must be positive")
    _observation_grid(observation_timeframe, observation_duration)
    _validate_threshold(bounce_excursion_atr, "bounce_excursion_atr")
    _validate_threshold(break_buffer_atr, "break_buffer_atr")
    if (
        isinstance(break_confirmation_bars, bool)
        or not isinstance(break_confirmation_bars, int)
        or break_confirmation_bars <= 0
    ):
        raise ValueError("break_confirmation_bars must be positive")

    observation_end_at = issued_at + horizon
    bars = _ordered_window(
        future_bars,
        issued_at=issued_at,
        observation_end_at=observation_end_at,
        observation_timeframe=observation_timeframe,
        observation_duration=observation_duration,
    )
    touch_at: datetime | None = None
    favorable = Decimal(0)
    adverse = Decimal(0)
    touched = False
    ambiguous = False
    resolved = False
    outcome = ForecastOutcome.NO_TOUCH
    break_count = 0

    for bar in bars:
        overlap = _overlap(zone, bar)
        if not touched:
            if not overlap:
                continue
            touched = True
            touch_at = bar.bar_close_at
            same_bar_bounce = _bounce_excursion(zone, bar) >= bounce_excursion_atr
            same_bar_break = _break_close(zone, bar, break_buffer_atr)
            if same_bar_bounce or same_bar_break:
                ambiguous = True
                resolved = True
                outcome = ForecastOutcome.TOUCH_UNRESOLVED
                break
            continue

        favorable = max(favorable, _bounce_excursion(zone, bar))
        if zone.side is ZoneSide.RESISTANCE:
            current_adverse = max(
                Decimal(0), (bar.high - zone.upper) / zone.creation_atr
            )
        else:
            current_adverse = max(
                Decimal(0), (zone.lower - bar.low) / zone.creation_atr
            )
        adverse = max(adverse, current_adverse)

        is_break = _break_close(zone, bar, break_buffer_atr)
        break_count = break_count + 1 if is_break else 0
        is_bounce = favorable >= bounce_excursion_atr
        is_confirmed_break = break_count >= break_confirmation_bars
        if is_bounce and is_confirmed_break:
            ambiguous = True
            resolved = True
            outcome = ForecastOutcome.TOUCH_UNRESOLVED
            break
        if is_confirmed_break:
            resolved = True
            outcome = ForecastOutcome.TOUCH_THEN_BREAK
            break
        if is_bounce:
            resolved = True
            outcome = ForecastOutcome.TOUCH_THEN_BOUNCE
            break

    last_observed_cutoff = bars[-1].bar_close_at if bars else None
    complete = last_observed_cutoff == observation_end_at
    if not touched:
        outcome = ForecastOutcome.NO_TOUCH
    elif not resolved:
        outcome = ForecastOutcome.TOUCH_UNRESOLVED
    censored = not resolved and not complete
    return TargetObservation(
        zone_id=zone.zone_id,
        horizon=horizon,
        issued_at=issued_at,
        observation_end_at=observation_end_at,
        last_observed_cutoff=last_observed_cutoff,
        # ``complete`` describes data coverage through the requested horizon;
        # an early terminal outcome is resolved but does not make the future
        # window complete.
        complete=complete,
        outcome=outcome,
        touch_at=touch_at,
        censored=censored,
        ambiguous=ambiguous,
        favorable_excursion_atr=favorable,
        adverse_excursion_atr=adverse,
    )


def target_fingerprint(
    *,
    horizons: Sequence[timedelta],
    bounce_excursion_atr: Decimal,
    break_buffer_atr: Decimal,
    break_confirmation_bars: int,
    observation_timeframe: str,
    observation_duration: timedelta,
) -> str:
    """Return the semantic identity of the target-generation rules.

    The fingerprint intentionally includes censoring and ambiguity semantics,
    not only numeric thresholds.  Calibration files and runtime forecasts can
    therefore never be mixed silently when the label definition changes.
    """

    _observation_grid(observation_timeframe, observation_duration)
    return canonical_hash(
        {
            "target_schema": TARGET_SCHEMA,
            "observation_timeframe": observation_timeframe,
            "observation_duration_seconds": int(observation_duration.total_seconds()),
            "horizons_seconds": tuple(int(value.total_seconds()) for value in horizons),
            "bounce_excursion_atr": str(bounce_excursion_atr),
            "break_buffer_atr": str(break_buffer_atr),
            "break_confirmation_bars": break_confirmation_bars,
            "ambiguity_rule": "same_bar_or_same_evaluation_bounce_and_confirmed_break_is_touch_unresolved",
            "first_touch_rule": "first_overlap_bar_excluded_from_excursion_accumulation",
            "censoring_rule": "only_unresolved_incomplete_windows_are_censored",
        }
    )


def resolve_target_spec(
    *,
    source_timeframe: str,
    source_horizon_bars: int,
    reference_lookback: int,
    barrier_multiplier: Decimal,
    observation_timeframe: str,
    observation_duration: timedelta,
) -> ResolvedTargetSpec:
    """Build the fully explicit candidate-independent target specification."""

    return ResolvedTargetSpec(
        source_timeframe=source_timeframe,
        source_horizon_bars=source_horizon_bars,
        reference_lookback=reference_lookback,
        barrier_multiplier=barrier_multiplier,
        observation_timeframe=observation_timeframe,
        observation_duration=observation_duration,
    )


def compute_target_reference_volatility(
    bars: Sequence[SRBar],
    *,
    source_timeframe: str,
    issuance_cutoff: datetime,
    lookback: int,
) -> TargetReferenceVolatility:
    """Compute the exact causal trailing true-range mean for one issuance.

    The caller supplies exactly ``lookback + 1`` native bars.  Requiring the
    exact suffix at this boundary prevents an accidental future or gapped
    prefix from being silently trimmed into an apparently valid receipt.
    """

    if source_timeframe not in TIMEFRAME_DURATIONS:
        raise ValueError("source_timeframe must be a supported timeframe")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback <= 0:
        raise ValueError("lookback must be a positive integer")
    require_utc(issuance_cutoff, field_name="issuance_cutoff")
    values = tuple(bars)
    if len(values) != lookback + 1:
        raise ValueError("reference volatility requires exactly N+1 source bars")
    if any(not isinstance(bar, SRBar) for bar in values):
        raise TypeError("reference volatility bars must contain only SRBar values")
    if any(bar.timeframe != source_timeframe for bar in values):
        raise ValueError("reference volatility source timeframe mismatch")
    if values[-1].bar_close_at != issuance_cutoff:
        raise ValueError("reference volatility final bar must close at issuance")
    grid = grid_for(source_timeframe)
    grid.validate_contiguous(
        tuple(bar.bar_open_at for bar in values),
        tuple(bar.bar_close_at for bar in values),
    )
    if any(not _is_aligned(bar, grid) for bar in values):
        raise ValueError("reference volatility bars must be closed UTC-grid bars")
    true_ranges = tuple(
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in pairwise(values)
    )
    value = sum(true_ranges, Decimal(0)) / Decimal(lookback)
    _validate_threshold(value, "reference volatility value")
    return TargetReferenceVolatility(
        algorithm_id=REFERENCE_VOLATILITY_ID,
        lookback=lookback,
        source_timeframe=source_timeframe,
        issuance_cutoff=issuance_cutoff,
        source_bar_identities=tuple(bar.identity for bar in values),
        value=value,
        source_fingerprint=canonical_hash(
            {
                "algorithm_id": REFERENCE_VOLATILITY_ID,
                "source_timeframe": source_timeframe,
                "issuance_cutoff": issuance_cutoff,
                "bars": tuple(bar for bar in values),
            }
        ),
    )


def _scientific_window(
    future_bars: Sequence[SRBar],
    *,
    issued_at: datetime,
    observation_end_at: datetime,
    observation_timeframe: str,
    observation_duration: timedelta,
) -> Sequence[SRBar]:
    """Return the contiguous future prefix without healing a gap."""

    grid = _observation_grid(observation_timeframe, observation_duration)
    if isinstance(future_bars, _IndexedSequence):
        values: Sequence[SRBar] = future_bars
        if any(not isinstance(bar, SRBar) for bar in values):
            raise TypeError("future_bars must contain only SRBar values")
        if not values:
            return values
        if values[0].bar_open_at != issued_at:
            return ()
        if any(not _is_aligned(bar, grid) for bar in values):
            return ()
        if any(
            current.bar_open_at != previous.bar_close_at
            or current.bar_close_at <= previous.bar_close_at
            for previous, current in pairwise(values)
        ):
            return ()
        if values[-1].bar_close_at > observation_end_at:
            return ()
        return values
    values = tuple(future_bars)
    if any(not isinstance(bar, SRBar) for bar in values):
        raise TypeError("future_bars must contain only SRBar values")
    selected = tuple(
        bar
        for bar in values
        if bar.bar_close_at > issued_at and bar.bar_close_at <= observation_end_at
    )
    usable: list[SRBar] = []
    previous: SRBar | None = None
    for bar in selected:
        if not _is_aligned(bar, grid):
            break
        if previous is None:
            if bar.bar_open_at != issued_at:
                break
        elif (
            bar.bar_open_at != previous.bar_close_at
            or bar.bar_close_at <= previous.bar_close_at
        ):
            break
        usable.append(bar)
        previous = bar
    return tuple(usable)


def _scientific_event(
    zone: ZoneLineage,
    *,
    spec: ResolvedTargetSpec,
    reference: TargetReferenceVolatility,
    bars: Sequence[SRBar],
    issued_at: datetime,
) -> tuple[TargetObservation, TwoStageTargetView]:
    distance = spec.barrier_multiplier * reference.value
    favorable_barrier = (
        zone.upper + distance
        if zone.side is ZoneSide.SUPPORT
        else zone.lower - distance
    )
    adverse_barrier = (
        zone.lower - distance
        if zone.side is ZoneSide.SUPPORT
        else zone.upper + distance
    )
    touch_at: datetime | None = None
    reaction: ScientificReaction | None = None
    reaction_at: datetime | None = None
    ambiguous = False
    touched = False
    favorable_excursion = Decimal(0)
    adverse_excursion = Decimal(0)
    for bar in bars:
        overlaps = _overlap(zone, bar)
        if not touched:
            if not overlaps:
                continue
            touched = True
            touch_at = bar.bar_close_at
            hit_favorable = (
                bar.high >= favorable_barrier
                if zone.side is ZoneSide.SUPPORT
                else bar.low <= favorable_barrier
            )
            hit_adverse = (
                bar.low <= adverse_barrier
                if zone.side is ZoneSide.SUPPORT
                else bar.high >= adverse_barrier
            )
            if hit_favorable or hit_adverse:
                ambiguous = True
                break
            continue

        favorable_excursion = max(
            favorable_excursion,
            (bar.high - zone.upper) / reference.value
            if zone.side is ZoneSide.SUPPORT
            else (zone.lower - bar.low) / reference.value,
        )
        adverse_excursion = max(
            adverse_excursion,
            (zone.lower - bar.low) / reference.value
            if zone.side is ZoneSide.SUPPORT
            else (bar.high - zone.upper) / reference.value,
        )
        hit_favorable = (
            bar.high >= favorable_barrier
            if zone.side is ZoneSide.SUPPORT
            else bar.low <= favorable_barrier
        )
        hit_adverse = (
            bar.low <= adverse_barrier
            if zone.side is ZoneSide.SUPPORT
            else bar.high >= adverse_barrier
        )
        if hit_favorable and hit_adverse:
            ambiguous = True
            break
        if hit_favorable:
            reaction = ScientificReaction.BOUNCE
            reaction_at = bar.bar_close_at
            break
        if hit_adverse:
            reaction = ScientificReaction.BREAK
            reaction_at = bar.bar_close_at
            break

    # ``_scientific_window`` guarantees the first bar opens at issuance; the
    # explicit cutoff keeps this helper safe when called with an empty prefix.
    complete = bool(bars) and bars[-1].bar_close_at == issued_at + spec.horizon
    if reaction is not None and not ambiguous:
        touch = True
        censored = False
        eligible = True
    elif touched:
        touch = True
        censored = not complete
        eligible = False
    elif complete:
        touch = False
        censored = False
        eligible = False
    else:
        touch = None
        censored = True
        eligible = False
    view = TwoStageTargetView(
        touch=touch,
        reaction=(None if ambiguous else reaction),
        reaction_eligible=eligible,
        censored=censored,
        ambiguous=ambiguous,
        touch_at=touch_at,
        reaction_at=(None if ambiguous else reaction_at),
    )
    outcome = ForecastOutcome.NO_TOUCH
    if touch is True:
        if view.reaction is ScientificReaction.BOUNCE:
            outcome = ForecastOutcome.TOUCH_THEN_BOUNCE
        elif view.reaction is ScientificReaction.BREAK:
            outcome = ForecastOutcome.TOUCH_THEN_BREAK
        else:
            outcome = ForecastOutcome.TOUCH_UNRESOLVED
    elif touch is None:
        outcome = ForecastOutcome.TOUCH_UNRESOLVED
    event = TargetObservation(
        zone_id=zone.zone_id,
        horizon=spec.horizon,
        issued_at=issued_at,
        observation_end_at=issued_at + spec.horizon,
        last_observed_cutoff=(bars[-1].bar_close_at if bars else None),
        complete=complete,
        outcome=outcome,
        touch_at=touch_at,
        censored=censored,
        ambiguous=ambiguous,
        favorable_excursion_atr=max(Decimal(0), favorable_excursion),
        adverse_excursion_atr=max(Decimal(0), adverse_excursion),
    )
    return event, view


def label_scientific_target(
    zone: ZoneLineage,
    *,
    issued_at: datetime,
    future_bars: Sequence[SRBar],
    target_spec: ResolvedTargetSpec,
    reference_bars: Sequence[SRBar] | None = None,
) -> ScientificTargetResult:
    """Label one candidate-independent two-stage target causally."""

    if not isinstance(zone, ZoneLineage):
        raise TypeError("zone must be ZoneLineage")
    if not isinstance(target_spec, ResolvedTargetSpec):
        raise TypeError("target_spec must be ResolvedTargetSpec")
    require_utc(issued_at, field_name="issued_at")
    if issued_at < zone.available_at:
        raise ValueError("issued_at cannot precede zone availability")
    if target_spec.source_timeframe != zone.source_timeframe:
        raise ValueError("target source timeframe must equal zone source timeframe")
    if reference_bars is None:
        raise ValueError("exact reference_bars are required")
    reference = compute_target_reference_volatility(
        reference_bars,
        source_timeframe=target_spec.source_timeframe,
        issuance_cutoff=issued_at,
        lookback=target_spec.reference_lookback,
    )
    bars = _scientific_window(
        future_bars,
        issued_at=issued_at,
        observation_end_at=issued_at + target_spec.horizon,
        observation_timeframe=target_spec.observation_timeframe,
        observation_duration=target_spec.observation_duration,
    )
    if any(bar.bar_open_at < issued_at for bar in bars):
        raise ValueError("future bars must not include formation evidence")
    event, view = _scientific_event(
        zone,
        spec=target_spec,
        reference=reference,
        bars=bars,
        issued_at=issued_at,
    )
    return ScientificTargetResult(
        zone_id=zone.zone_id,
        horizon=target_spec.horizon,
        issued_at=issued_at,
        observation_end_at=issued_at + target_spec.horizon,
        last_observed_cutoff=(bars[-1].bar_close_at if bars else None),
        complete=event.complete,
        view=view,
        target_reference_volatility=reference,
        event_observation=event,
    )


def label_scientific_target_indexed(
    zone: ZoneLineage,
    *,
    issued_at: datetime,
    future_bars: Sequence[SRBar],
    future_start_index: int,
    future_end_index: int,
    target_spec: ResolvedTargetSpec,
    reference_bars: Sequence[SRBar],
) -> ScientificTargetResult:
    """Label a shared-bar interval without copying its future sequence.

    ``future_start_index`` and ``future_end_index`` identify a half-open
    interval in the caller-owned bar sequence.  The normal sequence labeler
    remains the semantic authority; its indexed window path validates the
    shared interval in place.
    """

    if isinstance(future_start_index, bool) or not isinstance(future_start_index, int):
        raise TypeError("future_start_index must be an integer")
    if isinstance(future_end_index, bool) or not isinstance(future_end_index, int):
        raise TypeError("future_end_index must be an integer")
    if future_start_index < 0 or future_end_index < future_start_index:
        raise ValueError("future index interval is invalid")
    if future_end_index > len(future_bars):
        raise ValueError("future index interval exceeds shared bars")
    return label_scientific_target(
        zone,
        issued_at=issued_at,
        future_bars=_IndexedSequence(future_bars, future_start_index, future_end_index),
        target_spec=target_spec,
        reference_bars=reference_bars,
    )


def scientific_target_fingerprint(spec: ResolvedTargetSpec) -> str:
    """Return the immutable semantic identity of the scientific target rules."""

    if not isinstance(spec, ResolvedTargetSpec):
        raise TypeError("scientific target fingerprint requires ResolvedTargetSpec")
    return canonical_hash(
        {
            "schema": SCIENTIFIC_TARGET_SCHEMA,
            "reference_volatility": REFERENCE_VOLATILITY_ID,
            "source_timeframe": spec.source_timeframe,
            "source_horizon_bars": spec.source_horizon_bars,
            "reference_lookback": spec.reference_lookback,
            "barrier_multiplier": spec.barrier_multiplier,
            "observation_timeframe": spec.observation_timeframe,
            "observation_duration": spec.observation_duration,
            "semantics": {
                "touch": "first overlap; first-touch candle cannot establish ordered reaction",
                "reaction": "symmetric barriers; later same-bar dual passage is ambiguous",
                "censoring": "leading_or_later_gap_and_unresolved_horizon_are_censored",
                "candidate_independence": "creation_atr_and_lifecycle_rules_excluded",
            },
        }
    )


__all__ = [
    "REFERENCE_VOLATILITY_ID",
    "SCIENTIFIC_TARGET_SCHEMA",
    "TARGET_SCHEMA",
    "ResolvedTargetSpec",
    "ScientificReaction",
    "ScientificTargetResult",
    "TargetObservation",
    "TargetReferenceVolatility",
    "TwoStageTargetView",
    "compute_target_reference_volatility",
    "label_forecast",
    "label_scientific_target",
    "label_scientific_target_indexed",
    "resolve_target_spec",
    "scientific_target_fingerprint",
    "target_fingerprint",
]
