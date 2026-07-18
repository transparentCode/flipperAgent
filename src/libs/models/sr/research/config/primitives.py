"""Fail-closed typed parsing primitives for SR research configuration."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import require_utc


_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def require_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    """Require a mapping with exact-string keys."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    expected: Collection[str],
    *,
    path: str,
) -> None:
    """Require exact keys, reporting missing and unknown keys deterministically."""

    actual_keys = set(value)
    expected_keys = set(expected)
    if actual_keys != expected_keys:
        raise ContractValidationError(
            f"{path} keys mismatch; missing={sorted(expected_keys - actual_keys)} "
            f"unknown={sorted(actual_keys - expected_keys)}"
        )


def require_nonempty_string(value: Any, *, path: str) -> str:
    """Require an exact-string value containing non-whitespace content."""

    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def require_integer(
    value: Any,
    *,
    path: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    """Require an exact integer within inclusive bounds."""

    if type(minimum) is not int or (maximum is not None and type(maximum) is not int):
        raise ContractValidationError(f"{path} integer bounds must be exact integers")
    if maximum is not None and minimum > maximum:
        raise ContractValidationError(f"{path} integer minimum cannot exceed maximum")
    if type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractValidationError(f"{path} must be an integer <= {maximum}")
    return value


def _finite_bound(value: float | int, *, path: str, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} {name} must be numeric")
    try:
        bound = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} {name} must be finite") from exc
    if not math.isfinite(bound):
        raise ContractValidationError(f"{path} {name} must be finite")
    return bound


def require_finite_number(
    value: Any,
    *,
    path: str,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
) -> float:
    """Require a finite numeric value within inclusive bounds."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    lower = _finite_bound(minimum, path=path, name="minimum") if minimum is not None else None
    upper = _finite_bound(maximum, path=path, name="maximum") if maximum is not None else None
    if lower is not None and upper is not None and lower > upper:
        raise ContractValidationError(f"{path} numeric minimum cannot exceed maximum")
    if lower is not None and result < lower:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    if upper is not None and result > upper:
        raise ContractValidationError(f"{path} must be <= {maximum}")
    return 0.0 if result == 0.0 else result


def require_sha256(value: Any, *, path: str) -> str:
    """Require an exact lowercase SHA-256 hexadecimal digest."""

    digest = require_nonempty_string(value, path=path)
    if _SHA256.fullmatch(digest) is None:
        raise ContractValidationError(f"{path} must be a lowercase SHA-256 hex string")
    return digest


def require_git_commit(value: Any, *, path: str) -> str:
    """Require an exact lowercase SHA-1 or SHA-256 Git object identity."""

    commit = require_nonempty_string(value, path=path)
    if _GIT_COMMIT.fullmatch(commit) is None:
        raise ContractValidationError(f"{path} must be a git SHA")
    return commit


def require_safe_relative_path(value: Any, *, path: str) -> str:
    """Require a non-traversing repository-relative path without rewriting it."""

    relative_path = require_nonempty_string(value, path=path)
    posix_path = PurePosixPath(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if (
        "\x00" in relative_path
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise ContractValidationError(f"{path} must be a safe relative path")
    return relative_path


def require_utc_timestamp(
    value: Any,
    *,
    path: str,
    require_daily_boundary: bool = False,
) -> datetime:
    """Require strict trailing-Z UTC timestamp text and return aware UTC time."""

    timestamp = require_nonempty_string(value, path=path)
    if not timestamp.endswith("Z"):
        raise ContractValidationError(f"{path} must use strict UTC Z notation")
    try:
        parsed = require_utc(
            datetime.fromisoformat(timestamp[:-1] + "+00:00"),
            field_name=path,
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be a valid UTC timestamp") from exc
    if require_daily_boundary and (
        parsed.hour or parsed.minute or parsed.second or parsed.microsecond
    ):
        raise ContractValidationError(f"{path} must align to a UTC daily boundary")
    return parsed


__all__ = [
    "require_exact_keys",
    "require_finite_number",
    "require_git_commit",
    "require_integer",
    "require_mapping",
    "require_nonempty_string",
    "require_safe_relative_path",
    "require_sha256",
    "require_utc_timestamp",
]
