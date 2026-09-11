"""Typed retention and temporal-context policy for snapshot history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


SnapshotKey = tuple[str, str]
_HISTORY_FIELDS = frozenset(
    {
        "max_logical_snapshots_per_key",
        "max_revisions_per_snapshot",
        "context_limit",
    }
)


class SnapshotHistoryConfigError(ValueError):
    """Raised when snapshot-history policy configuration is invalid."""


def _validate_capacity(name: str, value: int | None, *, allow_none: bool) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SnapshotHistoryConfigError(f"{name} must be an integer >= 1")
    return int(value)


def _validate_fields(raw: Mapping[str, Any]) -> None:
    unknown = sorted(set(raw) - _HISTORY_FIELDS)
    if unknown:
        raise SnapshotHistoryConfigError(
            f"unknown history fields: {', '.join(str(item) for item in unknown)}"
        )


@dataclass(frozen=True)
class SnapshotHistoryPolicy:
    """Resolved storage and query limits for one asset/timeframe key."""

    max_logical_snapshots_per_key: int
    max_revisions_per_snapshot: int
    context_limit: int

    def __post_init__(self) -> None:
        for name in _HISTORY_FIELDS:
            _validate_capacity(name, getattr(self, name), allow_none=False)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SnapshotHistoryPolicy":
        if not isinstance(raw, Mapping):
            raise SnapshotHistoryConfigError("history must be a mapping")
        _validate_fields(raw)
        missing = sorted(_HISTORY_FIELDS - set(raw))
        if missing:
            raise SnapshotHistoryConfigError(
                f"history is missing fields: {', '.join(missing)}"
            )
        return cls(
            max_logical_snapshots_per_key=raw["max_logical_snapshots_per_key"],
            max_revisions_per_snapshot=raw["max_revisions_per_snapshot"],
            context_limit=raw["context_limit"],
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_logical_snapshots_per_key": self.max_logical_snapshots_per_key,
            "max_revisions_per_snapshot": self.max_revisions_per_snapshot,
            "context_limit": self.context_limit,
        }


@dataclass(frozen=True)
class SnapshotHistoryOverride:
    """Optional policy overrides for one asset/timeframe pair."""

    max_logical_snapshots_per_key: int | None = None
    max_revisions_per_snapshot: int | None = None
    context_limit: int | None = None

    def __post_init__(self) -> None:
        for name in _HISTORY_FIELDS:
            _validate_capacity(name, getattr(self, name), allow_none=True)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SnapshotHistoryOverride":
        if not isinstance(raw, Mapping):
            raise SnapshotHistoryConfigError("asset/timeframe history must be a mapping")
        _validate_fields(raw)
        return cls(**{name: raw.get(name) for name in _HISTORY_FIELDS})

    def apply(self, policy: SnapshotHistoryPolicy) -> SnapshotHistoryPolicy:
        return SnapshotHistoryPolicy(
            max_logical_snapshots_per_key=(
                self.max_logical_snapshots_per_key
                if self.max_logical_snapshots_per_key is not None
                else policy.max_logical_snapshots_per_key
            ),
            max_revisions_per_snapshot=(
                self.max_revisions_per_snapshot
                if self.max_revisions_per_snapshot is not None
                else policy.max_revisions_per_snapshot
            ),
            context_limit=(
                self.context_limit
                if self.context_limit is not None
                else policy.context_limit
            ),
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "max_logical_snapshots_per_key": self.max_logical_snapshots_per_key,
            "max_revisions_per_snapshot": self.max_revisions_per_snapshot,
            "context_limit": self.context_limit,
        }


@dataclass(frozen=True)
class SnapshotHistoryPolicies:
    """Immutable global plus resolved per-key history policies."""

    global_policy: SnapshotHistoryPolicy
    overrides: Mapping[SnapshotKey, SnapshotHistoryPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.global_policy, SnapshotHistoryPolicy):
            raise TypeError("global_policy must be a SnapshotHistoryPolicy")
        normalized: dict[SnapshotKey, SnapshotHistoryPolicy] = {}
        for key, policy in dict(self.overrides).items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise SnapshotHistoryConfigError("history override keys must be (asset, timeframe)")
            if not isinstance(policy, SnapshotHistoryPolicy):
                raise TypeError("history overrides must contain SnapshotHistoryPolicy values")
            normalized[(str(key[0]).upper(), str(key[1]))] = policy
        object.__setattr__(self, "overrides", MappingProxyType(normalized))

    @classmethod
    def from_config(cls, config: Any) -> "SnapshotHistoryPolicies":
        global_policy = getattr(config, "history", None)
        if not isinstance(global_policy, SnapshotHistoryPolicy):
            raise SnapshotHistoryConfigError(
                "trendline history policy is required; configure the YAML history block"
            )
        overrides: dict[SnapshotKey, SnapshotHistoryPolicy] = {}
        for asset, asset_config in getattr(config, "assets", {}).items():
            for timeframe, timeframe_config in getattr(asset_config, "timeframes", {}).items():
                override = getattr(timeframe_config, "history", None)
                if override is not None:
                    if not isinstance(override, SnapshotHistoryOverride):
                        raise TypeError("asset/timeframe history must be a SnapshotHistoryOverride")
                    key = (str(asset).upper(), str(timeframe))
                    overrides[key] = override.apply(global_policy)
        return cls(global_policy=global_policy, overrides=overrides)

    def resolve(self, asset: str, timeframe: str) -> SnapshotHistoryPolicy:
        return self.overrides.get((str(asset).upper(), str(timeframe)), self.global_policy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "global": self.global_policy.to_dict(),
            "overrides": {
                f"{asset}:{timeframe}": policy.to_dict()
                for (asset, timeframe), policy in sorted(self.overrides.items())
            },
        }


def resolve_snapshot_history_policies(config: Any) -> SnapshotHistoryPolicies:
    """Build immutable global and per-key policies from typed config."""

    return SnapshotHistoryPolicies.from_config(config)


def resolve_snapshot_history_policy(
    config: Any,
    asset: str,
    timeframe: str,
) -> SnapshotHistoryPolicy:
    """Resolve one asset/timeframe policy without requiring market data."""

    return resolve_snapshot_history_policies(config).resolve(asset, timeframe)


__all__ = [
    "SnapshotHistoryConfigError",
    "SnapshotHistoryOverride",
    "SnapshotHistoryPolicies",
    "SnapshotHistoryPolicy",
    "SnapshotKey",
    "resolve_snapshot_history_policies",
    "resolve_snapshot_history_policy",
]
