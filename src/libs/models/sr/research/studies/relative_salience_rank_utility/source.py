"""V2.4 frozen-history loading and one-shot fresh-source acquisition."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import math
from pathlib import Path
from typing import Any, Callable

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.artifacts.path_safety import reject_symlink_components, require_regular_file
from libs.models.sr.research.artifacts.validator import load_strict_json

from .config import COHORTS, END, RelativeSalienceRankConfig, START
from .contracts import IntervalBar, SourceBundle, SourceMember, bars_sha256, grid_sha256


class BlockedSourceError(ContractValidationError):
    """Raised when an authorized source response violates the frozen protocol."""


_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "taker_buy_base")


def _blocked(message: str, exc: BaseException | None = None) -> BlockedSourceError:
    del exc
    return BlockedSourceError(f"BLOCKED_SOURCE: {message}")


def _cadence(timeframe: str) -> timedelta:
    if timeframe == "1d":
        return timedelta(days=1)
    if timeframe == "12h":
        return timedelta(hours=12)
    raise ContractValidationError("unsupported V2.4 timeframe")


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{field} must use UTC Z notation")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{field} must be an ISO UTC timestamp") from exc


def _parse_bars(payload: Any, *, asset: str, timeframe: str) -> tuple[IntervalBar, ...]:
    if type(payload) is not list or not payload:
        raise ContractValidationError("frozen source bars must be a non-empty list")
    bars = []
    for index, item in enumerate(payload):
        if type(item) is not dict or set(item) != {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}:
            raise ContractValidationError(f"frozen source bar {index} schema mismatch")
        try:
            bar = IntervalBar(
                _parse_timestamp(item["open_time"], field=f"bars[{index}].open_time"),
                _parse_timestamp(item["closed_at"], field=f"bars[{index}].closed_at"),
                item["open"], item["high"], item["low"], item["close"], item["volume"], item["bar_id"],
            )
        except (ContractValidationError, TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError(f"frozen source bar {index} is invalid") from exc
        expected_id = f"binance_usdm:{asset}:{timeframe}:{int(bar.open_time.timestamp() * 1000)}"
        if bar.bar_id != expected_id:
            raise ContractValidationError(f"frozen source bar {index} identity mismatch")
        bars.append(bar)
    return tuple(bars)


def load_v23_history(
    config: RelativeSalienceRankConfig,
    *,
    repo_root: str | Path,
) -> dict[tuple[str, str], tuple[IntervalBar, ...]]:
    """Load only the immutable V2.3 source as causal warmup/history."""

    if type(config) is not RelativeSalienceRankConfig:
        raise ContractValidationError("V2.4 history loading requires typed configuration")
    relative = config.payload["history"]["v2_3_source_bundle_path"]
    root = Path(repo_root)
    bundle = root / relative
    reject_symlink_components(bundle, description="V2.3 history bundle")
    if not bundle.is_dir() or bundle.is_symlink():
        raise ContractValidationError("V2.3 history bundle must be a real directory")
    expected_names = {"manifest.json", *(f"{asset}_{timeframe}.json" for asset, timeframe in COHORTS)}
    try:
        names = {item.name for item in bundle.iterdir()}
    except OSError as exc:
        raise ContractValidationError("V2.3 history bundle cannot be read") from exc
    if names != expected_names:
        raise ContractValidationError("V2.3 history bundle member set mismatch")
    manifest_path = bundle / "manifest.json"
    require_regular_file(manifest_path, description="V2.3 history manifest")
    manifest = load_strict_json(manifest_path, description="V2.3 history manifest")
    if type(manifest) is not dict or manifest.get("bundle_id") != config.payload["history"]["v2_3_source_bundle_id"] or bundle.name != manifest.get("bundle_id"):
        raise ContractValidationError("V2.3 history bundle identity mismatch")
    semantic = manifest.get("bundle_id_semantic_payload")
    if type(semantic) is not dict or semantic.get("stage") != "development":
        raise ContractValidationError("V2.3 history manifest stage mismatch")
    metadata = semantic.get("members")
    expected_member_names = tuple(f"{asset}_{timeframe}.json" for asset, timeframe in COHORTS)
    if type(metadata) is not list or {item.get("name") for item in metadata if type(item) is dict} != set(expected_member_names):
        raise ContractValidationError("V2.3 history member metadata mismatch")
    metadata_by_name = {item["name"]: item for item in metadata if type(item) is dict}
    result: dict[tuple[str, str], tuple[IntervalBar, ...]] = {}
    for asset, timeframe in COHORTS:
        path = bundle / f"{asset}_{timeframe}.json"
        require_regular_file(path, description=f"V2.3 history {asset}/{timeframe}")
        data = path.read_bytes()
        member = metadata_by_name[path.name]
        if type(member) is not dict or set(member) != {"name", "sha256", "byte_length"} or sha256(data).hexdigest() != member["sha256"] or len(data) != member["byte_length"]:
            raise ContractValidationError("V2.3 history member byte identity mismatch")
        payload = load_strict_json(path, description=f"V2.3 history {asset}/{timeframe}")
        if type(payload) is not dict or payload.get("asset") != asset or payload.get("timeframe") != timeframe:
            raise ContractValidationError("V2.3 history member identity mismatch")
        bars = _parse_bars(payload.get("bars"), asset=asset, timeframe=timeframe)
        if payload.get("bars_sha256") != bars_sha256(bars) or payload.get("grid_sha256") != grid_sha256(bars):
            raise ContractValidationError("V2.3 history bar identity mismatch")
        result[(asset, timeframe)] = bars
    return result


def canonicalize_provider_response(
    response: Any,
    *,
    asset: str,
    timeframe: str,
    config: RelativeSalienceRankConfig,
) -> tuple[IntervalBar, ...]:
    """Fail closed on an unrepairable provider frame; never sort or filter."""

    if (asset, timeframe) not in COHORTS:
        raise ContractValidationError("provider cohort is outside V2.4 scope")
    try:
        columns = tuple(response.columns)
        rows = tuple(response.itertuples(index=False, name=None))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _blocked("provider response is not a tabular OHLCV response", exc) from exc
    if columns != _COLUMNS:
        raise _blocked("provider response columns are missing, additional, or reordered")
    expected_rows = config.payload["provider"]["expected_rows"][timeframe]
    if len(rows) != expected_rows:
        raise _blocked("provider response row count does not match approved cohort")
    cadence = _cadence(timeframe)
    expected_open = START
    bars = []
    for index, row in enumerate(rows):
        if type(row) is not tuple or len(row) != len(_COLUMNS):
            raise _blocked(f"provider row {index} has invalid columns")
        timestamp, open_value, high, low, close, volume, taker_buy_base = row
        try:
            if isinstance(timestamp, bool):
                raise ValueError("boolean timestamp")
            millis = int(timestamp)
            if float(timestamp) != millis:
                raise ValueError("non-integral timestamp")
            open_time = datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)
            numeric = tuple(float(value) for value in (open_value, high, low, close, volume, taker_buy_base))
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise _blocked(f"provider row {index} contains invalid values", exc) from exc
        if open_time != expected_open or not all(math.isfinite(value) for value in numeric) or numeric[-1] < 0.0:
            raise _blocked(f"provider row {index} is off-grid or non-finite")
        try:
            bars.append(IntervalBar(open_time, open_time + cadence, *numeric[:5], f"binance_usdm:{asset}:{timeframe}:{millis}"))
        except (ContractValidationError, TypeError, ValueError, OverflowError) as exc:
            raise _blocked(f"provider row {index} OHLCV values are invalid", exc) from exc
        expected_open += cadence
    if expected_open != END:
        raise _blocked("provider response does not terminate at approved cutoff")
    return tuple(bars)


async def fetch_fresh_member(
    asset: str,
    timeframe: str,
    *,
    config: RelativeSalienceRankConfig,
    adapter_factory: Callable[[], Any] | None = None,
) -> tuple[IntervalBar, ...]:
    """Make precisely one authorized provider request for an approved cohort."""

    if adapter_factory is None:
        from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
        adapter_factory = BinanceNativeAdapter
    adapter = adapter_factory()
    try:
        frame = await adapter.get_historical_ohlcv(asset, timeframe, since=int(START.timestamp() * 1000), until=int(END.timestamp() * 1000) - 1, limit=config.payload["provider"]["limit"])
    except Exception as exc:
        raise _blocked(f"provider request failed for {asset}/{timeframe}", exc) from exc
    return canonicalize_provider_response(frame, asset=asset, timeframe=timeframe, config=config)


async def fetch_and_freeze_source(
    config: RelativeSalienceRankConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
    adapter_factory: Callable[[], Any] | None = None,
) -> SourceBundle:
    """Perform six calls in canonical order, stopping immediately on any failure."""

    history = load_v23_history(config, repo_root=repo_root)
    fresh: dict[tuple[str, str], tuple[IntervalBar, ...]] = {}
    for asset, timeframe in COHORTS:
        fresh[(asset, timeframe)] = await fetch_fresh_member(asset, timeframe, config=config, adapter_factory=adapter_factory)
    return SourceBundle(implementation_commit, config.config_hash, tuple(SourceMember(asset, timeframe, history[(asset, timeframe)], fresh[(asset, timeframe)], 1, "provider") for asset, timeframe in COHORTS))


def fetch_and_freeze_source_sync(*args: Any, **kwargs: Any) -> SourceBundle:
    """CLI-safe synchronous wrapper; rejects invocation under a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_and_freeze_source(*args, **kwargs))
    raise ContractValidationError("V2.4 source fetch cannot run inside an active event loop")


__all__ = ["BlockedSourceError", "canonicalize_provider_response", "fetch_and_freeze_source", "fetch_and_freeze_source_sync", "load_v23_history"]
