"""Disabled-by-default paper guardrail for one PriceAction asset candidate.

Phase 6I found a narrow offline candidate: suppress PriceAction direction=1 on
BNBUSDT|1h. This module only previews that suppression and returns a decision;
it never mutates live candidates unless a caller explicitly uses the returned
paper candidates for analysis.
"""

from __future__ import annotations

from typing import Any

from libs.contracts.signal import SelectionCandidate

_DEFAULT_MODEL = "PriceAction"
_DEFAULT_ASSET = "BNBUSDT"
_DEFAULT_TIMEFRAME = "1h"
_DEFAULT_DIRECTION = 1


def preview_pa_asset_paper_guardrail(
    candidates: list[SelectionCandidate],
    config: dict[str, Any],
) -> tuple[list[SelectionCandidate], dict[str, Any]]:
    """Preview a narrow PriceAction asset guardrail in paper mode only."""
    guardrail = _guardrail_config(config)
    if not bool(guardrail.get("paper_enabled", False)):
        return candidates, _decision(
            active=False,
            reason="paper_disabled",
            candidates=candidates,
            guardrail=guardrail,
            suppressed=[],
        )

    target_model = str(guardrail.get("model_name") or _DEFAULT_MODEL)
    target_asset = str(guardrail.get("asset") or _DEFAULT_ASSET)
    target_timeframe = str(guardrail.get("timeframe") or _DEFAULT_TIMEFRAME)
    target_direction = _int_value(guardrail.get("direction"), _DEFAULT_DIRECTION)
    suppressed = [
        candidate
        for candidate in candidates
        if _matches_candidate(
            candidate,
            model_name=target_model,
            asset=target_asset,
            timeframe=target_timeframe,
            direction=target_direction,
        )
    ]
    if not suppressed:
        return candidates, _decision(
            active=False,
            reason="no_matching_price_action_candidate",
            candidates=candidates,
            guardrail=guardrail,
            suppressed=[],
        )

    paper_candidates = [candidate for candidate in candidates if candidate not in suppressed]
    return paper_candidates, _decision(
        active=True,
        reason="price_action_asset_direction_suppressed",
        candidates=candidates,
        guardrail=guardrail,
        suppressed=suppressed,
    )


def _matches_candidate(
    candidate: SelectionCandidate,
    *,
    model_name: str,
    asset: str,
    timeframe: str,
    direction: int,
) -> bool:
    return (
        candidate.model_name == model_name
        and candidate.asset == asset
        and candidate.timeframe == timeframe
        and int(candidate.direction) == int(direction)
    )


def _decision(
    *,
    active: bool,
    reason: str,
    candidates: list[SelectionCandidate],
    guardrail: dict[str, Any],
    suppressed: list[SelectionCandidate],
) -> dict[str, Any]:
    target_model = str(guardrail.get("model_name") or _DEFAULT_MODEL)
    target_asset = str(guardrail.get("asset") or _DEFAULT_ASSET)
    target_timeframe = str(guardrail.get("timeframe") or _DEFAULT_TIMEFRAME)
    target_direction = _int_value(guardrail.get("direction"), _DEFAULT_DIRECTION)
    return {
        "paper_enabled": bool(guardrail.get("paper_enabled", False)),
        "active": bool(active),
        "reason": reason,
        "target_model": target_model,
        "target_asset": target_asset,
        "target_timeframe": target_timeframe,
        "target_direction": target_direction,
        "candidate_count": len(candidates),
        "suppressed_count": len(suppressed),
        "suppressed_models": [candidate.model_name for candidate in suppressed],
        "suppressed_edge_scores": [float(candidate.edge_score) for candidate in suppressed],
        "suppressed_convictions": [float(candidate.conviction) for candidate in suppressed],
    }


def _guardrail_config(config: dict[str, Any]) -> dict[str, Any]:
    overlays = config.get("overlays", {})
    if not isinstance(overlays, dict):
        return {}
    guardrail = overlays.get("regime_v2_pa_asset_guardrail", {})
    return guardrail if isinstance(guardrail, dict) else {}


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


__all__ = ["preview_pa_asset_paper_guardrail"]
