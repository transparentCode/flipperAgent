"""Strict research-notebook-only settings.

Model and lifecycle parameters are intentionally absent here; they continue to
come from the canonical SR v2 runtime YAML resolver.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ..config.schema import (
    SRV2ConfigError,
    bounded_int,
    require_exact_keys,
    require_mapping,
)
from ..domain.identity import canonical_hash


class ResearchSourceMode(str):
    CACHE_ONLY = "CACHE_ONLY"
    BINANCE_USDM = "BINANCE_USDM"


class ReplayIdentityMode(str):
    EXACT_CHECKPOINT = "EXACT_CHECKPOINT"
    WINDOW_RELATIVE = "WINDOW_RELATIVE"


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise SRV2ConfigError("research YAML keys must be strings")
        if key in result:
            raise SRV2ConfigError(f"duplicate research YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


DISPLAY_POLICY_KEYS = frozenset(
    {
        "iframe_height",
        "candle_limit",
        "initial_mode",
        "show_zones",
        "show_candidates",
        "show_inspector",
        "show_history",
        "volume_pane_fraction",
        "volume_pane_min_height",
    }
)


def normalize_display_policy(value: object, *, name: str = "display") -> Mapping[str, Any]:
    """Validate and normalize the one viewer display policy contract."""

    display = require_mapping(value, name)
    require_exact_keys(display, set(DISPLAY_POLICY_KEYS), name)
    iframe_height = display["iframe_height"]
    if isinstance(iframe_height, bool) or not isinstance(iframe_height, int) or iframe_height < 240:
        raise SRV2ConfigError(f"{name}.iframe_height must be an integer >= 240")
    candle_limit = bounded_int(
        display["candle_limit"],
        f"{name}.candle_limit",
        minimum=1,
        maximum=100_000,
    )
    initial_mode = display["initial_mode"]
    if initial_mode not in {"formation", "lifecycle"}:
        raise SRV2ConfigError(f"{name}.initial_mode must be formation or lifecycle")
    for field in ("show_zones", "show_candidates", "show_inspector", "show_history"):
        if not isinstance(display[field], bool):
            raise SRV2ConfigError(f"{name}.{field} must be bool")
    try:
        fraction = float(display["volume_pane_fraction"])
    except (TypeError, ValueError) as exc:
        raise SRV2ConfigError(f"{name}.volume_pane_fraction must be numeric") from exc
    if not isfinite(fraction) or not 0.10 <= fraction <= 0.40:
        raise SRV2ConfigError(f"{name}.volume_pane_fraction must be in [0.10, 0.40]")
    min_height = bounded_int(
        display["volume_pane_min_height"],
        f"{name}.volume_pane_min_height",
        minimum=60,
        maximum=500,
    )
    return {
        "iframe_height": iframe_height,
        "candle_limit": candle_limit,
        "initial_mode": initial_mode,
        "show_zones": display["show_zones"],
        "show_candidates": display["show_candidates"],
        "show_inspector": display["show_inspector"],
        "show_history": display["show_history"],
        "volume_pane_fraction": fraction,
        "volume_pane_min_height": min_height,
    }


def _utc(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SRV2ConfigError(f"{name} must be an ISO-8601 UTC datetime") from exc
    else:
        raise SRV2ConfigError(f"{name} must be an ISO-8601 UTC datetime")
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise SRV2ConfigError(f"{name} must use UTC")
    return result.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedSRV2ResearchNotebookConfig:
    version: int
    venue: str
    instrument_id: str
    asset: str
    analysis_start: datetime
    knowledge_cutoff: datetime
    source_mode: str
    cache_root: str
    max_replay_steps: int
    replay_identity_mode: str
    display: Mapping[str, Any]
    config_fingerprint: str

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version != 2:
            raise SRV2ConfigError("unsupported SR v2 research notebook version")
        for name in ("venue", "instrument_id", "asset", "cache_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SRV2ConfigError(f"{name} must be non-empty")
        if self.venue != "binance_usdm":
            raise SRV2ConfigError("research venue must be binance_usdm")
        if not isinstance(self.source_mode, str) or not isinstance(self.replay_identity_mode, str):
            raise SRV2ConfigError("research source and identity modes must be strings")
        if self.source_mode not in {ResearchSourceMode.CACHE_ONLY, ResearchSourceMode.BINANCE_USDM}:
            raise SRV2ConfigError(f"unsupported research source mode: {self.source_mode}")
        if self.replay_identity_mode not in {ReplayIdentityMode.EXACT_CHECKPOINT, ReplayIdentityMode.WINDOW_RELATIVE}:
            raise SRV2ConfigError(f"unsupported replay identity mode: {self.replay_identity_mode}")
        if self.analysis_start >= self.knowledge_cutoff:
            raise SRV2ConfigError("analysis_start must precede knowledge_cutoff")
        if self.analysis_start.utcoffset() != UTC.utcoffset(self.analysis_start) or self.knowledge_cutoff.utcoffset() != UTC.utcoffset(self.knowledge_cutoff):
            raise SRV2ConfigError("research bounds must use UTC")
        if isinstance(self.max_replay_steps, bool) or not isinstance(self.max_replay_steps, int) or self.max_replay_steps <= 0:
            raise SRV2ConfigError("max_replay_steps must be positive")
        object.__setattr__(self, "display", MappingProxyType(dict(self.display)))

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "version": self.version,
            "research": {
                "venue": self.venue,
                "instrument_id": self.instrument_id,
                "asset": self.asset,
                "analysis_start": self.analysis_start.isoformat(timespec="microseconds"),
                "knowledge_cutoff": self.knowledge_cutoff.isoformat(timespec="microseconds"),
                "source_mode": self.source_mode,
                "cache_root": self.cache_root,
                "max_replay_steps": self.max_replay_steps,
                "replay_identity_mode": self.replay_identity_mode,
            },
            "display": dict(self.display),
        }


class SRV2ResearchNotebookConfigResolver:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        if not isinstance(raw, Mapping):
            raise SRV2ConfigError("research notebook config must be a mapping")
        self._raw = dict(raw)

    @classmethod
    def from_yaml(cls, path: str | Path) -> SRV2ResearchNotebookConfigResolver:
        return cls(load_research_notebook_yaml(path))

    def resolve(self) -> ResolvedSRV2ResearchNotebookConfig:
        require_exact_keys(self._raw, {"version", "research", "display"}, "research notebook config")
        research = require_mapping(self._raw["research"], "research notebook research")
        require_exact_keys(
            research,
            {
                "venue",
                "instrument_id",
                "asset",
                "analysis_start",
                "knowledge_cutoff",
                "source_mode",
                "cache_root",
                "max_replay_steps",
                "replay_identity_mode",
            },
            "research notebook research",
        )
        normalized_display = normalize_display_policy(
            self._raw["display"],
            name="research notebook display",
        )
        if isinstance(self._raw["version"], bool) or not isinstance(self._raw["version"], int):
            raise SRV2ConfigError("research notebook version must be an integer")
        for name in ("venue", "instrument_id", "asset", "cache_root", "source_mode", "replay_identity_mode"):
            if not isinstance(research[name], str) or not research[name].strip():
                raise SRV2ConfigError(f"research.{name} must be a non-empty string")
        values = {
            "version": self._raw["version"],
            "venue": research["venue"],
            "instrument_id": research["instrument_id"].upper(),
            "asset": research["asset"].upper(),
            "analysis_start": _utc(research["analysis_start"], "research.analysis_start"),
            "knowledge_cutoff": _utc(research["knowledge_cutoff"], "research.knowledge_cutoff"),
            "source_mode": research["source_mode"].upper(),
            "cache_root": research["cache_root"],
            "max_replay_steps": bounded_int(research["max_replay_steps"], "research.max_replay_steps", minimum=1, maximum=1_000_000),
            "replay_identity_mode": research["replay_identity_mode"].upper(),
            "display": normalized_display,
        }
        fingerprint_mapping = dict(values)
        fingerprint_mapping["display"] = normalized_display
        values["config_fingerprint"] = canonical_hash(fingerprint_mapping)
        return ResolvedSRV2ResearchNotebookConfig(**values)


def load_research_notebook_yaml(path: str | Path) -> Mapping[str, Any]:
    try:
        value = yaml.load(Path(path).read_bytes(), Loader=_UniqueLoader)
    except SRV2ConfigError:
        raise
    except Exception as exc:
        raise SRV2ConfigError(f"invalid research notebook YAML: {path}") from exc
    if not isinstance(value, Mapping):
        raise SRV2ConfigError("research notebook YAML root must be a mapping")
    return value


__all__ = [
    "DISPLAY_POLICY_KEYS",
    "ReplayIdentityMode",
    "ResearchSourceMode",
    "ResolvedSRV2ResearchNotebookConfig",
    "SRV2ResearchNotebookConfigResolver",
    "load_research_notebook_yaml",
    "normalize_display_policy",
]
