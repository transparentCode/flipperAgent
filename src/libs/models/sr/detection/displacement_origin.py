"""Pure causal displacement-origin candidate detection for SR-V2.0."""

from __future__ import annotations

from dataclasses import dataclass
import math

from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.candidates import CandidateLevel
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.geometry import ZoneGeometry
from libs.models.sr.domain.identity import require_utc
from libs.models.sr.domain.zones import ZoneSide


_SOURCE = "displacement_origin_v2"


@dataclass(frozen=True)
class DisplacementOriginConfig:
    """The four explicitly supplied SR-V2.0 displacement parameters."""

    displacement_atr: float
    minimum_body_fraction: float
    structure_lookback_bars: int
    base_search_bars: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "displacement_atr",
            _finite_positive(self.displacement_atr, field_name="displacement_atr"),
        )
        minimum_body_fraction = _finite_positive(
            self.minimum_body_fraction,
            field_name="minimum_body_fraction",
        )
        if minimum_body_fraction > 1.0:
            raise ContractValidationError("minimum_body_fraction must be at most 1.0")
        object.__setattr__(self, "minimum_body_fraction", minimum_body_fraction)
        object.__setattr__(
            self,
            "structure_lookback_bars",
            _positive_integer(
                self.structure_lookback_bars,
                field_name="structure_lookback_bars",
            ),
        )
        object.__setattr__(
            self,
            "base_search_bars",
            _positive_integer(self.base_search_bars, field_name="base_search_bars"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "displacement_atr": self.displacement_atr,
            "minimum_body_fraction": self.minimum_body_fraction,
            "structure_lookback_bars": self.structure_lookback_bars,
            "base_search_bars": self.base_search_bars,
        }


def _finite_positive(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{field_name} must be finite")
    if number <= 0.0:
        raise ContractValidationError(f"{field_name} must be positive")
    return 0.0 if number == 0.0 else number


def _positive_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value <= 0:
        raise ContractValidationError(f"{field_name} must be positive")
    return value


def _finite_bar_value(bar: ClosedBar, *, field_name: str) -> float:
    value = getattr(bar, field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{field_name} must be finite")
    return number


def _validate_bars(bars: tuple[ClosedBar, ...]) -> None:
    if type(bars) is not tuple:
        raise ContractValidationError("bars must be exactly a tuple")
    if not bars:
        return
    if type(bars[0]) is not ClosedBar:
        raise ContractValidationError("bars[0] must be exactly ClosedBar")

    state_key = bars[0].state_key
    seen_bar_ids: set[str] = set()
    previous_closed_at = None
    for index, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(f"bars[{index}] must be exactly ClosedBar")
        if bar.state_key != state_key:
            raise ContractValidationError(
                f"bars[{index}].state_key must match displacement window state_key"
            )
        if bar.bar_id in seen_bar_ids:
            raise ContractValidationError(
                f"duplicate bar_id in displacement window: {bar.bar_id}"
            )
        seen_bar_ids.add(bar.bar_id)
        closed_at = require_utc(bar.closed_at, field_name=f"bars[{index}].closed_at")
        if previous_closed_at is not None and bar.closed_at <= previous_closed_at:
            raise ContractValidationError(
                "displacement window timestamps must be strictly increasing"
            )
        previous_closed_at = closed_at
        for field_name in ("open", "high", "low", "close", "atr_at_close"):
            _finite_bar_value(bar, field_name=field_name)


def _opposing_base(
    *,
    bars: tuple[ClosedBar, ...],
    confirmation_index: int,
    side: ZoneSide,
    base_search_bars: int,
) -> ClosedBar | None:
    first_index = max(0, confirmation_index - base_search_bars)
    for base_index in range(confirmation_index - 1, first_index - 1, -1):
        base = bars[base_index]
        if side is ZoneSide.SUPPORT and base.close < base.open:
            return base
        if side is ZoneSide.RESISTANCE and base.close > base.open:
            return base
    return None


def _candidate(
    *,
    base: ClosedBar,
    confirmation: ClosedBar,
    atr_at_creation: float,
    side: ZoneSide,
) -> CandidateLevel | None:
    base_high = _finite_bar_value(base, field_name="high")
    base_low = _finite_bar_value(base, field_name="low")
    if base_high <= base_low:
        return None

    center = (base_high + base_low) / 2.0
    half_width = (base_high - base_low) / 2.0
    if not math.isfinite(center) or not math.isfinite(half_width):
        raise ContractValidationError("displacement base geometry must be finite")
    lower_bound = center - half_width
    upper_bound = center + half_width
    if not math.isfinite(lower_bound) or not math.isfinite(upper_bound):
        raise ContractValidationError("displacement base geometry bounds must be finite")
    geometry = ZoneGeometry(center=center, half_width=half_width)
    return CandidateLevel(
        state_key=base.state_key,
        side=side,
        geometry=geometry,
        source=_SOURCE,
        formed_at=base.closed_at,
        available_at=confirmation.closed_at,
        atr_at_creation=atr_at_creation,
    )


def detect_displacement_origins(
    bars: tuple[ClosedBar, ...],
    config: DisplacementOriginConfig,
) -> tuple[CandidateLevel, ...]:
    """Detect one causal rectangular origin zone for each qualifying close."""
    _validate_bars(bars)
    if type(config) is not DisplacementOriginConfig:
        raise ContractValidationError("config must be exactly DisplacementOriginConfig")
    if len(bars) <= config.structure_lookback_bars:
        return ()

    candidates: list[CandidateLevel] = []
    for confirmation_index in range(config.structure_lookback_bars, len(bars)):
        confirmation = bars[confirmation_index]
        prior_atr = _finite_bar_value(
            bars[confirmation_index - 1], field_name="atr_at_close"
        )
        if prior_atr <= 0.0:
            raise ContractValidationError("prior atr_at_close must be positive")
        high = _finite_bar_value(confirmation, field_name="high")
        low = _finite_bar_value(confirmation, field_name="low")
        open_price = _finite_bar_value(confirmation, field_name="open")
        close = _finite_bar_value(confirmation, field_name="close")
        bar_range = high - low
        if bar_range <= 0.0:
            continue
        body = abs(close - open_price)
        displacement_threshold = config.displacement_atr * prior_atr
        if not math.isfinite(displacement_threshold):
            raise ContractValidationError("displacement threshold must be finite")
        if body < displacement_threshold:
            continue
        if body / bar_range < config.minimum_body_fraction:
            continue

        structure = bars[
            confirmation_index - config.structure_lookback_bars : confirmation_index
        ]
        side: ZoneSide | None = None
        if close > max(_finite_bar_value(bar, field_name="high") for bar in structure):
            side = ZoneSide.SUPPORT
        elif close < min(_finite_bar_value(bar, field_name="low") for bar in structure):
            side = ZoneSide.RESISTANCE
        if side is None:
            continue

        base = _opposing_base(
            bars=bars,
            confirmation_index=confirmation_index,
            side=side,
            base_search_bars=config.base_search_bars,
        )
        if base is None:
            continue
        candidate = _candidate(
            base=base,
            confirmation=confirmation,
            atr_at_creation=prior_atr,
            side=side,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


__all__ = ["DisplacementOriginConfig", "detect_displacement_origins"]
