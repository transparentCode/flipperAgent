"""Typed controls and result contracts for the mature trendlines research lab."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from libs.models.trendlines.workflows.research.contracts import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
)


RESEARCH_LAB_SEMANTICS_VERSION = "trendlines.research-lab.v1"
DEFAULT_SELECTION_POLICY = "latest_valid_geometry"
VALID_SELECTION_POLICIES = frozenset(
    {DEFAULT_SELECTION_POLICY, "latest_recorded"}
)


class TrendlineResearchLabContractError(ValueError):
    """Raised when research-lab controls or results violate their contract."""


def _enum(value: Any, enum_type: type[Enum], name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().lower())
    except (TypeError, ValueError) as exc:
        raise TrendlineResearchLabContractError(f"unknown {name}: {value!r}") from exc


def _ordered_mapping(value: Mapping[str, Any], *, name: str) -> MappingProxyType:
    if not isinstance(value, Mapping):
        raise TrendlineResearchLabContractError(f"{name} must be a mapping")
    normalized = {str(key).strip(): item for key, item in value.items()}
    if any(not key for key in normalized):
        raise TrendlineResearchLabContractError(f"{name} contains an empty key")
    return MappingProxyType(normalized)


@dataclass(frozen=True)
class TrendlineResearchLabControls:
    """Immutable notebook controls; model parameters are deliberately absent."""

    purpose: TrendlineResearchPurpose
    data_mode: TrendlineResearchDataMode
    asset: str
    timeframes: tuple[str, ...]
    primary_timeframe: str
    data_spec: TrendlineResearchDataSpec
    replay_spec: TrendlineResearchReplaySpec
    include_signals: bool
    provider_calls_authorized: bool
    viewer_lookback_bars: int
    start_inline_viewers: bool
    permanent_export: bool
    selected_positions: Mapping[str, int] = field(default_factory=dict)
    selection_policy: str = DEFAULT_SELECTION_POLICY

    def __post_init__(self) -> None:
        purpose = _enum(self.purpose, TrendlineResearchPurpose, "research purpose")
        mode = _enum(self.data_mode, TrendlineResearchDataMode, "research data mode")
        if not isinstance(self.data_spec, TrendlineResearchDataSpec):
            raise TrendlineResearchLabContractError(
                "data_spec must be a TrendlineResearchDataSpec"
            )
        if self.data_spec.mode is not mode:
            raise TrendlineResearchLabContractError(
                "data_mode must match data_spec.mode"
            )
        asset = str(self.asset).strip().upper()
        timeframes = tuple(str(value).strip() for value in self.timeframes)
        if not asset:
            raise TrendlineResearchLabContractError("asset is required")
        if not timeframes or any(not value for value in timeframes):
            raise TrendlineResearchLabContractError("timeframes must be non-empty")
        if len(set(timeframes)) != len(timeframes):
            raise TrendlineResearchLabContractError("timeframes must be ordered and unique")
        primary = str(self.primary_timeframe).strip()
        if primary not in timeframes:
            raise TrendlineResearchLabContractError(
                "primary_timeframe must be present in timeframes"
            )
        if not isinstance(self.include_signals, bool):
            raise TrendlineResearchLabContractError("include_signals must be bool")
        for name, value in (
            ("provider_calls_authorized", self.provider_calls_authorized),
            ("start_inline_viewers", self.start_inline_viewers),
            ("permanent_export", self.permanent_export),
        ):
            if not isinstance(value, bool):
                raise TrendlineResearchLabContractError(f"{name} must be bool")
        if (
            isinstance(self.viewer_lookback_bars, bool)
            or not isinstance(self.viewer_lookback_bars, int)
            or self.viewer_lookback_bars < 1
        ):
            raise TrendlineResearchLabContractError(
                "viewer_lookback_bars must be a positive integer"
            )
        if not isinstance(self.replay_spec, TrendlineResearchReplaySpec):
            raise TrendlineResearchLabContractError(
                "replay_spec must be a TrendlineResearchReplaySpec"
            )
        if tuple(self.replay_spec.windows) != timeframes:
            raise TrendlineResearchLabContractError(
                "replay windows must cover timeframes in order"
            )
        if self.replay_spec.include_signals is not self.include_signals:
            raise TrendlineResearchLabContractError(
                "replay include_signals must match lab controls"
            )
        if purpose is TrendlineResearchPurpose.SMOKE and mode is TrendlineResearchDataMode.BINANCE:
            raise TrendlineResearchLabContractError(
                "SMOKE purpose cannot use BINANCE data"
            )
        if mode is TrendlineResearchDataMode.BINANCE:
            if purpose is not TrendlineResearchPurpose.RESEARCH:
                raise TrendlineResearchLabContractError(
                    "BINANCE data requires RESEARCH purpose"
                )
        elif self.provider_calls_authorized:
            raise TrendlineResearchLabContractError(
                "provider authorization is valid only for BINANCE mode"
            )
        policy = str(self.selection_policy).strip()
        if policy not in VALID_SELECTION_POLICIES:
            raise TrendlineResearchLabContractError(
                f"unknown selection policy: {self.selection_policy!r}"
            )
        positions = _ordered_mapping(self.selected_positions, name="selected_positions")
        for timeframe, position in positions.items():
            if timeframe not in timeframes:
                raise TrendlineResearchLabContractError(
                    f"selected position uses unexpected timeframe: {timeframe}"
                )
            if isinstance(position, bool) or not isinstance(position, int) or position < 0:
                raise TrendlineResearchLabContractError(
                    "selected positions must be non-negative integers"
                )
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframes", timeframes)
        object.__setattr__(self, "primary_timeframe", primary)
        object.__setattr__(self, "selected_positions", positions)
        object.__setattr__(self, "selection_policy", policy)

    def to_spec(self) -> TrendlineResearchSpec:
        """Build the canonical source-agnostic research specification."""

        return TrendlineResearchSpec(
            purpose=self.purpose,
            data=self.data_spec,
            asset=self.asset,
            timeframes=self.timeframes,
            primary_timeframe=self.primary_timeframe,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose.value,
            "data_mode": self.data_mode.value,
            "asset": self.asset,
            "timeframes": list(self.timeframes),
            "primary_timeframe": self.primary_timeframe,
            "data_spec": self.data_spec.to_dict(),
            "replay_spec": self.replay_spec.to_dict(),
            "include_signals": self.include_signals,
            "provider_calls_authorized": self.provider_calls_authorized,
            "viewer_lookback_bars": self.viewer_lookback_bars,
            "start_inline_viewers": self.start_inline_viewers,
            "permanent_export": self.permanent_export,
            "selected_positions": dict(self.selected_positions),
            "selection_policy": self.selection_policy,
            "semantics_version": RESEARCH_LAB_SEMANTICS_VERSION,
        }


@dataclass(frozen=True)
class TrendlineResearchLabTimings:
    """Measured orchestration timings; never included in research identities."""

    preparation_ms: float
    replay_ms: float
    evidence_ms_by_timeframe: Mapping[str, float]
    viewer_payload_ms_by_timeframe: Mapping[str, float]
    viewer_bundle_ms_by_timeframe: Mapping[str, float]
    table_ms: float = 0.0
    viewer_startup_ms_by_timeframe: Mapping[str, float] = field(default_factory=dict)
    total_ms: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "evidence_ms_by_timeframe",
            "viewer_payload_ms_by_timeframe",
            "viewer_bundle_ms_by_timeframe",
            "viewer_startup_ms_by_timeframe",
        ):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TrendlineResearchLabContractError(f"{name} must be a mapping")
            object.__setattr__(self, name, MappingProxyType(dict(value)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "preparation_ms": self.preparation_ms,
            "replay_ms": self.replay_ms,
            "evidence_ms_by_timeframe": dict(self.evidence_ms_by_timeframe),
            "viewer_payload_ms_by_timeframe": dict(self.viewer_payload_ms_by_timeframe),
            "viewer_bundle_ms_by_timeframe": dict(self.viewer_bundle_ms_by_timeframe),
            "table_ms": self.table_ms,
            "viewer_startup_ms_by_timeframe": dict(self.viewer_startup_ms_by_timeframe),
            "total_ms": self.total_ms,
        }


@dataclass(frozen=True)
class TrendlineResearchLabSelection:
    """All validated evidence associated with one replay coordinate."""

    timeframe: str
    position: int
    selection_reason: str
    point: Any
    snapshot_row: Any
    pivot_count_row: Any
    selected_pivots: tuple[Any, ...]
    line_rows: tuple[Any, ...]
    ray_rows: tuple[Any, ...]
    signal_rows: tuple[Any, ...]
    evidence_bundle: Any
    viewer_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not str(self.timeframe).strip():
            raise TrendlineResearchLabContractError("selection timeframe is required")
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise TrendlineResearchLabContractError("selection position must be integer")
        if not str(self.selection_reason).strip():
            raise TrendlineResearchLabContractError("selection reason is required")


@dataclass(frozen=True)
class TrendlineResearchStudyRegistry:
    """Notebook-visible inventory separating available from deferred studies."""

    available: tuple[str, ...]
    l2d_pending: tuple[str, ...]
    separate_programme: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "AVAILABLE": list(self.available),
            "L2-D PENDING": list(self.l2d_pending),
            "SEPARATE PROGRAMME": list(self.separate_programme),
        }


def default_study_registry() -> TrendlineResearchStudyRegistry:
    return TrendlineResearchStudyRegistry(
        available=(
            "causal replay inspection",
            "pivot diagnostics",
            "line/ray diagnostics",
            "signal inspection",
            "position comparison",
            "performance inspection",
            "evidence export",
        ),
        l2d_pending=(
            "longevity",
            "churn/revision adequacy",
            "null comparison",
            "touch/penetration utility",
            "sensitivity",
            "cross-window robustness",
            "cross-asset adequacy",
        ),
        separate_programme=(
            "RSI/MACD trendlines",
            "price/oscillator confluence",
        ),
    )


def _build_controls(
    *,
    purpose: TrendlineResearchPurpose,
    data_spec: TrendlineResearchDataSpec,
    asset: str,
    timeframes: tuple[str, ...],
    primary_timeframe: str,
    replay_windows: Mapping[str, Any],
    include_signals: bool,
    provider_calls_authorized: bool,
    viewer_lookback_bars: int,
    start_inline_viewers: bool,
    permanent_export: bool,
    selected_positions: Mapping[str, int] | None,
    selection_policy: str,
) -> TrendlineResearchLabControls:
    from libs.models.trendlines.workflows.research.contracts import (
        TrendlineResearchReplaySpec,
    )

    replay_spec = TrendlineResearchReplaySpec(
        windows=dict(replay_windows),
        include_signals=include_signals,
    )
    return TrendlineResearchLabControls(
        purpose=purpose,
        data_mode=data_spec.mode,
        asset=asset,
        timeframes=tuple(timeframes),
        primary_timeframe=primary_timeframe,
        data_spec=data_spec,
        replay_spec=replay_spec,
        include_signals=include_signals,
        provider_calls_authorized=provider_calls_authorized,
        viewer_lookback_bars=viewer_lookback_bars,
        start_inline_viewers=start_inline_viewers,
        permanent_export=permanent_export,
        selected_positions=selected_positions or {},
        selection_policy=selection_policy,
    )


def synthetic_lab_controls(
    *,
    asset: str,
    timeframes: tuple[str, ...],
    primary_timeframe: str,
    seed: int,
    start_time: datetime,
    bar_counts: Mapping[str, int],
    replay_windows: Mapping[str, Any],
    include_signals: bool = True,
    viewer_lookback_bars: int = 64,
    start_inline_viewers: bool = True,
    permanent_export: bool = False,
    selected_positions: Mapping[str, int] | None = None,
    selection_policy: str = DEFAULT_SELECTION_POLICY,
) -> TrendlineResearchLabControls:
    data_spec = TrendlineResearchDataSpec(
        mode=TrendlineResearchDataMode.SYNTHETIC,
        seed=seed,
        start_time=start_time,
        bar_counts=bar_counts,
    )
    return _build_controls(
        purpose=TrendlineResearchPurpose.SMOKE,
        data_spec=data_spec,
        asset=asset,
        timeframes=timeframes,
        primary_timeframe=primary_timeframe,
        replay_windows=replay_windows,
        include_signals=include_signals,
        provider_calls_authorized=False,
        viewer_lookback_bars=viewer_lookback_bars,
        start_inline_viewers=start_inline_viewers,
        permanent_export=permanent_export,
        selected_positions=selected_positions,
        selection_policy=selection_policy,
    )


def injected_lab_controls(
    *,
    asset: str,
    timeframes: tuple[str, ...],
    primary_timeframe: str,
    replay_windows: Mapping[str, Any],
    include_signals: bool = True,
    viewer_lookback_bars: int = 64,
    start_inline_viewers: bool = True,
    permanent_export: bool = False,
    selected_positions: Mapping[str, int] | None = None,
    selection_policy: str = DEFAULT_SELECTION_POLICY,
) -> TrendlineResearchLabControls:
    data_spec = TrendlineResearchDataSpec(mode=TrendlineResearchDataMode.INJECTED)
    return _build_controls(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data_spec=data_spec,
        asset=asset,
        timeframes=timeframes,
        primary_timeframe=primary_timeframe,
        replay_windows=replay_windows,
        include_signals=include_signals,
        provider_calls_authorized=False,
        viewer_lookback_bars=viewer_lookback_bars,
        start_inline_viewers=start_inline_viewers,
        permanent_export=permanent_export,
        selected_positions=selected_positions,
        selection_policy=selection_policy,
    )


def binance_lab_controls(
    *,
    asset: str,
    timeframes: tuple[str, ...],
    primary_timeframe: str,
    event_start: datetime,
    knowledge_cutoff: datetime,
    replay_windows: Mapping[str, Any],
    include_signals: bool = True,
    provider_calls_authorized: bool = False,
    viewer_lookback_bars: int = 128,
    start_inline_viewers: bool = True,
    permanent_export: bool = False,
    selected_positions: Mapping[str, int] | None = None,
    selection_policy: str = DEFAULT_SELECTION_POLICY,
) -> TrendlineResearchLabControls:
    data_spec = TrendlineResearchDataSpec(
        mode=TrendlineResearchDataMode.BINANCE,
        event_start=event_start,
        knowledge_cutoff=knowledge_cutoff,
    )
    return _build_controls(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data_spec=data_spec,
        asset=asset,
        timeframes=timeframes,
        primary_timeframe=primary_timeframe,
        replay_windows=replay_windows,
        include_signals=include_signals,
        provider_calls_authorized=provider_calls_authorized,
        viewer_lookback_bars=viewer_lookback_bars,
        start_inline_viewers=start_inline_viewers,
        permanent_export=permanent_export,
        selected_positions=selected_positions,
        selection_policy=selection_policy,
    )


__all__ = [
    "DEFAULT_SELECTION_POLICY",
    "RESEARCH_LAB_SEMANTICS_VERSION",
    "TrendlineResearchLabContractError",
    "TrendlineResearchLabControls",
    "TrendlineResearchLabSelection",
    "TrendlineResearchLabTimings",
    "TrendlineResearchStudyRegistry",
    "binance_lab_controls",
    "default_study_registry",
    "injected_lab_controls",
    "synthetic_lab_controls",
]
