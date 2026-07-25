"""Quality helpers shared by trendlines-native signals and downstream confluence."""

from __future__ import annotations

from typing import Any, Sequence

from app.trendlines.boundary import BoundaryResult, ConfluenceGateConfig

# ── Hardcoded constants (architecture tier) ──
_PRICE_BLEND_W = 0.5
_AGREEING_BLEND_W = 0.5
_CONF_AGREEMENT_BASE = 0.4
_CONF_AGREEMENT_SCALE = 0.6
_OSC_WEIGHTS = (0.5, 0.25, 0.15, 0.10)


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def touch_count_confidence_factor(
    touch_count: float,
    full_confidence_touches: float,
) -> float:
    if full_confidence_touches <= 0:
        return 0.0
    return clamp_unit(float(touch_count) / float(full_confidence_touches))


def blended_quality_score(
    price_quality: float,
    agreeing_qualities: Sequence[float],
) -> float:
    if not agreeing_qualities:
        return 0.0
    mean_agreeing_quality = sum(agreeing_qualities) / len(agreeing_qualities)
    return clamp_unit(_PRICE_BLEND_W * clamp_unit(price_quality) + _AGREEING_BLEND_W * clamp_unit(mean_agreeing_quality))


def confluence_confidence(
    *,
    gate_config: ConfluenceGateConfig,
    gate_applies: bool,
    agreement_ratio: float,
    quality_score: float,
    agreeing_oscillators: int,
) -> float | None:
    mode = gate_config.operating_mode
    clamped_quality = clamp_unit(quality_score)
    
    base = _CONF_AGREEMENT_BASE
    scale = _CONF_AGREEMENT_SCALE

    if not gate_applies:
        if mode == "coarse_gate":
            return clamp_unit(base + scale * agreement_ratio)
        if mode == "soft_weight":
            base_confidence = clamp_unit(base + scale * agreement_ratio)
            return clamp_unit(scale * base_confidence + base * clamped_quality)
        if mode == "score_only":
            return clamped_quality if clamped_quality > 0.0 else None
        raise ValueError(f"Unsupported confluence operating mode: {mode}")

    if agreeing_oscillators < gate_config.min_agreeing_oscillators:
        return None

    if mode == "coarse_gate":
        if agreement_ratio < gate_config.min_agreement_ratio:
            return None
        return clamp_unit(base + scale * agreement_ratio)

    if mode == "soft_weight":
        if agreement_ratio < gate_config.min_agreement_ratio:
            return None
        base_confidence = clamp_unit(base + scale * agreement_ratio)
        return clamp_unit(scale * base_confidence + base * clamped_quality)

    if mode == "score_only":
        return clamped_quality if clamped_quality > 0.0 else None

    raise ValueError(f"Unsupported confluence operating mode: {mode}")


def price_quality_for_direction(result: BoundaryResult, price_dir: float) -> float:
    ray = result.best_support if price_dir > 0 else result.best_resistance
    if ray is None:
        return 0.0
    return float(ray.score)


def oscillator_quality_for_direction(
    osc: dict[str, Any], 
    price_dir: float, 
) -> float:
    if price_dir > 0:
        base_score = float(osc.get("best_support_score", 0.0) or 0.0)
        touch_count = int(osc.get("best_support_touch_count", 0) or 0)
        r_squared = float(osc.get("best_support_r_squared", 0.0) or 0.0)
    else:
        base_score = float(osc.get("best_resistance_score", 0.0) or 0.0)
        touch_count = int(osc.get("best_resistance_touch_count", 0) or 0)
        r_squared = float(osc.get("best_resistance_r_squared", 0.0) or 0.0)

    if not any(
        key in osc
        for key in (
            "best_support_touch_count",
            "best_resistance_touch_count",
            "best_support_r_squared",
            "best_resistance_r_squared",
            "normalized_magnitude",
        )
    ):
        return base_score

    activation = float(osc.get("normalized_magnitude", 0.0) or 0.0)
    touch_component = touch_count_confidence_factor(touch_count - 1.0, 4.0)
    fit_component = clamp_unit(r_squared)
    
    w0, w1, w2, w3 = _OSC_WEIGHTS
    
    blended = (
        w0 * clamp_unit(base_score)
        + w1 * touch_component
        + w2 * fit_component
        + w3 * clamp_unit(activation)
    )
    return clamp_unit(blended)


__all__ = [
    "blended_quality_score",
    "clamp_unit",
    "confluence_confidence",
    "oscillator_quality_for_direction",
    "price_quality_for_direction",
    "touch_count_confidence_factor",
]