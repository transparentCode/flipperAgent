"""Shared policy contracts for the trendlines boundary layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TouchDeclusterConfig:
    """Controls how dense touch clusters collapse into effective touches."""

    min_bars_between_touches: int = 0

    def __post_init__(self) -> None:
        if self.min_bars_between_touches < 0:
            raise ValueError("min_bars_between_touches must be >= 0")


@dataclass(frozen=True)
class TouchDiagnostics:
    """Raw versus declustered touch diagnostics for one fitted side."""

    raw_touch_count: int = 0
    effective_touch_count: int = 0
    raw_touch_indices: tuple[int, ...] = field(default_factory=tuple)
    effective_touch_indices: tuple[int, ...] = field(default_factory=tuple)
    min_bars_between_touches: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["raw_touch_indices"] = list(self.raw_touch_indices)
        data["effective_touch_indices"] = list(self.effective_touch_indices)
        return data


@dataclass(frozen=True)
class ConfluenceGateConfig:
    """Side-aware score thresholds for price and oscillator confluence."""

    operating_mode: str = "coarse_gate"
    enabled: bool = False
    apply_to_interactions: tuple[str, ...] = field(default_factory=tuple)
    min_agreement_ratio: float = 0.5
    min_agreeing_oscillators: int = 1
    threshold_mode: str = "absolute"
    min_price_support_score: float = 0.0
    min_price_resistance_score: float = 0.0
    min_osc_support_score: float = 0.0
    min_osc_resistance_score: float = 0.0
    price_support_quantile: float | None = None
    price_resistance_quantile: float | None = None
    osc_support_quantile: float | None = None
    osc_resistance_quantile: float | None = None

    def __post_init__(self) -> None:
        normalized_operating_mode = str(self.operating_mode).lower()
        if normalized_operating_mode not in {"coarse_gate", "soft_weight", "score_only"}:
            raise ValueError(
                "operating_mode must be 'coarse_gate', 'soft_weight', or 'score_only'"
            )
        object.__setattr__(self, "operating_mode", normalized_operating_mode)

        normalized_mode = str(self.threshold_mode).lower()
        if normalized_mode not in {"absolute", "quantile"}:
            raise ValueError("threshold_mode must be 'absolute' or 'quantile'")
        object.__setattr__(self, "threshold_mode", normalized_mode)

        if self.min_agreement_ratio < 0.0 or self.min_agreement_ratio > 1.0:
            raise ValueError("min_agreement_ratio must be between 0 and 1")
        if self.min_agreeing_oscillators < 1:
            raise ValueError("min_agreeing_oscillators must be >= 1")

        for field_name in (
            "min_price_support_score",
            "min_price_resistance_score",
            "min_osc_support_score",
            "min_osc_resistance_score",
        ):
            value = float(getattr(self, field_name))
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")

        for field_name in (
            "price_support_quantile",
            "price_resistance_quantile",
            "osc_support_quantile",
            "osc_resistance_quantile",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            value = float(value)
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")

    def applies_to(self, interaction: str) -> bool:
        if not self.enabled:
            return False
        if not self.apply_to_interactions:
            return True
        return interaction in self.apply_to_interactions

    @property
    def uses_quantile_thresholds(self) -> bool:
        return self.threshold_mode == "quantile"


@dataclass(frozen=True)
class ConfluenceQualitySnapshot:
    """Stable quality payload for one oscillator result."""

    name: str
    interaction: str
    best_support_score: float = 0.0
    best_resistance_score: float = 0.0
    best_support_touch_count: int = 0
    best_resistance_touch_count: int = 0
    best_support_r_squared: float = 0.0
    best_resistance_r_squared: float = 0.0
    current_value: float = 0.0
    neutral_level: float = 0.0
    normalized_magnitude: float = 0.0
    is_valid: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RayTrackerConfig:
    """Matching tolerances for future downstream ray persistence tracking."""

    enabled: bool = False
    slope_tolerance: float = 0.0
    level_distance_atr: float = 0.0
    max_gap_bars: int = 0

    def __post_init__(self) -> None:
        if self.slope_tolerance < 0:
            raise ValueError("slope_tolerance must be >= 0")
        if self.level_distance_atr < 0:
            raise ValueError("level_distance_atr must be >= 0")
        if self.max_gap_bars < 0:
            raise ValueError("max_gap_bars must be >= 0")


@dataclass(frozen=True)
class TrackedRayState:
    """Minimal persistent identity for a ray tracked across bars."""

    ray_id: str
    side: str
    kernel: str
    slope: float
    anchor_price: float
    first_seen_bar: int
    last_seen_bar: int
    age_bars: int
    consecutive_seen_bars: int
    latest_score: float

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = [
    "ConfluenceGateConfig",
    "ConfluenceQualitySnapshot",
    "RayTrackerConfig",
    "TouchDeclusterConfig",
    "TouchDiagnostics",
    "TrackedRayState",
]