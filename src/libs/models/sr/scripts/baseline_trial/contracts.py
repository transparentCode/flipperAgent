"""Immutable contracts for the SR-V1.5 baseline trial.

This module contains only protocol and data contracts. YAML loading, provider
access, and artifact publication live in separate leaf modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path, PurePath
import re
from typing import Any

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import (
    ClosedBar,
    ContractValidationError,
    SRSnapshot,
    SRState,
)
from libs.models.sr.domain.identity import deterministic_hash, require_utc
from libs.models.sr.evaluation.contracts import SREvaluationTrace
from libs.models.sr.evaluation.diagnostics import SRDiagnostics
from libs.models.sr.research.source.contracts import SourceBar


SR_BASELINE_TRIAL_SCHEMA_VERSION = "1.0"
BINANCE_ADAPTER_MAX_LIMIT = 1500
ATR_IMPLEMENTATION = "libs.features.indicators.volatility.atr.ATR"
ATR_IMPLEMENTATION_CONTRACT = "true_range_sma_seed_then_wilder_recursion_v1"
BASELINE_SYMBOL = "TAOUSDT"
BASELINE_TIMEFRAME = "1d"
BASELINE_VENUE = "binance_usdm"
BASELINE_TRIAL_NAME = "sr-v1.5-taousdt-1d-baseline"
BASELINE_WINDOW_POLICY = "half_open_utc_daily"
VIEWER_LIBRARY = "lightweight-charts"
VIEWER_LIBRARY_VERSION = "5.2.0"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_INPUT_PATHS = ("atr.method", "atr.period", "atr.seed")


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    return require_utc(value, field_name=field_name)


def epoch_milliseconds(timestamp: datetime) -> int:
    """Return canonical UTC epoch milliseconds for a validated timestamp."""
    normalized = _timestamp(timestamp, field_name="timestamp")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = normalized - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def effective_provider_request_bounds(
    requested_since: datetime,
    requested_until: datetime,
) -> tuple[int, int]:
    """Return Binance bounds for the half-open model window."""
    since = _timestamp(requested_since, field_name="requested_since")
    until = _timestamp(requested_until, field_name="requested_until")
    if since >= until:
        raise ContractValidationError("requested_since must be < requested_until")
    return epoch_milliseconds(since), epoch_milliseconds(until) - 1


def _number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _boolean(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _relative_path(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    path = PurePath(value.replace("\\", "/"))
    if Path(value).is_absolute() or value.startswith("/") or ".." in path.parts:
        raise ContractValidationError(
            f"{field_name} must be a relative path without parent traversal"
        )
    return value


@dataclass(frozen=True)
class ResolvedInputConfig:
    """Resolved causal ATR-input configuration and field provenance."""

    version: str
    asset: str
    timeframe: str
    atr_method: str
    atr_period: int
    atr_seed: str
    field_provenance: tuple[tuple[str, str], ...]
    resolved_input_hash: str

    def __post_init__(self) -> None:
        if _string(self.version, field_name="version") != "1":
            raise ContractValidationError(
                f"unsupported input config version: {self.version!r}"
            )
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(
            self,
            "timeframe",
            _string(self.timeframe, field_name="timeframe"),
        )
        if _string(self.atr_method, field_name="atr_method") != "wilder_rma":
            raise ContractValidationError("atr_method must be exactly 'wilder_rma'")
        object.__setattr__(
            self,
            "atr_period",
            _integer(self.atr_period, field_name="atr_period", minimum=1),
        )
        if _string(self.atr_seed, field_name="atr_seed") != "sma":
            raise ContractValidationError("atr_seed must be exactly 'sma'")
        if type(self.field_provenance) is not tuple:
            raise ContractValidationError("field_provenance must be exactly a tuple")
        entries = []
        for index, entry in enumerate(self.field_provenance):
            if type(entry) is not tuple or len(entry) != 2:
                raise ContractValidationError(
                    f"field_provenance[{index}] must be a pair tuple"
                )
            entries.append(
                (
                    _string(entry[0], field_name=f"field_provenance[{index}].path"),
                    _string(entry[1], field_name=f"field_provenance[{index}].source"),
                )
            )
        if tuple(path for path, _ in entries) != _INPUT_PATHS:
            raise ContractValidationError(
                "field_provenance must contain exactly the ATR input paths"
            )
        allowed_sources = {
            "defaults",
            f"timeframe:{self.timeframe}",
            f"asset_timeframe:{self.asset}:{self.timeframe}",
        }
        if any(source not in allowed_sources for _, source in entries):
            raise ContractValidationError("invalid input field provenance source")
        object.__setattr__(self, "field_provenance", tuple(entries))
        expected_hash = deterministic_hash(self.hash_payload())
        if _hash(self.resolved_input_hash, field_name="resolved_input_hash") != expected_hash:
            raise ContractValidationError("resolved_input_hash does not match content")

    def hash_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "atr_method": self.atr_method,
            "atr_period": self.atr_period,
            "atr_seed": self.atr_seed,
            "field_provenance": [list(pair) for pair in self.field_provenance],
        }

    @classmethod
    def create(
        cls,
        *,
        version: str,
        asset: str,
        timeframe: str,
        atr_method: str,
        atr_period: int,
        atr_seed: str,
        field_provenance: tuple[tuple[str, str], ...],
    ) -> ResolvedInputConfig:
        payload = {
            "version": version,
            "asset": asset,
            "timeframe": timeframe,
            "atr_method": atr_method,
            "atr_period": atr_period,
            "atr_seed": atr_seed,
            "field_provenance": [list(pair) for pair in field_provenance],
        }
        return cls(
            version=version,
            asset=asset,
            timeframe=timeframe,
            atr_method=atr_method,
            atr_period=atr_period,
            atr_seed=atr_seed,
            field_provenance=field_provenance,
            resolved_input_hash=deterministic_hash(payload),
        )


@dataclass(frozen=True)
class ViewerConfig:
    library: str
    library_version: str
    attribution_logo: bool
    live_zone_extent: str
    show_terminal_by_default: bool
    show_events_by_default: bool
    background_color: str
    text_color: str
    grid_color: str
    support_border_color: str
    support_fill_color: str
    resistance_border_color: str
    resistance_fill_color: str
    pending_border_color: str
    terminal_opacity: float
    zone_line_width: int

    def __post_init__(self) -> None:
        if _string(self.library, field_name="viewer.library") != VIEWER_LIBRARY:
            raise ContractValidationError("viewer.library must be lightweight-charts")
        if _string(self.library_version, field_name="viewer.library_version") != VIEWER_LIBRARY_VERSION:
            raise ContractValidationError("unsupported Lightweight Charts version")
        if not _boolean(self.attribution_logo, field_name="viewer.attribution_logo"):
            raise ContractValidationError("viewer.attribution_logo must be true")
        if _string(self.live_zone_extent, field_name="viewer.live_zone_extent") != "viewport_right_edge":
            raise ContractValidationError(
                "viewer.live_zone_extent must be viewport_right_edge"
            )
        for field_name in ("show_terminal_by_default", "show_events_by_default"):
            object.__setattr__(
                self,
                field_name,
                _boolean(getattr(self, field_name), field_name=f"viewer.{field_name}"),
            )
        for field_name in (
            "background_color",
            "text_color",
            "grid_color",
            "support_border_color",
            "support_fill_color",
            "resistance_border_color",
            "resistance_fill_color",
            "pending_border_color",
        ):
            object.__setattr__(
                self,
                field_name,
                _string(getattr(self, field_name), field_name=f"viewer.{field_name}"),
            )
        object.__setattr__(
            self,
            "terminal_opacity",
            _number(
                self.terminal_opacity,
                field_name="viewer.terminal_opacity",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "zone_line_width",
            _integer(self.zone_line_width, field_name="viewer.zone_line_width", minimum=1),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "library_version": self.library_version,
            "attribution_logo": self.attribution_logo,
            "live_zone_extent": self.live_zone_extent,
            "show_terminal_by_default": self.show_terminal_by_default,
            "show_events_by_default": self.show_events_by_default,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "grid_color": self.grid_color,
            "support_border_color": self.support_border_color,
            "support_fill_color": self.support_fill_color,
            "resistance_border_color": self.resistance_border_color,
            "resistance_fill_color": self.resistance_fill_color,
            "pending_border_color": self.pending_border_color,
            "terminal_opacity": self.terminal_opacity,
            "zone_line_width": self.zone_line_width,
        }


@dataclass(frozen=True)
class TrialSpec:
    version: str
    trial_name: str
    venue: str
    symbol: str
    timeframe: str
    requested_since: datetime
    requested_until: datetime
    adapter_limit: int
    gap_policy: str
    sr_config_path: str
    input_config_path: str
    output_root: str
    viewer: ViewerConfig

    def __post_init__(self) -> None:
        if _string(self.version, field_name="version") != "1":
            raise ContractValidationError(f"unsupported trial config version: {self.version!r}")
        for field_name in ("trial_name", "venue", "symbol", "timeframe"):
            object.__setattr__(
                self,
                field_name,
                _string(getattr(self, field_name), field_name=field_name),
            )
        if self.trial_name != BASELINE_TRIAL_NAME:
            raise ContractValidationError("trial_name does not match the frozen baseline")
        if self.venue != BASELINE_VENUE:
            raise ContractValidationError("venue does not match the frozen baseline")
        if self.symbol != BASELINE_SYMBOL:
            raise ContractValidationError("symbol does not match the frozen baseline")
        if self.timeframe != BASELINE_TIMEFRAME:
            raise ContractValidationError("timeframe does not match the frozen baseline")
        since = _timestamp(self.requested_since, field_name="requested_since")
        until = _timestamp(self.requested_until, field_name="requested_until")
        if since >= until:
            raise ContractValidationError("requested_since must be < requested_until")
        if any(
            value.hour != 0
            or value.minute != 0
            or value.second != 0
            or value.microsecond != 0
            for value in (since, until)
        ):
            raise ContractValidationError(
                "requested timestamps must align to UTC daily boundaries"
            )
        object.__setattr__(self, "requested_since", since)
        object.__setattr__(self, "requested_until", until)
        object.__setattr__(
            self,
            "adapter_limit",
            _integer(self.adapter_limit, field_name="adapter_limit", minimum=1),
        )
        if self.adapter_limit > BINANCE_ADAPTER_MAX_LIMIT:
            raise ContractValidationError(
                f"adapter_limit must be <= {BINANCE_ADAPTER_MAX_LIMIT}"
            )
        if _string(self.gap_policy, field_name="gap_policy") != "reject":
            raise ContractValidationError("gap_policy must be exactly 'reject'")
        for field_name in ("sr_config_path", "input_config_path", "output_root"):
            object.__setattr__(
                self,
                field_name,
                _relative_path(getattr(self, field_name), field_name=field_name),
            )
        if type(self.viewer) is not ViewerConfig:
            raise ContractValidationError("viewer must be exactly ViewerConfig")

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial_name": self.trial_name,
            "venue": self.venue,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "requested_since": self.requested_since.isoformat().replace("+00:00", "Z"),
            "requested_until": self.requested_until.isoformat().replace("+00:00", "Z"),
            "adapter_limit": self.adapter_limit,
            "gap_policy": self.gap_policy,
            "sr_config_path": self.sr_config_path,
            "input_config_path": self.input_config_path,
            "output_root": self.output_root,
            "viewer": self.viewer.to_payload(),
        }


@dataclass(frozen=True)
class ValidatedDataset:
    bars: tuple[SourceBar, ...]
    requested_since: datetime
    requested_until: datetime
    actual_since: datetime
    actual_until: datetime
    raw_row_count: int
    adapter_limit: int
    gap_policy: str

    def __post_init__(self) -> None:
        if type(self.bars) is not tuple or not self.bars:
            raise ContractValidationError("validated dataset bars must be non-empty tuple")
        if any(type(bar) is not SourceBar for bar in self.bars):
            raise ContractValidationError("validated dataset must contain SourceBar values")
        requested_since = _timestamp(self.requested_since, field_name="requested_since")
        requested_until = _timestamp(self.requested_until, field_name="requested_until")
        actual_since = _timestamp(self.actual_since, field_name="actual_since")
        actual_until = _timestamp(self.actual_until, field_name="actual_until")
        if requested_since >= requested_until or actual_since > actual_until:
            raise ContractValidationError("dataset bounds are invalid")
        if actual_since < requested_since or actual_until > requested_until:
            raise ContractValidationError("actual dataset bounds exceed requested bounds")
        if actual_since != self.bars[0].open_time or actual_until != self.bars[-1].closed_at:
            raise ContractValidationError("actual dataset bounds do not match bars")
        object.__setattr__(self, "requested_since", requested_since)
        object.__setattr__(self, "requested_until", requested_until)
        object.__setattr__(self, "actual_since", actual_since)
        object.__setattr__(self, "actual_until", actual_until)
        object.__setattr__(
            self,
            "raw_row_count",
            _integer(self.raw_row_count, field_name="raw_row_count", minimum=1),
        )
        if self.raw_row_count != len(self.bars):
            raise ContractValidationError("raw_row_count does not match bars")
        object.__setattr__(
            self,
            "adapter_limit",
            _integer(self.adapter_limit, field_name="adapter_limit", minimum=1),
        )
        if self.raw_row_count >= self.adapter_limit:
            raise ContractValidationError("dataset row count must be below adapter_limit")
        if _string(self.gap_policy, field_name="gap_policy") != "reject":
            raise ContractValidationError("gap_policy must be exactly 'reject'")


@dataclass(frozen=True)
class ATRProvenance:
    method: str
    period: int
    seed: str
    implementation: str
    implementation_contract: str
    warmup_count: int
    first_valid_at: datetime
    raw_bar_count: int
    model_bar_count: int

    def __post_init__(self) -> None:
        if _string(self.method, field_name="atr.method") != "wilder_rma":
            raise ContractValidationError("atr.method must be wilder_rma")
        object.__setattr__(self, "period", _integer(self.period, field_name="atr.period", minimum=1))
        if _string(self.seed, field_name="atr.seed") != "sma":
            raise ContractValidationError("atr.seed must be sma")
        object.__setattr__(self, "implementation", _string(self.implementation, field_name="atr.implementation"))
        object.__setattr__(self, "implementation_contract", _string(self.implementation_contract, field_name="atr.implementation_contract"))
        object.__setattr__(self, "warmup_count", _integer(self.warmup_count, field_name="atr.warmup_count", minimum=0))
        object.__setattr__(self, "first_valid_at", _timestamp(self.first_valid_at, field_name="atr.first_valid_at"))
        object.__setattr__(self, "raw_bar_count", _integer(self.raw_bar_count, field_name="atr.raw_bar_count", minimum=1))
        object.__setattr__(self, "model_bar_count", _integer(self.model_bar_count, field_name="atr.model_bar_count", minimum=1))
        if self.warmup_count + self.model_bar_count != self.raw_bar_count:
            raise ContractValidationError("ATR row counts do not reconcile")
        if self.first_valid_at is None:
            raise ContractValidationError("ATR first_valid_at is required")

    def to_payload(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "period": self.period,
            "seed": self.seed,
            "implementation": self.implementation,
            "implementation_contract": self.implementation_contract,
            "warmup_count": self.warmup_count,
            "first_valid_at": self.first_valid_at.isoformat().replace("+00:00", "Z"),
            "raw_bar_count": self.raw_bar_count,
            "model_bar_count": self.model_bar_count,
        }


@dataclass(frozen=True)
class BundleMember:
    name: str
    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        name = _string(self.name, field_name="member.name")
        if name == "manifest.json" or name.startswith("/") or ".." in PurePath(name).parts:
            raise ContractValidationError("invalid bundle member name")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "sha256", _hash(self.sha256, field_name=f"member[{name}].sha256"))
        object.__setattr__(self, "byte_length", _integer(self.byte_length, field_name=f"member[{name}].byte_length", minimum=0))


@dataclass(frozen=True)
class EvidenceManifest:
    schema_version: str
    trial: TrialSpec
    provider_adapter: str
    dataset: ValidatedDataset
    resolved_sr_config: ResolvedSRConfig
    resolved_input: ResolvedInputConfig
    atr: ATRProvenance
    implementation_commit: str
    sr_schema_version: str
    evaluation_schema_version: str
    trace_id: str
    diagnostics_id: str
    chart_payload_schema_version: str
    members: tuple[BundleMember, ...]
    bundle_id: str

    def __post_init__(self) -> None:
        if _string(self.schema_version, field_name="manifest.schema_version") != SR_BASELINE_TRIAL_SCHEMA_VERSION:
            raise ContractValidationError("unsupported baseline trial schema version")
        if type(self.trial) is not TrialSpec:
            raise ContractValidationError("manifest.trial must be exactly TrialSpec")
        object.__setattr__(self, "provider_adapter", _string(self.provider_adapter, field_name="provider_adapter"))
        if self.provider_adapter != "apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter":
            raise ContractValidationError("unsupported provider adapter")
        for field_name, expected in (("sr_schema_version", "1.0"), ("evaluation_schema_version", "1.0")):
            if _string(getattr(self, field_name), field_name=field_name) != expected:
                raise ContractValidationError(f"unsupported {field_name}")
        if type(self.dataset) is not ValidatedDataset or type(self.resolved_input) is not ResolvedInputConfig or type(self.atr) is not ATRProvenance:
            raise ContractValidationError("manifest source contracts have invalid types")
        if self.resolved_input.asset != self.trial.symbol or self.resolved_input.timeframe != self.trial.timeframe:
            raise ContractValidationError("manifest input identity does not match trial")
        if self.dataset.requested_since != self.trial.requested_since or self.dataset.requested_until != self.trial.requested_until:
            raise ContractValidationError("manifest dataset bounds do not match trial")
        if self.atr.first_valid_at != self.dataset.bars[self.atr.warmup_count].closed_at:
            raise ContractValidationError(
                "manifest ATR first_valid_at must equal first model bar closed_at"
            )
        if (
            self.atr.method != self.resolved_input.atr_method
            or self.atr.period != self.resolved_input.atr_period
            or self.atr.seed != self.resolved_input.atr_seed
        ):
            raise ContractValidationError("manifest ATR identity does not match input")
        object.__setattr__(self, "implementation_commit", _string(self.implementation_commit, field_name="implementation_commit"))
        if _COMMIT_RE.fullmatch(self.implementation_commit) is None:
            raise ContractValidationError("implementation_commit must be a git SHA")
        object.__setattr__(self, "trace_id", _hash(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "diagnostics_id", _hash(self.diagnostics_id, field_name="diagnostics_id"))
        object.__setattr__(self, "chart_payload_schema_version", _string(self.chart_payload_schema_version, field_name="chart_payload_schema_version"))
        if self.chart_payload_schema_version != "1.0":
            raise ContractValidationError("unsupported chart payload schema version")
        if type(self.members) is not tuple or not self.members:
            raise ContractValidationError("manifest members must be a non-empty tuple")
        if any(type(member) is not BundleMember for member in self.members):
            raise ContractValidationError("manifest members must contain BundleMember values")
        names = [member.name for member in self.members]
        if len(set(names)) != len(names):
            raise ContractValidationError("manifest member names must be unique")
        object.__setattr__(self, "bundle_id", _hash(self.bundle_id, field_name="bundle_id"))


@dataclass(frozen=True)
class TrialResult:
    trial: TrialSpec
    resolved_sr_config: ResolvedSRConfig
    resolved_input: ResolvedInputConfig
    dataset: ValidatedDataset
    model_bars: tuple[ClosedBar, ...]
    atr: ATRProvenance
    final_state: SRState
    snapshots: tuple[SRSnapshot, ...]
    trace: SREvaluationTrace
    diagnostics: SRDiagnostics

    def __post_init__(self) -> None:
        if type(self.trial) is not TrialSpec or type(self.resolved_sr_config) is not ResolvedSRConfig or type(self.resolved_input) is not ResolvedInputConfig or type(self.dataset) is not ValidatedDataset or type(self.atr) is not ATRProvenance or type(self.final_state) is not SRState or type(self.trace) is not SREvaluationTrace or type(self.diagnostics) is not SRDiagnostics:
            raise ContractValidationError("trial result contains invalid contract types")
        if type(self.model_bars) is not tuple or not self.model_bars or any(type(bar) is not ClosedBar for bar in self.model_bars):
            raise ContractValidationError("model_bars must be a non-empty tuple of ClosedBar")
        if type(self.snapshots) is not tuple or not self.snapshots or any(type(snapshot) is not SRSnapshot for snapshot in self.snapshots):
            raise ContractValidationError("snapshots must be a non-empty tuple of SRSnapshot")
        if self.final_state.state_key != self.trace.state_key or self.trace.config_hash != self.resolved_sr_config.resolved_config_hash:
            raise ContractValidationError("trial result identity ownership does not reconcile")
        if self.resolved_input.asset != self.trial.symbol or self.resolved_input.timeframe != self.trial.timeframe:
            raise ContractValidationError("trial input identity does not reconcile")
        if self.resolved_sr_config.asset != self.trial.symbol or self.resolved_sr_config.timeframe != self.trial.timeframe:
            raise ContractValidationError("trial SR identity does not reconcile")
        if self.final_state.state_key != self.model_bars[0].state_key:
            raise ContractValidationError("trial state key does not reconcile")
        if self.atr.first_valid_at != self.model_bars[0].closed_at:
            raise ContractValidationError(
                "ATR first_valid_at must equal first model bar closed_at"
            )
        if len(self.snapshots) != len(self.model_bars):
            raise ContractValidationError("snapshot and model-bar counts do not reconcile")
        if self.atr.model_bar_count != len(self.model_bars) or self.dataset.raw_row_count != self.atr.raw_bar_count:
            raise ContractValidationError("trial result row counts do not reconcile")


@dataclass(frozen=True)
class BundlePublication:
    bundle_id: str
    output_path: Path
    manifest: EvidenceManifest

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _hash(self.bundle_id, field_name="bundle_id"))
        if not isinstance(self.output_path, Path):
            raise ContractValidationError("output_path must be a pathlib.Path")
        if type(self.manifest) is not EvidenceManifest:
            raise ContractValidationError("manifest must be exactly EvidenceManifest")


__all__ = [
    "ATR_IMPLEMENTATION",
    "ATR_IMPLEMENTATION_CONTRACT",
    "ATRProvenance",
    "BASELINE_SYMBOL",
    "BASELINE_TRIAL_NAME",
    "BASELINE_TIMEFRAME",
    "BASELINE_VENUE",
    "BASELINE_WINDOW_POLICY",
    "BINANCE_ADAPTER_MAX_LIMIT",
    "BundleMember",
    "BundlePublication",
    "EvidenceManifest",
    "ResolvedInputConfig",
    "SR_BASELINE_TRIAL_SCHEMA_VERSION",
    "SourceBar",
    "TrialResult",
    "TrialSpec",
    "ValidatedDataset",
    "VIEWER_LIBRARY",
    "VIEWER_LIBRARY_VERSION",
    "ViewerConfig",
    "effective_provider_request_bounds",
    "epoch_milliseconds",
]
