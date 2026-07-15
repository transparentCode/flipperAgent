"""Strict source preparation for the SR-V1.7 development cohort.

The provider boundary is intentionally leaf-only.  Nothing in this module
imports a provider client; the adapter is supplied by the caller or imported
inside :func:`default_provider_adapter` at execution time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import import_module
from numbers import Integral, Real
from pathlib import Path
from hashlib import sha256
from typing import Any, Protocol

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.scripts.atr_calibration.config import load_calibration_config
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage
from libs.models.sr.scripts.atr_calibration.source import (
    load_capsule,
    validate_development_prefix,
)
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar

from .config import CohortConfig
from .contracts import (
    ADAPTER_LIMIT,
    APPROVED_ASSETS,
    APPROVED_SOURCE_ROWS,
    AssetSource,
    SourceBundle,
    TAO_BARS_SHA256,
    TAO_SOURCE_BUNDLE_ID,
    TAO_SOURCE_ID,
    bars_sha256,
    grid_sha256,
)


DAY_MS = 86_400_000
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class HistoricalOHLCVAdapter(Protocol):
    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> Any:
        """Fetch exactly one bounded provider response."""


def epoch_milliseconds(timestamp: datetime) -> int:
    timestamp = timestamp.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = timestamp - epoch
    return delta.days * DAY_MS + delta.seconds * 1000 + delta.microseconds // 1000


def effective_provider_request_bounds(config: CohortConfig) -> tuple[int, int]:
    return epoch_milliseconds(config.source_since), epoch_milliseconds(config.source_until) - 1


def _as_float(value: Any, *, field_name: str, row_number: int) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ContractValidationError(f"row {row_number} {field_name} must be numeric without coercion")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ContractValidationError(f"row {row_number} {field_name} must be finite") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise ContractValidationError(f"row {row_number} {field_name} must be finite")
    return 0.0 if result == 0.0 else result


def _timestamp_ms(value: Any, *, row_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ContractValidationError(f"row {row_number} timestamp must be an integer millisecond")
    return int(value)


def _expected_bar_id(config: CohortConfig, asset: str, timestamp_ms: int) -> str:
    return f"{config.venue}:{asset}:{config.timeframe}:{timestamp_ms}"


def validate_provider_frame(
    frame: Any,
    *,
    config: CohortConfig,
    asset: str,
    expected_grid: tuple[datetime, ...],
    resolved_sr_config_hash: str,
    resolved_input_hash: str,
) -> AssetSource:
    """Validate one adapter response without sorting, repair, or coercion."""
    if asset not in APPROVED_ASSETS or asset == "TAOUSDT":
        raise ContractValidationError("provider validation is only for BTCUSDT/ETHUSDT/SOLUSDT")
    if type(frame).__name__ != "DataFrame" or type(frame).__module__ != "pandas":
        raise ContractValidationError("provider result must be exactly pandas.DataFrame")
    if frame.empty or len(frame) != APPROVED_SOURCE_ROWS:
        raise ContractValidationError("provider result must contain exactly 629 rows")
    if len(set(frame.columns)) != len(frame.columns) or not set(_REQUIRED_COLUMNS).issubset(set(frame.columns)):
        raise ContractValidationError("provider result must contain unique timestamp/open/high/low/close/volume columns")
    if len(expected_grid) != APPROVED_SOURCE_ROWS:
        raise ContractValidationError("expected source grid must contain 629 timestamps")
    requested_since_ms, requested_until_ms = effective_provider_request_bounds(config)
    bars = []
    previous_ms: int | None = None
    rows = frame.loc[:, _REQUIRED_COLUMNS].itertuples(index=False, name=None)
    for row_number, row in enumerate(rows):
        timestamp_ms = _timestamp_ms(row[0], row_number=row_number)
        expected_time = expected_grid[row_number]
        if timestamp_ms != epoch_milliseconds(expected_time):
            raise ContractValidationError(f"provider row {row_number} does not match the exact TAOUSDT UTC grid")
        if timestamp_ms < requested_since_ms or timestamp_ms >= requested_until_ms:
            raise ContractValidationError(f"provider row {row_number} is outside the requested source window")
        if previous_ms is not None and timestamp_ms - previous_ms != DAY_MS:
            raise ContractValidationError("provider timestamps must be strictly contiguous daily values")
        previous_ms = timestamp_ms
        open_price = _as_float(row[1], field_name="open", row_number=row_number)
        high = _as_float(row[2], field_name="high", row_number=row_number)
        low = _as_float(row[3], field_name="low", row_number=row_number)
        close = _as_float(row[4], field_name="close", row_number=row_number)
        volume = _as_float(row[5], field_name="volume", row_number=row_number)
        if open_price <= 0 or high <= 0 or low <= 0 or close <= 0 or volume < 0:
            raise ContractValidationError(f"provider row {row_number} contains non-positive OHLC or negative volume")
        if low > high or not low <= open_price <= high or not low <= close <= high:
            raise ContractValidationError(f"provider row {row_number} has invalid OHLC relationships")
        open_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        closed_at = open_time + timedelta(days=1)
        if closed_at > config.source_until:
            raise ContractValidationError(f"provider row {row_number} causal close exceeds source boundary")
        bars.append(
            SourceBar(
                open_time=open_time,
                closed_at=closed_at,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                bar_id=_expected_bar_id(config, asset, timestamp_ms),
            )
        )
    source_bars = tuple(bars)
    source_id = deterministic_hash({
        "schema_version": "1.0",
        "asset": asset,
        "venue": config.venue,
        "timeframe": config.timeframe,
        "bars_sha256": bars_sha256(source_bars),
        "grid_sha256": grid_sha256(source_bars),
        "requested_since": utc_isoformat(config.source_since),
        "requested_until": utc_isoformat(config.source_until),
        "source_kind": "provider",
    })
    return AssetSource(
        asset=asset,
        venue=config.venue,
        timeframe=config.timeframe,
        source_id=source_id,
        source_bundle_id=source_id,
        bars_sha256=bars_sha256(source_bars),
        row_count=len(source_bars),
        first_open_time=source_bars[0].open_time,
        last_closed_at=source_bars[-1].closed_at,
        grid_sha256=grid_sha256(source_bars),
        requested_since=config.source_since,
        requested_until=config.source_until,
        provider_calls=1,
        provider_request_since_ms=requested_since_ms,
        provider_request_until_ms=requested_until_ms,
        adapter_limit=ADAPTER_LIMIT,
        source_kind="provider",
        resolved_sr_config_hash=resolved_sr_config_hash,
        resolved_input_hash=resolved_input_hash,
        bars=source_bars,
    )


def load_taousdt_source(
    config: CohortConfig,
    *,
    repo_root: str | Path,
    resolved_sr_config_hash: str,
    resolved_input_hash: str,
) -> AssetSource:
    """Load the published V1.6 capsule directly; never rebuild from its parent."""
    root = Path(repo_root).resolve()
    path = (root / config.tao_source_path).resolve()
    if root not in path.parents or not path.is_dir() or path.is_symlink():
        raise ContractValidationError("approved TAOUSDT development capsule is missing")
    v16_config_path = root / "configs/sr_trials/taousdt_1d_atr_calibration.yaml"
    v16_config = load_calibration_config(v16_config_path)
    try:
        capsule = load_capsule(
            path,
            expected_stage=CapsuleStage.DEVELOPMENT,
            expected_source=v16_config,
            expected_implementation_commit=config.tao_source_implementation_commit,
        )
        validate_development_prefix(capsule)
    except ContractValidationError:
        raise
    except (OSError, TypeError, ValueError, KeyError, IndexError) as exc:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation") from exc
    if capsule.capsule_id != TAO_SOURCE_ID or capsule.source_bundle_id != TAO_SOURCE_BUNDLE_ID or capsule.source_bars_sha256 != v16_config.source_bars_sha256 or len(capsule.bars) != config.source_row_count:
        raise ContractValidationError("TAOUSDT capsule identity is not the approved V1.6 development prefix")
    source_member = path / "source_bars.json"
    if sha256(source_member.read_bytes()).hexdigest() != config.tao_source_member_sha256:
        raise ContractValidationError("TAOUSDT source member hash does not match the approved capsule")
    source_bars = tuple(capsule.bars)
    if bars_sha256(source_bars) != TAO_BARS_SHA256:
        raise ContractValidationError("TAOUSDT development bars hash does not match the frozen prefix")
    return AssetSource(
        asset="TAOUSDT",
        venue=config.venue,
        timeframe=config.timeframe,
        source_id=TAO_SOURCE_ID,
        source_bundle_id=TAO_SOURCE_BUNDLE_ID,
        bars_sha256=TAO_BARS_SHA256,
        row_count=len(source_bars),
        first_open_time=source_bars[0].open_time,
        last_closed_at=source_bars[-1].closed_at,
        grid_sha256=grid_sha256(source_bars),
        requested_since=config.source_since,
        requested_until=config.source_until,
        provider_calls=0,
        provider_request_since_ms=None,
        provider_request_until_ms=None,
        adapter_limit=ADAPTER_LIMIT,
        source_kind="frozen_v1_6",
        resolved_sr_config_hash=resolved_sr_config_hash,
        resolved_input_hash=resolved_input_hash,
        bars=source_bars,
    )


async def fetch_new_asset_sources(
    config: CohortConfig,
    *,
    adapter: HistoricalOHLCVAdapter,
    expected_grid: tuple[datetime, ...],
    resolved_hashes: dict[str, tuple[str, str]],
) -> tuple[AssetSource, ...]:
    if adapter is None:
        raise ContractValidationError("provider adapter is required for source preparation")
    since_ms, until_ms = effective_provider_request_bounds(config)
    sources: list[AssetSource] = []
    for asset in APPROVED_ASSETS[1:]:
        frame = await adapter.get_historical_ohlcv(
            asset,
            config.timeframe,
            since=since_ms,
            until=until_ms,
            limit=config.provider_limit,
        )
        sr_hash, input_hash = resolved_hashes[asset]
        sources.append(validate_provider_frame(frame, config=config, asset=asset, expected_grid=expected_grid, resolved_sr_config_hash=sr_hash, resolved_input_hash=input_hash))
    return tuple(sources)


def build_source_bundle(
    config: CohortConfig,
    *,
    implementation_commit: str,
    tao_source: AssetSource,
    new_sources: tuple[AssetSource, ...],
    resolved_hashes: dict[str, tuple[str, str]],
) -> SourceBundle:
    sources = (tao_source, *new_sources)
    if tuple(source.asset for source in sources) != APPROVED_ASSETS:
        raise ContractValidationError("source bundle assets are not canonical")
    return SourceBundle(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        assets=sources,
        resolved_sr_config_hashes=tuple((asset, resolved_hashes[asset][0]) for asset in APPROVED_ASSETS),
        resolved_input_hashes=tuple((asset, resolved_hashes[asset][1]) for asset in APPROVED_ASSETS),
    )


def default_provider_adapter() -> HistoricalOHLCVAdapter:
    """Construct the approved adapter behind a lazy import boundary."""
    adapter_module = import_module("apps.ingestion_app.adapters.binance_native")
    return adapter_module.BinanceNativeAdapter()


__all__ = [
    "HistoricalOHLCVAdapter", "build_source_bundle", "default_provider_adapter",
    "effective_provider_request_bounds", "epoch_milliseconds", "fetch_new_asset_sources",
    "load_taousdt_source", "validate_provider_frame",
]
