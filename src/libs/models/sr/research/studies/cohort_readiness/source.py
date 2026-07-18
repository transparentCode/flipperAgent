"""Strict source preparation for the SR-V1.7 development cohort.

The provider boundary is intentionally leaf-only.  Nothing in this module
imports a provider client; the adapter is supplied by the caller or imported
inside :func:`default_provider_adapter` at execution time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import import_module
import json
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Protocol

from pandas import DataFrame

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.artifacts.validator import load_strict_json
from libs.models.sr.research.config.identities import ContentIdentity
from libs.models.sr.research.provenance.repository import resolve_repository_path
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.source.capsules import CapsuleStage, SourceCapsule
from libs.models.sr.research.source.frozen import read_verified_frozen_file

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
_ALLOWED_COLUMNS = frozenset((*_REQUIRED_COLUMNS, "taker_buy_base"))
_CAPSULE_MEMBER_NAMES = ("manifest.json", "source_bars.json")
_CAPSULE_SOURCE_KEYS = {
    "schema_version",
    "stage",
    "source_bundle_id",
    "source_bars_sha256",
    "source_row_count",
    "split_boundary",
    "implementation_commit",
    "bars",
}
_CAPSULE_MANIFEST_KEYS = {
    "schema_version",
    "stage",
    "capsule_id",
    "source_bundle_id",
    "source_bars_sha256",
    "source_row_count",
    "row_count",
    "bars_sha256",
    "first_open_time",
    "last_closed_at",
    "split_boundary",
    "implementation_commit",
    "member",
    "capsule_id_semantic_payload",
    "capsule_id_recomputed_from",
}
_BAR_KEYS = {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}


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
    if type(frame) is not DataFrame:
        raise ContractValidationError("provider result must be exactly pandas.DataFrame")
    if frame.empty or len(frame) != APPROVED_SOURCE_ROWS:
        raise ContractValidationError("provider result must contain exactly 629 rows")
    columns = set(frame.columns)
    if (
        len(columns) != len(frame.columns)
        or not set(_REQUIRED_COLUMNS).issubset(columns)
        or not columns.issubset(_ALLOWED_COLUMNS)
    ):
        raise ContractValidationError("provider result contains unsupported or duplicate columns")
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


def _capsule_timestamp(value: Any, *, field_name: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{field_name} must use strict UTC Z notation")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


def _load_taousdt_development_capsule(
    config: CohortConfig,
    *,
    repo_root: str | Path,
) -> SourceCapsule:
    """Validate exactly the V1.6 development capsule Cohort consumes.

    This is intentionally an explicit frozen-upstream boundary.  Cohort needs
    source bars, not ATR calibration's selection or artifact semantics.
    """

    path = resolve_repository_path(repo_root, config.tao_source_path, field_name="tao_source_path")
    if not path.is_dir() or path.is_symlink():
        raise ContractValidationError("approved TAOUSDT development capsule is missing")
    try:
        members = {item.name for item in path.iterdir()}
    except OSError as exc:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation") from exc
    if members != set(_CAPSULE_MEMBER_NAMES):
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    manifest_path = path / "manifest.json"
    source_path = path / "source_bars.json"
    if manifest_path.is_symlink() or source_path.is_symlink():
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    manifest = load_strict_json(manifest_path, description="approved TAOUSDT development capsule")
    if type(manifest) is not dict or set(manifest) != _CAPSULE_MANIFEST_KEYS:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    member = manifest.get("member")
    if (
        type(member) is not dict
        or set(member) != {"name", "sha256", "byte_length"}
        or member.get("name") != "source_bars.json"
        or member.get("sha256") != config.tao_source_member_sha256
        or type(member.get("byte_length")) is not int
        or isinstance(member.get("byte_length"), bool)
        or member["byte_length"] < 0
    ):
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    source_bytes = read_verified_frozen_file(
        source_path,
        identity=ContentIdentity(sha256=member["sha256"], byte_length=member["byte_length"]),
        description="approved TAOUSDT development capsule source member",
    )
    try:
        source_payload = json.loads(
            source_bytes.decode("utf-8"),
            object_pairs_hook=lambda pairs: _reject_duplicate_keys(pairs),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation") from exc
    if type(source_payload) is not dict or set(source_payload) != _CAPSULE_SOURCE_KEYS:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    if (
        source_payload.get("schema_version") != "1.0"
        or source_payload.get("stage") != CapsuleStage.DEVELOPMENT.value
        or source_payload.get("implementation_commit") != config.tao_source_implementation_commit
        or source_payload.get("source_bundle_id") != config.tao_source_bundle_id
        or manifest.get("stage") != CapsuleStage.DEVELOPMENT.value
        or manifest.get("implementation_commit") != config.tao_source_implementation_commit
    ):
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    raw_bars = source_payload.get("bars")
    if type(raw_bars) is not list:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation")
    bars: list[SourceBar] = []
    previous: SourceBar | None = None
    for index, raw in enumerate(raw_bars):
        if type(raw) is not dict or set(raw) != _BAR_KEYS:
            raise ContractValidationError("approved TAOUSDT development capsule failed validation")
        try:
            bar = SourceBar(
                open_time=_capsule_timestamp(raw["open_time"], field_name=f"capsule.bars[{index}].open_time"),
                closed_at=_capsule_timestamp(raw["closed_at"], field_name=f"capsule.bars[{index}].closed_at"),
                open=raw["open"],
                high=raw["high"],
                low=raw["low"],
                close=raw["close"],
                volume=raw["volume"],
                bar_id=raw["bar_id"],
            )
        except (ContractValidationError, TypeError, ValueError) as exc:
            raise ContractValidationError("approved TAOUSDT development capsule failed validation") from exc
        if previous is not None and bar.open_time != previous.open_time + timedelta(days=1):
            raise ContractValidationError("approved TAOUSDT development capsule failed validation")
        bars.append(bar)
        previous = bar
    try:
        capsule = SourceCapsule(
            stage=CapsuleStage.DEVELOPMENT,
            source_bundle_id=source_payload["source_bundle_id"],
            source_bars_sha256=source_payload["source_bars_sha256"],
            source_row_count=source_payload["source_row_count"],
            split_boundary=_capsule_timestamp(source_payload["split_boundary"], field_name="split_boundary"),
            implementation_commit=source_payload["implementation_commit"],
            bars=tuple(bars),
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError("approved TAOUSDT development capsule failed validation") from exc
    if (
        capsule.capsule_id != config.tao_source_id
        or path.name != config.tao_source_id
        or manifest.get("capsule_id") != capsule.capsule_id
        or manifest.get("capsule_id_recomputed_from") != capsule.identity_payload()
    ):
        raise ContractValidationError("TAOUSDT capsule identity is not the approved V1.6 development prefix")
    return capsule


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_taousdt_source(
    config: CohortConfig,
    *,
    repo_root: str | Path,
    resolved_sr_config_hash: str,
    resolved_input_hash: str,
) -> AssetSource:
    """Load the published V1.6 capsule directly; never rebuild from its parent."""
    capsule = _load_taousdt_development_capsule(config, repo_root=repo_root)
    if (
        capsule.capsule_id != TAO_SOURCE_ID
        or capsule.source_bundle_id != TAO_SOURCE_BUNDLE_ID
        or len(capsule.bars) != config.source_row_count
    ):
        raise ContractValidationError("TAOUSDT capsule identity is not the approved V1.6 development prefix")
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
    resolved_sr_field_provenance: dict[str, tuple[tuple[str, str], ...]],
    resolved_input_field_provenance: dict[str, tuple[tuple[str, str], ...]],
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
        resolved_sr_field_provenance=tuple(
            (asset, resolved_sr_field_provenance[asset]) for asset in APPROVED_ASSETS
        ),
        resolved_input_field_provenance=tuple(
            (asset, resolved_input_field_provenance[asset]) for asset in APPROVED_ASSETS
        ),
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
