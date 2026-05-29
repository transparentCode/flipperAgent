"""Backward-compatibility shim — real implementation moved to scorer.py."""
# ruff: noqa: F401
import warnings as _warnings

_warnings.warn(
    "libs.models.squeeze_breakout.scoring_model is deprecated. "
    "Import from libs.models.squeeze_breakout.scorer instead.",
    DeprecationWarning,
    stacklevel=2,
)

from libs.models.squeeze_breakout.scorer import SqueezeBreakoutScorer  # noqa: F401
