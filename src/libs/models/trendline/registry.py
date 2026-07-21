"""Transitional forwarding path for complete provider registration."""

from .discovery.registry import fitter_names, get_line_provider, line_provider_names, pivot_provider_names

__all__ = ["fitter_names", "get_line_provider", "line_provider_names", "pivot_provider_names"]
