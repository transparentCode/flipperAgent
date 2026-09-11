"""Optional selection overlays.

Overlays must be disabled by default and must degrade to no-op whenever their
required feature payload is missing or incomplete.
"""

from libs.selection.overlays.regime_v2_trend_gate import (
    apply_regime_v2_trend_gate,
    explain_regime_v2_trend_gate,
    preview_regime_v2_trend_gate,
)

__all__ = [
    "apply_regime_v2_trend_gate",
    "explain_regime_v2_trend_gate",
    "preview_regime_v2_trend_gate",
]
