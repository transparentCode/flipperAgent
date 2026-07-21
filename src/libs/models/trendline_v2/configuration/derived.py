"""Deterministic protocol derivations with no model defaults."""

from __future__ import annotations

import re

from ..domain.validation import ContractValidationError, require_string

_TIMEFRAME_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>[smhdw])$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def derive_timeframe_duration_seconds(timeframe: str) -> int:
    """Derive duration from an explicit compact timeframe, never infer one."""

    timeframe = require_string(timeframe, field_name="timeframe")
    match = _TIMEFRAME_PATTERN.fullmatch(timeframe)
    if match is None:
        raise ContractValidationError("timeframe must use <positive integer><s|m|h|d|w>")
    return int(match.group("count")) * _SECONDS[match.group("unit")]


__all__ = ["derive_timeframe_duration_seconds"]
