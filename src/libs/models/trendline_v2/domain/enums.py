"""Closed domain enumerations."""

from enum import Enum


class LineRole(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


class DiscoveryStatus(str, Enum):
    VALID = "valid"
    ABSTAINED = "abstained"
    FAILED = "failed"


class AbstentionReason(str, Enum):
    INSUFFICIENT_DATA = "insufficient_data"
    NO_CANDIDATES = "no_candidates"
    INVALID_INPUT = "invalid_input"
    CONFIGURATION_ERROR = "configuration_error"
    PROVIDER_FAILURE = "provider_failure"


__all__ = ["AbstentionReason", "DiscoveryStatus", "LineRole"]
