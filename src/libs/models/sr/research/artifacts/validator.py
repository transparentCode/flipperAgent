"""Strict JSON decoding for immutable research artifacts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError

from .path_safety import require_regular_file


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _require_finite(value: Any, *, description: str, path: str = "json") -> None:
    if type(value) is float and not math.isfinite(value):
        raise ContractValidationError(f"non-finite {description} value at {path}")
    if type(value) is dict:
        for key, item in value.items():
            _require_finite(item, description=description, path=f"{path}.{key}")
    elif type(value) is list:
        for index, item in enumerate(value):
            _require_finite(item, description=description, path=f"{path}[{index}]")


def load_strict_json(
    path: str | Path,
    *,
    description: str,
    value_description: str | None = None,
    require_regular: bool = True,
) -> Any:
    """Load JSON while rejecting duplicate keys and non-finite values.

    ``description`` is retained verbatim in caller-facing parse errors.  A
    distinct ``value_description`` supports historical callers whose value
    validation context predates their JSON-file description.
    """

    artifact_path = Path(path)
    if require_regular:
        require_regular_file(artifact_path, description=description)
    try:
        payload = json.loads(
            artifact_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid {description}: {path}") from exc
    _require_finite(payload, description=value_description or description)
    return payload


__all__ = ["load_strict_json"]
