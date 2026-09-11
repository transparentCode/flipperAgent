"""Canonical SR domain contract errors."""

from __future__ import annotations


class ContractValidationError(ValueError):
    """Raised when an SR contract invariant is violated."""


__all__ = ["ContractValidationError"]
