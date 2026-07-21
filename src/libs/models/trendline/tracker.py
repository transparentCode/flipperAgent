"""Transitional forwarding path for the family tracking service."""

from .tracking.service import TrendlineFamilyTracker, TrendlineFamilyUpdateError

__all__ = ["TrendlineFamilyTracker", "TrendlineFamilyUpdateError"]
