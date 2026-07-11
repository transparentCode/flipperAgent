"""Shared playbook/expert metadata for RegimeProbV1 routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from libs.models.regime_prob_v1.edge.labels import playbook_score_column as _edge_playbook_score_column

PLAYBOOKS: tuple[str, ...] = (
    "trend_following",
    "breakout",
    "mean_reversion",
    "scalping",
    "countertrend",
)

_PLAYBOOK_ALLOW_COLUMNS = {
    "trend_following": "policy_allow_trend_following",
    "breakout": "policy_allow_breakout",
    "mean_reversion": "policy_allow_mean_reversion",
    "scalping": "policy_allow_scalping",
    "countertrend": "policy_allow_countertrend",
}


def playbook_allow_column(playbook: str) -> str:
    normalized = _normalize_playbook(playbook)
    return _PLAYBOOK_ALLOW_COLUMNS[normalized]


def playbook_score_column(playbook: str) -> str:
    return _edge_playbook_score_column(playbook)


def playbook_probability_column(playbook: str, horizon: int) -> str:
    normalized = _normalize_playbook(playbook)
    return f"{normalized}_p_edge_h{int(horizon)}"


def playbook_weight_column(playbook: str) -> str:
    normalized = _normalize_playbook(playbook)
    return f"moe_weight_{normalized}"


def extract_edge_probabilities(row: Mapping[str, Any], *, horizon: int) -> dict[str, float]:
    return {
        playbook: _float(row.get(playbook_probability_column(playbook, horizon)), default=0.0)
        for playbook in PLAYBOOKS
    }


def extract_policy_allows(row: Mapping[str, Any]) -> dict[str, bool]:
    return {
        playbook: bool(row.get(playbook_allow_column(playbook), False))
        for playbook in PLAYBOOKS
    }


def extract_policy_scores(row: Mapping[str, Any]) -> dict[str, float]:
    return {
        playbook: _float(row.get(playbook_score_column(playbook)), default=0.0)
        for playbook in PLAYBOOKS
    }


def _normalize_playbook(playbook: str) -> str:
    normalized = str(playbook).strip().lower()
    if normalized not in PLAYBOOKS:
        raise KeyError(f"Unsupported playbook: {playbook}")
    return normalized


def _float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if number == number else float(default)


__all__ = [
    "PLAYBOOKS",
    "extract_edge_probabilities",
    "extract_policy_allows",
    "extract_policy_scores",
    "playbook_allow_column",
    "playbook_probability_column",
    "playbook_score_column",
    "playbook_weight_column",
]
