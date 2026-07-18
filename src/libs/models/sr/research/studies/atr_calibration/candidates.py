"""Compatibility exports for the shared causal ATR replay functions."""

from libs.models.sr.research.replay.atr import (
    compute_atr_series,
    replay_candidate,
    replay_candidates,
)


__all__ = ["compute_atr_series", "replay_candidate", "replay_candidates"]
