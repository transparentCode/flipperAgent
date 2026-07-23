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
    HYPOTHESIS_LIMIT_EXCEEDED = "hypothesis_limit_exceeded"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    PROVIDER_FAILURE = "provider_failure"


__all__ = ["AbstentionReason", "DiscoveryStatus", "LineRole"]
