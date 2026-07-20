"""Identity-bearing domain entities re-exported from canonical contracts."""

from __future__ import annotations

from ..contracts import TrendlineFamilyState

# Published family state already carries stable identity and invariant metadata.
# A second family DTO would duplicate tracker state and break type identity.
TrendlineFamily = TrendlineFamilyState

__all__ = ["TrendlineFamily"]
