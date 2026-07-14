"""Causal replay adapters. They only call canonical model APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from time import perf_counter
from typing import Any, Mapping

import pandas as pd

from ..config import CandidateConfig, ResolvedTrendlineFamilyConfig, TrendlineFamilyConfig, canonical_timeframe_duration_seconds
from ..contracts import ContractValidationError, TrendlineFamilyOutput, deterministic_hash
from ..provider import CandidateGenerationResult, LineCandidateProvider, NativeDeterministicLineProvider
from ..repository import InMemoryTrendlineFamilyRepository
from ..tracker import TrendlineFamilyTracker
from ..optimization.folds import ImmutableHistoricalFrame
from .contracts import ResearchRunContext, SnapshotSummary


@dataclass(frozen=True)
class ResearchReplay:
    context: ResearchRunContext
    dataset: ImmutableHistoricalFrame
    outputs: tuple[TrendlineFamilyOutput, ...]
    candidate_results: tuple[CandidateGenerationResult, ...]
    runtime_diagnostics: Mapping[str, float]

    def __post_init__(self) -> None:
        if len(self.outputs) != self.dataset.row_count or len(self.candidate_results) != self.dataset.row_count:
            raise ContractValidationError("research replay must preserve one output and provider result per confirmed bar")
        if tuple(output.snapshot.timestamp for output in self.outputs) != self.dataset.timestamps:
            raise ContractValidationError("research replay output timestamps must match immutable dataset")

    def output_at(self, position: int) -> TrendlineFamilyOutput:
        if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < len(self.outputs):
            raise ContractValidationError("research replay position is out of range")
        return self.outputs[position]

    def snapshot_summary_at(self, position: int) -> SnapshotSummary:
        from .tables import snapshot_summary

        return snapshot_summary(self.output_at(position).snapshot)


class _RecordingProvider:
    """Record canonical provider outputs without changing candidate semantics."""

    def __init__(self, provider: LineCandidateProvider) -> None:
        self._provider = provider
        self.results: list[CandidateGenerationResult] = []

    def generate(
        self,
        ohlcv: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
        context: Mapping[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        result = self._provider.generate(
            ohlcv,
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            config=config,
            context=context,
        )
        self.results.append(result)
        return result


def build_smoke_ohlcv(*, rows: int = 48) -> pd.DataFrame:
    """Compact deterministic confirmed OHLCV fixture. No network or file read."""

    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 16:
        raise ContractValidationError("smoke fixture rows must be an integer >= 16")
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    close = [100.0 + index_value * 0.05 + math.sin(index_value * math.pi / 3.0) * 2.0 for index_value in range(rows)]
    return pd.DataFrame(
        {
            "open": [value - 0.25 for value in close],
            "high": [value + 0.75 for value in close],
            "low": [value - 0.75 for value in close],
            "close": close,
            "volume": [100.0 + float(index_value) for index_value in range(rows)],
            "complete": True,
        },
        index=index,
    )


def build_smoke_config(*, asset: str = "BTCUSDT", timeframe: str = "1h") -> ResolvedTrendlineFamilyConfig:
    """Local compact config. Never reads or writes YAML."""

    candidate = CandidateConfig(
        lookback_bars=48,
        min_bars=8,
        fractal_left_bars=1,
        fractal_right_bars=1,
        min_pivots_per_side=2,
        min_candidate_quality=0.0,
        birth_quality_threshold=0.0,
    )
    return ResolvedTrendlineFamilyConfig.create(
        asset=asset,
        timeframe=timeframe,
        config_version="research_smoke_v1",
        config=TrendlineFamilyConfig(candidate=candidate),
        field_provenance={"research_lab": "deterministic_smoke_fixture"},
    )


def immutable_research_frame(*, frame: pd.DataFrame, asset: str, timeframe: str) -> ImmutableHistoricalFrame:
    """Reject malformed or incomplete research input through canonical validation."""

    return ImmutableHistoricalFrame(asset=asset, timeframe=timeframe, _frame=frame)


def dataset_summary(dataset: ImmutableHistoricalFrame) -> dict[str, Any]:
    frame = dataset.to_frame()
    return {
        "asset": dataset.asset,
        "timeframe": dataset.timeframe,
        "dataset_hash": dataset.dataset_hash,
        "row_count": dataset.row_count,
        "start": dataset.timestamps[0],
        "end": dataset.timestamps[-1],
        "duplicate_timestamp_count": int(frame.index.duplicated().sum()),
        "missing_value_count": int(frame.isna().sum().sum()),
        "confirmed_bar_status": "all_confirmed",
    }


def run_canonical_replay(
    *,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    provider: LineCandidateProvider | None = None,
    provider_spec: Mapping[str, Any] | None = None,
    research_parameters: Mapping[str, Any] | None = None,
) -> ResearchReplay:
    """Replay only confirmed prefixes. Future rows never enter earlier updates."""

    if dataset.asset != config.asset or dataset.timeframe != config.timeframe:
        raise ContractValidationError("research dataset/config identity mismatch")
    selected_provider = provider or NativeDeterministicLineProvider()
    resolved_provider_spec = _provider_spec(
        provider=selected_provider,
        config=config,
        explicit_spec=provider_spec,
        is_default=provider is None,
    )
    recorder = _RecordingProvider(selected_provider)
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=recorder,
        config=config,
    )
    started = perf_counter()
    outputs = tuple(
        tracker.update(dataset.prefix(position), observed_at=timestamp)
        for position, timestamp in enumerate(dataset.timestamps)
    )
    elapsed_seconds = perf_counter() - started
    context = ResearchRunContext(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        dataset_hash=dataset.dataset_hash,
        model_version=config.model_version,
        config_version=config.config_version,
        resolved_config_hash=config.resolved_config_hash,
        mtf_config_hash=config.mtf_config_hash,
        parameter_policy_hash=parameter_policy_hash(config),
        research_parameters={} if research_parameters is None else research_parameters,
        provider_spec=resolved_provider_spec,
    )
    return ResearchReplay(
        context=context,
        dataset=dataset,
        outputs=outputs,
        candidate_results=tuple(recorder.results),
        runtime_diagnostics={
            "replay_seconds": elapsed_seconds,
            "bars_per_second": 0.0 if elapsed_seconds == 0.0 else dataset.row_count / elapsed_seconds,
            "peak_candidate_count": float(max(len(result.candidates) for result in recorder.results)),
            "peak_active_family_count": float(max(len(output.snapshot.active_families) for output in outputs)),
            "peak_dormant_family_count": float(max(len(output.snapshot.dormant_families) for output in outputs)),
            "peak_event_count": float(max(len(output.snapshot.interaction_events) for output in outputs)),
        },
    )


def replay_prefix_is_causal(
    replay: ResearchReplay,
    *,
    position: int,
    config: ResolvedTrendlineFamilyConfig,
    provider: LineCandidateProvider | None = None,
    provider_spec: Mapping[str, Any] | None = None,
) -> bool:
    """Compare snapshot at T against independent replay truncated at T."""

    expected = replay.output_at(position).snapshot.to_dict()
    prefix = immutable_research_frame(
        frame=replay.dataset.prefix(position),
        asset=replay.dataset.asset,
        timeframe=replay.dataset.timeframe,
    )
    actual = run_canonical_replay(
        dataset=prefix,
        config=config,
        provider=provider,
        provider_spec=provider_spec,
        research_parameters=replay.context.research_parameters,
    ).outputs[-1].snapshot.to_dict()
    return expected == actual


def load_local_ohlcv(path: str, *, timestamp_column: str = "timestamp") -> pd.DataFrame:
    """Load local OHLCV only with explicit timezone-aware UTC timestamps."""

    source = pd.io.common.stringify_path(path)
    if not isinstance(source, str) or not source:
        raise ContractValidationError("local research path must be non-empty")
    frame = pd.read_parquet(source) if source.lower().endswith(".parquet") else pd.read_csv(source)
    timestamps = frame.pop(timestamp_column) if timestamp_column in frame.columns else frame.index
    return _bind_utc_index(frame, timestamps=timestamps, source="local research input")


def normalize_binance_ohlcv(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    closed_before: datetime,
) -> pd.DataFrame:
    """Bind Binance millisecond open times and retain only bars closed by explicit bound."""

    if not isinstance(frame, pd.DataFrame) or "timestamp" not in frame.columns:
        raise ContractValidationError("Binance research input requires a timestamp column")
    if not isinstance(closed_before, datetime):
        raise ContractValidationError("Binance closed_before must be UTC datetime")
    close_bound = pd.Timestamp(closed_before)
    if close_bound.tzinfo is None or close_bound.utcoffset() is None or close_bound.utcoffset().total_seconds() != 0:
        raise ContractValidationError("Binance closed_before must be timezone-aware UTC")
    timestamp_ms = pd.to_numeric(frame["timestamp"], errors="raise")
    if timestamp_ms.isna().any() or (timestamp_ms % 1 != 0).any():
        raise ContractValidationError("Binance timestamp values must be integer milliseconds")
    timestamps = pd.to_datetime(timestamp_ms.astype("int64"), unit="ms", utc=True, errors="raise")
    normalized = _bind_utc_index(frame.drop(columns=["timestamp"]), timestamps=timestamps, source="Binance research input")
    duration = pd.Timedelta(seconds=canonical_timeframe_duration_seconds(timeframe))
    normalized = normalized.loc[normalized.index + duration <= close_bound].copy()
    if normalized.empty:
        raise ContractValidationError("Binance research input has no confirmed bars before closed_before")
    normalized["complete"] = True
    return normalized


def validate_research_mode(
    *,
    smoke_mode: bool,
    fetch_remote: bool,
    local_data_path: str | None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> None:
    """Validate data-source selection; replay, export, and MTF remain independent flags."""

    if not isinstance(smoke_mode, bool) or not isinstance(fetch_remote, bool):
        raise ContractValidationError("research source flags must be boolean")
    if smoke_mode and fetch_remote:
        raise ContractValidationError("SMOKE_MODE and FETCH_REMOTE cannot both be enabled")
    if smoke_mode and local_data_path:
        raise ContractValidationError("SMOKE_MODE and LOCAL_DATA_PATH cannot both be selected")
    if fetch_remote and local_data_path:
        raise ContractValidationError("FETCH_REMOTE and LOCAL_DATA_PATH cannot both be selected")
    if not smoke_mode and not fetch_remote and not local_data_path:
        raise ContractValidationError("select smoke data, local data, or explicit remote fetch")
    if fetch_remote:
        for name, value in (("START", start), ("END", end)):
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
                raise ContractValidationError(f"{name} must be timezone-aware UTC for remote fetch")
        if pd.Timestamp(start) >= pd.Timestamp(end):
            raise ContractValidationError("remote START must be earlier than END")


def validate_research_config(
    config: ResolvedTrendlineFamilyConfig,
    *,
    asset: str,
    timeframe: str,
    require_mtf: bool = False,
) -> ResolvedTrendlineFamilyConfig:
    """Validate an explicit non-smoke research configuration."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("research requires ResolvedTrendlineFamilyConfig")
    if config.asset != asset or config.timeframe != timeframe:
        raise ContractValidationError("research config asset/timeframe mismatch")
    if _is_smoke_fixture_config(config):
        raise ContractValidationError("smoke fixture config is not valid for local or remote research")
    if require_mtf and not config.mtf.enabled:
        raise ContractValidationError("MTF research requires mtf.enabled resolved config")
    return config


def parameter_policy_hash(config: ResolvedTrendlineFamilyConfig) -> str:
    """Hash parameter semantics while allowing asset-specific resolved identities."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("parameter policy requires ResolvedTrendlineFamilyConfig")
    payload = config.to_dict()
    payload.pop("asset", None)
    return deterministic_hash(payload)


def _is_smoke_fixture_config(config: ResolvedTrendlineFamilyConfig) -> bool:
    return (
        config.config_version == "research_smoke_v1"
        or config.field_provenance.get("research_lab") == "deterministic_smoke_fixture"
    )


def _provider_spec(
    *,
    provider: LineCandidateProvider,
    config: ResolvedTrendlineFamilyConfig,
    explicit_spec: Mapping[str, Any] | None,
    is_default: bool,
) -> Mapping[str, Any]:
    if explicit_spec is not None:
        if not isinstance(explicit_spec, Mapping) or not explicit_spec:
            raise ContractValidationError("custom research provider_spec must be a non-empty mapping")
        return dict(explicit_spec)
    if not is_default:
        raise ContractValidationError("custom research providers require explicit provider_spec")
    return {
        "provider": "native_deterministic",
        "provider_class": type(provider).__qualname__,
        "pivot_provider": config.candidate.pivot_provider,
        "fitter": config.candidate.fitter,
    }


def _bind_utc_index(frame: pd.DataFrame, *, timestamps: Any, source: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ContractValidationError(f"{source} must be a DataFrame")
    converted = pd.DatetimeIndex(pd.to_datetime(timestamps, errors="raise"))
    if converted.tz is None:
        raise ContractValidationError(f"{source} timestamps must be timezone-aware UTC")
    if str(converted.tz) not in {"UTC", "UTC+00:00"}:
        raise ContractValidationError(f"{source} timestamps must use UTC offset")
    if not converted.is_monotonic_increasing or converted.has_duplicates:
        raise ContractValidationError(f"{source} timestamps must be strictly ordered and unique")
    result = frame.copy(deep=True)
    result.index = converted
    return result


__all__ = [
    "ResearchReplay",
    "build_smoke_config",
    "build_smoke_ohlcv",
    "dataset_summary",
    "immutable_research_frame",
    "load_local_ohlcv",
    "normalize_binance_ohlcv",
    "parameter_policy_hash",
    "replay_prefix_is_causal",
    "run_canonical_replay",
    "validate_research_mode",
    "validate_research_config",
]
