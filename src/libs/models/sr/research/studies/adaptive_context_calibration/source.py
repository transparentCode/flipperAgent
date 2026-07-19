"""Immutable V2.3 source binding with a lazy, one-call provider leaf."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.cohort.artifacts import load_source_bundle
from .config import AdaptiveContextCalibrationConfig
from .contracts import (
    CANONICAL_COHORTS,
    INTERVAL,
    IntervalBar,
    V23SourceBundle,
    V23SourceMember,
    interval_bars_sha256,
    interval_grid_sha256,
)


class BlockedSourceError(ContractValidationError):
    """A source response violated the immutable V2.3 boundary."""


def _epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _frozen_members(
    config: AdaptiveContextCalibrationConfig,
    *,
    repo_root: str | Path,
) -> tuple[V23SourceMember, ...]:
    path = Path(repo_root) / config.frozen_1d.bundle_path
    outer = load_source_bundle(path, expected_bundle_id=config.frozen_1d.outer_bundle_id)
    if outer.implementation_commit != config.frozen_1d.implementation_commit:
        raise ContractValidationError("frozen 1d outer implementation identity mismatch")
    result = []
    for spec in config.frozen_1d.members:
        selected = tuple(item for item in outer.assets if item.asset == spec.asset)
        if len(selected) != 1:
            raise ContractValidationError(f"frozen 1d source has no unique {spec.asset} member")
        actual = selected[0]
        expected_identity = (spec.source_id, spec.source_bundle_id, spec.bars_sha256, spec.grid_sha256, spec.row_count, spec.start, spec.end)
        actual_identity = (actual.source_id, actual.source_bundle_id, actual.bars_sha256, actual.grid_sha256, actual.row_count, actual.first_open_time, actual.last_closed_at)
        if actual_identity != expected_identity or actual.venue != config.frozen_1d.venue or actual.timeframe != config.frozen_1d.timeframe:
            raise ContractValidationError(f"frozen 1d {spec.asset} identity mismatch")
        if actual.provider_calls not in (0, 1):
            raise ContractValidationError(f"frozen 1d {spec.asset} provider-call metadata is invalid")
        result.append(
            V23SourceMember(
                asset=actual.asset,
                venue=actual.venue,
                timeframe=actual.timeframe,
                source_id=actual.source_id,
                source_bundle_id=actual.source_bundle_id,
                bars_sha256=actual.bars_sha256,
                grid_sha256=actual.grid_sha256,
                row_count=actual.row_count,
                first_open_time=actual.first_open_time,
                last_closed_at=actual.last_closed_at,
                requested_since=actual.first_open_time,
                requested_until=actual.last_closed_at,
                provider_calls=0,
                provider_request_since_ms=None,
                provider_request_until_ms=None,
                adapter_limit=config.provider_12h.adapter_limit,
                source_kind="frozen_v1_7",
                implementation_commit=config.frozen_1d.implementation_commit,
                bars=actual.bars,
            )
        )
    return tuple(result)


def _blocked(message: str, exc: BaseException | None = None) -> BlockedSourceError:
    del exc
    return BlockedSourceError(f"BLOCKED_SOURCE: {message}")


def _row_values(row: Any, *, index: int) -> tuple[Any, ...]:
    try:
        values = tuple(row)
    except TypeError as exc:
        raise _blocked(f"row {index} is not iterable", exc) from exc
    if len(values) != 6:
        raise _blocked(f"row {index} has an invalid column count")
    return values


def canonicalize_12h_response(
    response: Any,
    *,
    asset: str,
    config: AdaptiveContextCalibrationConfig,
    implementation_commit: str,
) -> V23SourceMember:
    """Validate one adapter response without sorting, repairing, or filtering."""

    expected_columns = ("timestamp", "open", "high", "low", "close", "volume")
    try:
        columns = tuple(response.columns)
        rows = tuple(response.itertuples(index=False, name=None))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _blocked("provider response is not a tabular OHLCV response", exc) from exc
    if columns != expected_columns:
        raise _blocked("provider response columns are missing, additional, or reordered")
    protocol = config.provider_12h
    if len(rows) != protocol.expected_rows:
        raise _blocked("provider response row count does not equal the approved 1000 rows")
    bars: list[IntervalBar] = []
    expected_open = protocol.start
    seen_timestamps: set[int] = set()
    for index, row in enumerate(rows):
        values = _row_values(row, index=index)
        timestamp, open_value, high, low, close, volume = values
        try:
            if isinstance(timestamp, bool):
                raise ValueError("boolean timestamp")
            timestamp_ms = int(timestamp)
            if float(timestamp) != timestamp_ms:
                raise ValueError("non-integral timestamp")
            actual_open = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise _blocked(f"provider row {index} timestamp is invalid", exc) from exc
        expected_ms = _epoch_ms(expected_open)
        if timestamp_ms in seen_timestamps or timestamp_ms != expected_ms or actual_open != expected_open:
            raise _blocked(f"provider row {index} is missing, duplicate, unordered, or off-grid")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in values[1:]):
            raise _blocked(f"provider row {index} contains a non-finite OHLCV value")
        bar_id = f"{protocol.venue}:{asset}:{protocol.timeframe}:{timestamp_ms}"
        try:
            bars.append(IntervalBar(actual_open, actual_open + INTERVAL, float(open_value), float(high), float(low), float(close), float(volume), bar_id))
        except (ContractValidationError, TypeError, ValueError, OverflowError) as exc:
            raise _blocked(f"provider row {index} OHLCV values are invalid", exc) from exc
        seen_timestamps.add(timestamp_ms)
        expected_open += INTERVAL
    if expected_open != protocol.end:
        raise _blocked("provider response does not terminate at the approved cutoff")
    interval_bars = tuple(bars)
    bars_hash = interval_bars_sha256(interval_bars)
    grid_hash = interval_grid_sha256(interval_bars)
    request_identity = {
        "adapter": protocol.adapter,
        "asset": asset,
        "venue": protocol.venue,
        "timeframe": protocol.timeframe,
        "since_ms": _epoch_ms(protocol.start),
        "until_ms": _epoch_ms(protocol.end) - 1,
        "limit": protocol.adapter_limit,
        "bars_sha256": bars_hash,
        "grid_sha256": grid_hash,
    }
    return V23SourceMember(
        asset=asset,
        venue=protocol.venue,
        timeframe=protocol.timeframe,
        source_id=deterministic_hash({"source": request_identity}),
        source_bundle_id=deterministic_hash({"member": request_identity}),
        bars_sha256=bars_hash,
        grid_sha256=grid_hash,
        row_count=len(interval_bars),
        first_open_time=protocol.start,
        last_closed_at=protocol.end,
        requested_since=protocol.start,
        requested_until=protocol.end,
        provider_calls=1,
        provider_request_since_ms=_epoch_ms(protocol.start),
        provider_request_until_ms=_epoch_ms(protocol.end) - 1,
        adapter_limit=protocol.adapter_limit,
        source_kind="provider",
        implementation_commit=implementation_commit,
        bars=interval_bars,
    )


async def fetch_12h_asset(
    asset: str,
    *,
    config: AdaptiveContextCalibrationConfig,
    implementation_commit: str,
    adapter_factory: Callable[[], Any] | None = None,
) -> V23SourceMember:
    """Make exactly one bounded provider call for one approved asset."""

    if asset not in config.assets:
        raise ContractValidationError("provider asset is outside V2.3 scope")
    if adapter_factory is None:
        from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter

        adapter_factory = BinanceNativeAdapter
    adapter = adapter_factory()
    protocol = config.provider_12h
    try:
        response = await adapter.get_historical_ohlcv(
            asset,
            protocol.timeframe,
            since=_epoch_ms(protocol.start),
            until=_epoch_ms(protocol.end) - 1,
            limit=protocol.adapter_limit,
        )
    except Exception as exc:
        raise _blocked(f"provider request failed for {asset}", exc) from exc
    return canonicalize_12h_response(
        response,
        asset=asset,
        config=config,
        implementation_commit=implementation_commit,
    )


async def fetch_and_publish_source_bundle(
    config: AdaptiveContextCalibrationConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
    adapter_factory: Callable[[], Any] | None = None,
) -> tuple[str, Path]:
    """Bind frozen 1d members and fetch each 12h member once in canonical order."""

    frozen = _frozen_members(config, repo_root=repo_root)
    provider_members = []
    for asset in config.assets:
        provider_members.append(
            await fetch_12h_asset(
                asset,
                config=config,
                implementation_commit=implementation_commit,
                adapter_factory=adapter_factory,
            )
        )
    members_by_key = {(item.asset, item.timeframe): item for item in (*frozen, *provider_members)}
    ordered = tuple(members_by_key[key] for key in CANONICAL_COHORTS)
    bundle = V23SourceBundle(implementation_commit=implementation_commit, config_hash=config.config_hash, assets=ordered)
    from .artifacts import publish_source_bundle

    return publish_source_bundle(bundle, output_root=Path(repo_root) / config.artifact.output_root)


def load_v23_source_bundle(path: str | Path) -> V23SourceBundle:
    from .artifacts import load_source_bundle

    return load_source_bundle(path)


def source_bundle_for_offline_evaluation(
    config: AdaptiveContextCalibrationConfig,
    *,
    repo_root: str | Path,
    source_bundle_path: str | Path,
) -> V23SourceBundle:
    del repo_root
    bundle = load_v23_source_bundle(source_bundle_path)
    if bundle.config_hash != config.config_hash:
        raise ContractValidationError("V2.3 source bundle config identity mismatch")
    if tuple((item.asset, item.timeframe) for item in bundle.assets) != CANONICAL_COHORTS:
        raise ContractValidationError("V2.3 source bundle cohort order mismatch")
    if bundle.assets[0].bars[0].open_time < config.frozen_1d.members[0].start:
        raise ContractValidationError("V2.3 source bundle starts before approved frozen history")
    return bundle


__all__ = [
    "BlockedSourceError",
    "canonicalize_12h_response",
    "fetch_12h_asset",
    "fetch_and_publish_source_bundle",
    "load_v23_source_bundle",
    "source_bundle_for_offline_evaluation",
]
