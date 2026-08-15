"""Deterministic identity and configuration fingerprint helpers for D1."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import Any

from libs.contracts.decision import require_utc


def canonicalize(value: Any) -> Any:
    """Convert supported configuration values into deterministic JSON values."""

    return _canonicalize(value, path="$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_fingerprint(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def binding_config_fingerprint(
    parameters: Mapping[str, Any],
    runtime_binding: Mapping[str, Any] | None = None,
) -> str:
    """Fingerprint binding parameters plus effective runtime binding values."""

    return sha256_fingerprint(
        {
            "parameters": parameters,
            "runtime_binding": runtime_binding or {},
        }
    )


def make_binding_id(
    *,
    lane_id: str,
    slot_name: str,
    plugin_name: str,
    plugin_version: str,
    binding_fingerprint: str,
) -> str:
    """Build a readable deterministic binding identity."""

    _require_text(lane_id, "lane_id")
    _require_text(slot_name, "slot_name")
    _require_text(plugin_name, "plugin_name")
    _require_text(plugin_version, "plugin_version")
    _require_text(binding_fingerprint, "binding_fingerprint")
    return f"{lane_id}:{slot_name}:{plugin_name}@{plugin_version}:{binding_fingerprint}"


def effective_lane_revision(
    lane_id: str,
    lane_configuration: Mapping[str, Any],
    policy_configuration: Mapping[str, Any],
) -> str:
    """Fingerprint the effective lane and its policy configuration."""

    _require_text(lane_id, "lane_id")
    return sha256_fingerprint(
        {
            "lane_id": lane_id,
            "lane_configuration": lane_configuration,
            "policy_configuration": policy_configuration,
        }
    )


def decision_id(
    *,
    lane_id: str,
    lane_revision: str,
    market_as_of: datetime,
) -> str:
    """Build one deterministic authoritative lane/as-of identity."""

    _require_text(lane_id, "lane_id")
    _require_text(lane_revision, "lane_revision")
    require_utc(market_as_of, field_name="market_as_of")
    return f"{lane_id}:{lane_revision}:{_canonical_datetime(market_as_of)}"


def compute_decision_execution_revision(
    *,
    lane_id: str,
    base_lane_revision: str,
    feature_plan_fingerprint: str,
    data_plan_fingerprint: str,
    policy_name: str,
    policy_version: str,
    policy_parameters: Mapping[str, Any],
) -> str:
    """Fingerprint all material D8 execution semantics for one lane."""

    for field_name, value in (
        ("lane_id", lane_id),
        ("base_lane_revision", base_lane_revision),
        ("feature_plan_fingerprint", feature_plan_fingerprint),
        ("data_plan_fingerprint", data_plan_fingerprint),
        ("policy_name", policy_name),
        ("policy_version", policy_version),
    ):
        _require_text(value, field_name)
    return sha256_fingerprint(
        {
            "lane_id": lane_id,
            "base_lane_revision": base_lane_revision,
            "feature_plan_fingerprint": feature_plan_fingerprint,
            "data_plan_fingerprint": data_plan_fingerprint,
            "policy": {
                "name": policy_name,
                "version": policy_version,
                "parameters": policy_parameters,
            },
        }
    )


def _canonicalize(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"non-finite float is not supported at {path}")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"non-finite Decimal is not supported at {path}")
        return {"__decimal__": str(value.normalize())}
    if isinstance(value, datetime):
        require_utc(value, field_name=path)
        return {"__datetime__": _canonical_datetime(value)}
    if isinstance(value, timedelta):
        return {
            "__timedelta_us__": value.days * 86_400_000_000
            + value.seconds * 1_000_000
            + value.microseconds
        }
    if isinstance(value, Enum):
        return {
            "__enum__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonicalize(value.value, path=path),
        }
    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be strings at {path}")
            items[key] = _canonicalize(item, path=f"{path}.{key}")
        return items
    if isinstance(value, (list, tuple)):
        return [
            _canonicalize(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        raise TypeError(f"unordered sets are not supported at {path}")
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": {
                item.name: _canonicalize(
                    getattr(value, item.name), path=f"{path}.{item.name}"
                )
                for item in fields(value)
            },
        }
    raise TypeError(f"unsupported identity value at {path}: {type(value).__name__}")


def _canonical_datetime(value: datetime) -> str:
    require_utc(value, field_name="datetime")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")


__all__ = [
    "binding_config_fingerprint",
    "canonical_json_bytes",
    "canonicalize",
    "compute_decision_execution_revision",
    "decision_id",
    "effective_lane_revision",
    "make_binding_id",
    "sha256_fingerprint",
]
