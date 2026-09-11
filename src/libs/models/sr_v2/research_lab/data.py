"""Injected Binance USD-M historical loader and exploratory cache boundary."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from libs.market_data import BINANCE_KLINE_PAGE_LIMIT

from ..config.schema import TIMEFRAME_DURATIONS
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..features.time import grid_for
from ..research.source import SourceBarRecord, SourceManifest, load_source_jsonl

RESEARCH_CACHE_SCHEMA_VERSION = 2


class HistoricalAdapter(Protocol):
    async def get_historical_ohlcv(
        self, symbol: str, timeframe: str, **kwargs: Any
    ) -> Any: ...


@dataclass(slots=True)
class ProviderCallAccounting:
    """Per-loader accounting; it is never persisted as authorization."""

    calls: int = 0
    pages: int = 0

    @property
    def provider_calls(self) -> int:
        return self.calls


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchDataResult:
    manifest: SourceManifest
    records: tuple[SourceBarRecord, ...]
    cache_path: Path | None
    provider_calls: int
    source_mode: str
    manifest_path: Path | None = None
    total_provider_calls: int = 0
    cache_access_mode: str = "CACHE_ONLY"
    origin_mode: str = ""
    acquisition_cutoff: datetime | None = None
    acquisition_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.source_mode not in {"CACHE_ONLY", "BINANCE_USDM"}:
            raise ValueError("research result source_mode is unsupported")
        if self.cache_access_mode not in {"CACHE_ONLY", "PROVIDER_FETCH"}:
            raise ValueError("research result cache_access_mode is unsupported")
        if not isinstance(self.origin_mode, str) or not self.origin_mode.strip():
            raise ValueError("research result must retain authenticated origin mode")
        if (
            self.acquisition_cutoff is None
            or self.acquisition_cutoff.tzinfo is None
            or self.acquisition_cutoff.utcoffset()
            != UTC.utcoffset(self.acquisition_cutoff)
        ):
            raise ValueError("research result must retain one UTC acquisition cutoff")
        if (
            self.acquisition_evidence_sha256 is None
            or len(self.acquisition_evidence_sha256) != 64
        ):
            raise ValueError(
                "research result must retain acquisition evidence identity"
            )
        try:
            int(self.acquisition_evidence_sha256, 16)
        except ValueError as exc:
            raise ValueError("acquisition evidence identity must be SHA-256") from exc

    @property
    def manifest_sha256(self) -> str:
        return self.manifest.source_sha256

    @property
    def manifest_file_sha256(self) -> str | None:
        if self.manifest_path is None:
            return None
        return hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()

    @property
    def bars(self) -> tuple[SRBar, ...]:
        return tuple(item.bar for item in self.records)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSourceSetManifest:
    """Authenticated identity for the exact multi-timeframe cache set."""

    manifest_id: str
    source_sha256: str
    records: int
    venue: str
    instrument_ids: tuple[str, ...]
    timeframes: tuple[str, ...]
    entries: tuple[Mapping[str, Any], ...]
    source_results: tuple[ResearchDataResult, ...] = field(repr=False, compare=False)

    @property
    def assets(self) -> tuple[str, ...]:
        """Return the authenticated asset ontology carried by the entries."""

        return tuple(sorted({str(entry["asset"]) for entry in self.entries}))

    def __post_init__(self) -> None:
        semantic = {
            "schema_version": 1,
            "entries": _source_set_identity_entries(self.entries),
        }
        if self.manifest_id != canonical_hash(semantic):
            raise ValueError(
                "source-set manifest ID does not match authenticated entries"
            )
        expected_source_sha = canonical_hash(
            {"source_sha256s": tuple(entry["source_sha256"] for entry in self.entries)}
        )
        if self.source_sha256 != expected_source_sha:
            raise ValueError(
                "source-set source hash does not match authenticated entries"
            )
        if (
            not self.entries
            or tuple(entry["timeframe"] for entry in self.entries) != self.timeframes
        ):
            raise ValueError("source-set manifest timeframes are not ordered exactly")
        if self.records != sum(int(entry["records"]) for entry in self.entries):
            raise ValueError("source-set manifest record count is inconsistent")
        if any(
            not isinstance(entry.get("origin_mode"), str)
            or not isinstance(entry.get("acquisition_cutoff"), datetime)
            or not isinstance(entry.get("acquisition_evidence_sha256"), str)
            for entry in self.entries
        ):
            raise ValueError(
                "source-set manifest lacks authenticated acquisition evidence"
            )

    def verify_covers(
        self,
        *,
        ladder: Sequence[str],
        venue: str,
        instrument_id: str,
        asset: str,
        bounds: Mapping[str, tuple[datetime, datetime]],
    ) -> None:
        """Verify authenticated parent results cover a native requested slice."""

        ordered_ladder = tuple(ladder)
        if (
            tuple(self.timeframes) != ordered_ladder
            or set(bounds) != set(ordered_ladder)
            or len(self.source_results) != len(ordered_ladder)
        ):
            raise ValueError("source-set coverage must use the exact resolved ladder")
        if (
            self.venue != venue
            or self.instrument_ids != (instrument_id,)
            or self.assets != (asset,)
        ):
            raise ValueError("source-set coverage market identity mismatch")
        for timeframe, result, entry in zip(
            ordered_ladder, self.source_results, self.entries, strict=True
        ):
            if entry.get("timeframe") != timeframe:
                raise ValueError(
                    "source-set entries are not in authenticated ladder order"
                )
            parent_start = _datetime(entry.get("requested_start"))
            parent_end = _datetime(entry.get("requested_end"))
            if (
                entry.get("manifest_id") != result.manifest.manifest_id
                or entry.get("source_sha256") != result.manifest.source_sha256
            ):
                raise ValueError(
                    "source-set entry does not match its authenticated parent"
                )
            _verify_authenticated_result(
                result,
                timeframe=timeframe,
                venue=venue,
                instrument_id=instrument_id,
                asset=asset,
                start=parent_start,
                end=parent_end,
            )
            requested_start, requested_end = _validate_slice_bounds(
                timeframe, bounds[timeframe]
            )
            if requested_start < parent_start or requested_end > parent_end:
                raise ValueError(
                    "authenticated source result does not cover requested slice"
                )
            selected = tuple(
                item
                for item in result.records
                if item.bar.bar_open_at >= requested_start
                and item.bar.bar_close_at <= requested_end
            )
            _validate_slice_records(
                selected,
                timeframe=timeframe,
                venue=venue,
                instrument_id=instrument_id,
                asset=asset,
                start=requested_start,
                end=requested_end,
            )

    def verify(
        self,
        *,
        ladder: Sequence[str],
        venue: str,
        instrument_id: str,
        asset: str,
        bounds: Mapping[str, tuple[datetime, datetime]],
    ) -> None:
        if len(self.source_results) != len(self.timeframes):
            raise ValueError("source-set manifest result count is inconsistent")
        result_timeframes = tuple(
            result.manifest.timeframes[0]
            if len(result.manifest.timeframes) == 1
            else ""
            for result in self.source_results
        )
        if result_timeframes != self.timeframes:
            raise ValueError(
                "source-set manifest results are not in authenticated ladder order"
            )
        expected = build_research_source_set_manifest(
            {item.manifest.timeframes[0]: item for item in self.source_results},
            ladder=ladder,
            venue=venue,
            instrument_id=instrument_id,
            asset=asset,
            bounds=bounds,
        )
        if (
            expected.manifest_id != self.manifest_id
            or expected.source_sha256 != self.source_sha256
        ):
            raise ValueError("source-set manifest authentication failed")


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _validate_slice_bounds(
    timeframe: str,
    bounds: tuple[datetime, datetime],
) -> tuple[datetime, datetime]:
    if timeframe not in TIMEFRAME_DURATIONS:
        raise ValueError("authenticated slice timeframe is unsupported")
    if not isinstance(bounds, tuple) or len(bounds) != 2:
        raise ValueError("authenticated slice bounds must be (start, end)")
    start = _datetime(bounds[0])
    end = _datetime(bounds[1])
    if end <= start:
        raise ValueError("authenticated slice end must follow start")
    grid = grid_for(timeframe)
    grid.validate_bar(start, start + TIMEFRAME_DURATIONS[timeframe])
    grid.validate_bar(end - TIMEFRAME_DURATIONS[timeframe], end)
    return start, end


def _validate_slice_records(
    records: Sequence[SourceBarRecord],
    *,
    timeframe: str,
    venue: str,
    instrument_id: str,
    asset: str,
    start: datetime,
    end: datetime,
) -> None:
    if not records:
        raise ValueError("authenticated source slice is empty")
    if any(
        item.venue != venue
        or item.instrument_id != instrument_id
        or item.asset != asset
        or item.bar.timeframe != timeframe
        for item in records
    ):
        raise ValueError("authenticated source slice identity mismatch")
    if records[0].bar.bar_open_at != start or records[-1].bar.bar_close_at != end:
        raise ValueError(
            "authenticated source slice does not cover exact requested bounds"
        )
    grid_for(timeframe).validate_contiguous(
        tuple(item.bar.bar_open_at for item in records),
        tuple(item.bar.bar_close_at for item in records),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticatedSourceSlice:
    """An exact native subinterval selected from authenticated parent bytes."""

    source_manifest_id: str
    source_sha256: str
    venue: str
    instrument_id: str
    asset: str
    bounds: tuple[tuple[str, datetime, datetime], ...]
    records_by_timeframe: Mapping[str, tuple[SourceBarRecord, ...]]
    record_identities: tuple[tuple[str, tuple[str, ...]], ...]
    record_counts: tuple[tuple[str, int], ...]
    acquisition_evidence: tuple[tuple[str, str, datetime, str], ...]
    slice_fingerprint: str

    def __post_init__(self) -> None:
        if not self.source_manifest_id.strip() or not self.source_sha256.strip():
            raise ValueError("authenticated slice requires parent source identity")
        if (
            not self.venue.strip()
            or not self.instrument_id.strip()
            or not self.asset.strip()
        ):
            raise ValueError("authenticated slice market identity is incomplete")
        ordered_bounds = tuple(self.bounds)
        timeframes = tuple(item[0] for item in ordered_bounds)
        if len(set(timeframes)) != len(timeframes) or not timeframes:
            raise ValueError(
                "authenticated slice bounds must contain unique timeframes"
            )
        normalized_bounds = tuple(
            (timeframe, *_validate_slice_bounds(timeframe, (start, end)))
            for timeframe, start, end in ordered_bounds
        )
        records = {
            str(key): tuple(value) for key, value in self.records_by_timeframe.items()
        }
        if set(records) != set(timeframes):
            raise ValueError("authenticated slice records must cover exact bounds")
        identities: list[tuple[str, tuple[str, ...]]] = []
        counts: list[tuple[str, int]] = []
        for timeframe, start, end in normalized_bounds:
            values = records[timeframe]
            _validate_slice_records(
                values,
                timeframe=timeframe,
                venue=self.venue,
                instrument_id=self.instrument_id,
                asset=self.asset,
                start=start,
                end=end,
            )
            ids = tuple(item.source_identity for item in values)
            if len(set(ids)) != len(ids):
                raise ValueError("authenticated slice record identities must be unique")
            identities.append((timeframe, ids))
            counts.append((timeframe, len(values)))
        expected_identity = tuple(sorted(identities))
        expected_counts = tuple(sorted(counts))
        if (
            tuple(self.record_identities) != expected_identity
            or tuple(self.record_counts) != expected_counts
        ):
            raise ValueError(
                "authenticated slice receipt record metadata is inconsistent"
            )
        if any(
            not isinstance(item, tuple) or len(item) != 4
            for item in self.acquisition_evidence
        ):
            raise ValueError("authenticated slice acquisition evidence is malformed")
        expected_fingerprint = canonical_hash(
            {
                "schema_version": 1,
                "source_manifest_id": self.source_manifest_id,
                "source_sha256": self.source_sha256,
                "venue": self.venue,
                "instrument_id": self.instrument_id,
                "asset": self.asset,
                "bounds": normalized_bounds,
                "record_identities": expected_identity,
                "record_counts": expected_counts,
                "acquisition_evidence": tuple(self.acquisition_evidence),
            }
        )
        if self.slice_fingerprint != expected_fingerprint:
            raise ValueError("authenticated slice fingerprint does not match receipt")
        object.__setattr__(self, "bounds", normalized_bounds)
        object.__setattr__(self, "records_by_timeframe", MappingProxyType(records))
        object.__setattr__(self, "record_identities", expected_identity)
        object.__setattr__(self, "record_counts", expected_counts)
        object.__setattr__(
            self, "acquisition_evidence", tuple(self.acquisition_evidence)
        )

    @property
    def bars_by_timeframe(self) -> Mapping[str, tuple[SRBar, ...]]:
        return MappingProxyType(
            {
                timeframe: tuple(item.bar for item in records)
                for timeframe, records in self.records_by_timeframe.items()
            }
        )


def authenticated_slice(
    manifest: ResearchSourceSetManifest,
    *,
    ladder: Sequence[str],
    venue: str,
    instrument_id: str,
    asset: str,
    bounds: Mapping[str, tuple[datetime, datetime]],
) -> AuthenticatedSourceSlice:
    """Compose one exact native slice from a verified authenticated source set."""

    if not isinstance(manifest, ResearchSourceSetManifest):
        raise TypeError("manifest must be ResearchSourceSetManifest")
    ordered_ladder = tuple(ladder)
    manifest.verify_covers(
        ladder=ordered_ladder,
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
        bounds=bounds,
    )
    ordered_bounds = tuple(
        (timeframe, *_validate_slice_bounds(timeframe, bounds[timeframe]))
        for timeframe in ordered_ladder
    )
    records_by_timeframe: dict[str, tuple[SourceBarRecord, ...]] = {}
    identities: list[tuple[str, tuple[str, ...]]] = []
    counts: list[tuple[str, int]] = []
    evidence: list[tuple[str, str, datetime, str]] = []
    for timeframe, start, end in ordered_bounds:
        index = tuple(manifest.timeframes).index(timeframe)
        parent = manifest.source_results[index]
        selected = tuple(
            item
            for item in parent.records
            if item.bar.bar_open_at >= start and item.bar.bar_close_at <= end
        )
        records_by_timeframe[timeframe] = selected
        identities.append((timeframe, tuple(item.source_identity for item in selected)))
        counts.append((timeframe, len(selected)))
        entry = manifest.entries[index]
        evidence.append(
            (
                timeframe,
                str(entry["origin_mode"]),
                _datetime(entry["acquisition_cutoff"]),
                str(entry["acquisition_evidence_sha256"]),
            )
        )
    expected_identity = tuple(sorted(identities))
    expected_counts = tuple(sorted(counts))
    acquisition_evidence = tuple(evidence)
    fingerprint = canonical_hash(
        {
            "schema_version": 1,
            "source_manifest_id": manifest.manifest_id,
            "source_sha256": manifest.source_sha256,
            "venue": venue,
            "instrument_id": instrument_id,
            "asset": asset,
            "bounds": ordered_bounds,
            "record_identities": expected_identity,
            "record_counts": expected_counts,
            "acquisition_evidence": acquisition_evidence,
        }
    )
    return AuthenticatedSourceSlice(
        source_manifest_id=manifest.manifest_id,
        source_sha256=manifest.source_sha256,
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
        bounds=ordered_bounds,
        records_by_timeframe=records_by_timeframe,
        record_identities=expected_identity,
        record_counts=expected_counts,
        acquisition_evidence=acquisition_evidence,
        slice_fingerprint=fingerprint,
    )


def _source_set_identity_entries(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Return immutable source identity, excluding the per-load access path.

    CACHE_ONLY versus PROVIDER_FETCH is provenance on a result, not a new
    source dataset.  The aggregate identity must therefore remain stable when
    a provider-fetched cache is reopened offline, while retaining both access
    and origin fields in the visible entries.
    """

    excluded = {"source_mode", "cache_access_mode"}
    return tuple(
        {key: value for key, value in entry.items() if key not in excluded}
        for entry in entries
    )


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("historical timestamps must be ISO-8601 UTC") from exc
    else:
        if isinstance(value, bool):
            raise TypeError("historical timestamps cannot be bool")
        try:
            result = datetime.fromtimestamp(float(value) / 1000, tz=UTC)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("historical timestamps must be UTC milliseconds") from exc
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise ValueError("historical timestamps must be timezone-aware UTC")
    return result.astimezone(UTC)


def _rows(page: Any) -> list[Mapping[str, Any]]:
    if page is None:
        return []
    if hasattr(page, "to_dict"):
        values = page.to_dict("records")
    else:
        values = page
    result: list[Mapping[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping):
            result.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            names = (
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base",
                "taker_buy_quote_volume",
                "ignore",
            )
            result.append(
                {
                    name: value[index]
                    for index, name in enumerate(names)
                    if index < len(value)
                }
            )
        else:
            raise TypeError("historical adapter rows must be mappings or sequences")
    return result


def _canonical_source_identity(
    *,
    venue: str,
    instrument_id: str,
    asset: str,
    timeframe: str,
    opened: datetime,
    exchange_close_at: datetime | None,
) -> str:
    return canonical_hash(
        {
            "venue": venue,
            "instrument_id": instrument_id,
            "asset": asset,
            "timeframe": timeframe,
            "bar_open_at": opened,
            "exchange_close_at": exchange_close_at,
        }
    )


def _row_record(
    row: Mapping[str, Any],
    *,
    venue: str,
    instrument_id: str,
    asset: str,
    timeframe: str,
) -> SourceBarRecord:
    if "timestamp" not in row:
        raise ValueError("historical row lacks timestamp")
    opened = _datetime(row["timestamp"])
    duration = TIMEFRAME_DURATIONS[timeframe]
    closed = opened + duration
    source_close = row.get("close_time")
    if source_close is None:
        raise ValueError("Binance historical rows must include exchange close evidence")
    exchange_close_at = _datetime(source_close)
    if not opened < exchange_close_at <= closed:
        raise ValueError(
            "exchange close evidence is outside the canonical bar interval"
        )

    def decimal(name: str) -> Decimal:
        try:
            result = Decimal(str(row[name]))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"historical row lacks numeric {name}") from exc
        if not result.is_finite():
            raise ValueError(f"historical row {name} must be finite")
        return result

    bar = SRBar(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=decimal("open"),
        high=decimal("high"),
        low=decimal("low"),
        close=decimal("close"),
        volume=decimal("volume"),
        taker_buy_base=(
            None if row.get("taker_buy_base") is None else decimal("taker_buy_base")
        ),
    )
    grid_for(timeframe).validate_bar(opened, closed)
    source_identity = _canonical_source_identity(
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
        timeframe=timeframe,
        opened=opened,
        exchange_close_at=exchange_close_at,
    )
    return SourceBarRecord(
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
        bar=bar,
        source_identity=source_identity,
        exchange_close_at=exchange_close_at,
    )


def _cache_name(
    venue: str,
    instrument_id: str,
    asset: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> str:
    identity = canonical_hash(
        {
            "cache_schema_version": RESEARCH_CACHE_SCHEMA_VERSION,
            "venue": venue,
            "instrument_id": instrument_id,
            "asset": asset,
            "timeframe": timeframe,
            "start": start,
            "end": end,
        }
    )
    return f"{instrument_id.upper()}_{timeframe}_v{RESEARCH_CACHE_SCHEMA_VERSION}_{identity[:24]}.jsonl"


def _validate_utc_cutoff(value: datetime, name: str = "acquisition_cutoff") -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a timezone-aware UTC datetime") from exc
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value.astimezone(UTC)


def _acquisition_evidence(
    *,
    manifest: SourceManifest,
    venue: str,
    instrument_id: str,
    asset: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    acquisition_cutoff: datetime,
    origin_mode: str,
) -> tuple[Mapping[str, Any], str]:
    """Build the authenticated origin record persisted beside one cache."""

    evidence = {
        "schema_version": RESEARCH_CACHE_SCHEMA_VERSION,
        "origin_mode": origin_mode,
        "provider_identity": "binance_usdm_native",
        "venue": venue,
        "instrument_id": instrument_id,
        "asset": asset,
        "timeframe": timeframe,
        "requested_start": start,
        "requested_end": end,
        "acquisition_cutoff": _validate_utc_cutoff(acquisition_cutoff),
        "manifest_id": manifest.manifest_id,
        "source_sha256": manifest.source_sha256,
        "records": manifest.records,
        "closed_bar_contract": "canonical_grid_close_v1",
    }
    return evidence, canonical_hash(evidence)


def _validate_acquisition_evidence(
    evidence: Mapping[str, Any],
    *,
    manifest: SourceManifest,
    venue: str,
    instrument_id: str,
    asset: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> tuple[datetime, str, str]:
    required = {
        "schema_version",
        "origin_mode",
        "provider_identity",
        "venue",
        "instrument_id",
        "asset",
        "timeframe",
        "requested_start",
        "requested_end",
        "acquisition_cutoff",
        "manifest_id",
        "source_sha256",
        "records",
        "closed_bar_contract",
        "evidence_sha256",
    }
    if set(evidence) != required:
        raise ValueError(
            "research cache acquisition evidence schema is unsupported or incomplete"
        )
    if (
        evidence["schema_version"] != RESEARCH_CACHE_SCHEMA_VERSION
        or evidence["provider_identity"] != "binance_usdm_native"
    ):
        raise ValueError(
            "research cache acquisition evidence version/origin is unsupported"
        )
    if evidence["origin_mode"] != "BINANCE_USDM_NATIVE":
        raise ValueError(
            "research cache origin is not authenticated Binance USD-M evidence"
        )
    expected = {
        "schema_version": RESEARCH_CACHE_SCHEMA_VERSION,
        "origin_mode": evidence["origin_mode"],
        "provider_identity": evidence["provider_identity"],
        "venue": venue,
        "instrument_id": instrument_id,
        "asset": asset,
        "timeframe": timeframe,
        "requested_start": start,
        "requested_end": end,
        "acquisition_cutoff": _validate_utc_cutoff(evidence["acquisition_cutoff"]),
        "manifest_id": manifest.manifest_id,
        "source_sha256": manifest.source_sha256,
        "records": manifest.records,
        "closed_bar_contract": "canonical_grid_close_v1",
    }
    if (
        evidence["venue"] != venue
        or evidence["instrument_id"] != instrument_id
        or evidence["asset"] != asset
        or evidence["timeframe"] != timeframe
        or evidence["manifest_id"] != manifest.manifest_id
        or evidence["source_sha256"] != manifest.source_sha256
        or evidence["records"] != manifest.records
        or _datetime(evidence["requested_start"]) != start
        or _datetime(evidence["requested_end"]) != end
    ):
        raise ValueError(
            "research cache acquisition identity does not match requested source"
        )
    evidence_hash = str(evidence["evidence_sha256"])
    if evidence_hash != canonical_hash(expected):
        raise ValueError("research cache acquisition evidence identity mismatch")
    cutoff = expected["acquisition_cutoff"]
    if end > grid_for(timeframe).expected_closed_cutoff(cutoff):
        raise ValueError(
            "research cache requested end was not closed at authenticated acquisition cutoff"
        )
    return cutoff, str(evidence["origin_mode"]), evidence_hash


class BinanceUSDMResearchLoader:
    """Load exact closed UTC bars through an injected native adapter."""

    def __init__(
        self,
        adapter: HistoricalAdapter | None = None,
        *,
        cache_root: str | Path,
        venue: str,
        page_limit: int = BINANCE_KLINE_PAGE_LIMIT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(page_limit, bool) or page_limit != BINANCE_KLINE_PAGE_LIMIT:
            raise ValueError(
                f"page_limit must equal market-data invariant {BINANCE_KLINE_PAGE_LIMIT}"
            )
        if venue != "binance_usdm":
            raise ValueError("research loader venue must be binance_usdm")
        self.adapter = adapter
        self.cache_root = Path(cache_root)
        self.venue = venue
        self.page_limit = page_limit
        self.accounting = ProviderCallAccounting()
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def provider_calls(self) -> int:
        return self.accounting.calls

    def capture_acquisition_cutoff(self) -> datetime:
        """Capture one authenticated UTC cutoff for a source-set load."""

        return _validate_utc_cutoff(self._clock())

    def _path(
        self,
        instrument_id: str,
        asset: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> Path:
        return self.cache_root / _cache_name(
            self.venue,
            instrument_id,
            asset,
            timeframe,
            start,
            end,
        )

    async def load(
        self,
        *,
        instrument_id: str,
        asset: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        source_mode: str,
        provider_calls_authorized: bool = False,
        cache_path: str | Path | None = None,
        acquisition_cutoff: datetime | None = None,
    ) -> ResearchDataResult:
        calls_at_start = self.accounting.calls
        if self.cache_root.is_symlink():
            raise ValueError("research cache root must not be a symlink")
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(asset, str) or not asset.strip():
            raise ValueError("asset must be non-empty")
        if timeframe not in TIMEFRAME_DURATIONS:
            raise ValueError(f"unsupported research timeframe: {timeframe}")
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or start.utcoffset() != UTC.utcoffset(start)
            or end.utcoffset() != UTC.utcoffset(end)
        ):
            raise ValueError("research data bounds must use UTC")
        if end <= start:
            raise ValueError("research data end must follow start")
        grid_for(timeframe).validate_bar(start, start + TIMEFRAME_DURATIONS[timeframe])
        grid_for(timeframe).validate_bar(end - TIMEFRAME_DURATIONS[timeframe], end)
        if not isinstance(source_mode, str):
            raise TypeError("source_mode must be a string")
        mode = source_mode.upper()
        if mode not in {"CACHE_ONLY", "BINANCE_USDM"}:
            raise ValueError("unsupported research source mode")
        target = (
            Path(cache_path)
            if cache_path is not None
            else self._path(instrument_id, asset, timeframe, start, end)
        )
        if target.parent.is_symlink():
            raise ValueError("research cache parent must not be a symlink")
        if mode == "CACHE_ONLY":
            if target.is_symlink() or not target.is_file():
                raise FileNotFoundError(
                    f"cache-only research source is missing: {target}"
                )
            manifest, records = load_source_jsonl(target)
            manifest_path = target.with_suffix(target.suffix + ".manifest.json")
            acquisition_cutoff, origin_mode, evidence_sha256 = (
                self._verify_cache_manifest(
                    manifest_path,
                    manifest,
                    venue=self.venue,
                    instrument_id=instrument_id,
                    asset=asset,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
            )
            self._validate_records(
                records,
                venue=self.venue,
                instrument_id=instrument_id,
                asset=asset,
                timeframe=timeframe,
                start=start,
                end=end,
                acquisition_cutoff=acquisition_cutoff,
            )
            return ResearchDataResult(
                manifest=manifest,
                records=records,
                cache_path=target,
                provider_calls=0,
                source_mode=mode,
                manifest_path=manifest_path,
                total_provider_calls=self.accounting.calls,
                cache_access_mode="CACHE_ONLY",
                origin_mode=origin_mode,
                acquisition_cutoff=acquisition_cutoff,
                acquisition_evidence_sha256=evidence_sha256,
            )
        if provider_calls_authorized is not True:
            raise PermissionError(
                "provider calls require explicit provider_calls_authorized=True"
            )
        if self.adapter is None:
            raise ValueError("BINANCE_USDM research mode requires an injected adapter")
        acquisition_cutoff = (
            self.capture_acquisition_cutoff()
            if acquisition_cutoff is None
            else _validate_utc_cutoff(acquisition_cutoff)
        )
        latest_closed = grid_for(timeframe).expected_closed_cutoff(acquisition_cutoff)
        if end > latest_closed:
            raise ValueError(
                "requested research end is beyond the latest closed grid at acquisition cutoff"
            )
        records = await self._fetch(
            instrument_id=instrument_id,
            asset=asset,
            timeframe=timeframe,
            start=start,
            end=end,
            acquisition_cutoff=acquisition_cutoff,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(self._record_json(item) for item in records).encode("utf-8")
        target_preexisted = target.exists()
        if target.is_symlink():
            raise ValueError("research cache path must not be a symlink")
        if target.exists():
            existing = target.read_bytes()
            if existing != payload:
                raise FileExistsError(
                    "research cache identity already exists with different bytes"
                )
        else:
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
        manifest, loaded = load_source_jsonl(target)
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        existing_evidence: tuple[datetime, str, str] | None = None
        if (
            target_preexisted
            and manifest_path.exists()
            and not manifest_path.is_symlink()
        ):
            try:
                existing_evidence = self._verify_cache_manifest(
                    manifest_path,
                    manifest,
                    venue=self.venue,
                    instrument_id=instrument_id,
                    asset=asset,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
            except (ValueError, FileNotFoundError):
                existing_evidence = None
        if existing_evidence is None:
            evidence, evidence_sha256 = _acquisition_evidence(
                manifest=manifest,
                venue=self.venue,
                instrument_id=instrument_id,
                asset=asset,
                timeframe=timeframe,
                start=start,
                end=end,
                acquisition_cutoff=acquisition_cutoff,
                origin_mode="BINANCE_USDM_NATIVE",
            )
            self._write_cache_manifest(
                manifest_path,
                manifest,
                evidence=evidence,
                evidence_sha256=evidence_sha256,
            )
            existing_evidence = self._verify_cache_manifest(
                manifest_path,
                manifest,
                venue=self.venue,
                instrument_id=instrument_id,
                asset=asset,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        stored_cutoff, stored_origin, stored_evidence_sha256 = existing_evidence
        return ResearchDataResult(
            manifest=manifest,
            records=loaded,
            cache_path=target,
            provider_calls=self.accounting.calls - calls_at_start,
            source_mode=mode,
            manifest_path=manifest_path,
            total_provider_calls=self.accounting.calls,
            cache_access_mode="PROVIDER_FETCH",
            origin_mode=stored_origin,
            acquisition_cutoff=stored_cutoff,
            acquisition_evidence_sha256=stored_evidence_sha256,
        )

    async def _fetch(
        self,
        *,
        instrument_id: str,
        asset: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        acquisition_cutoff: datetime,
    ) -> tuple[SourceBarRecord, ...]:
        duration = TIMEFRAME_DURATIONS[timeframe]
        cursor = start
        seen_open: set[datetime] = set()
        records: list[SourceBarRecord] = []
        while cursor < end:
            kwargs = {
                "since": _milliseconds(cursor),
                "until": _milliseconds(end),
                "limit": self.page_limit,
                "include_close_time": True,
            }
            result = self.adapter.get_historical_ohlcv(
                instrument_id, timeframe, **kwargs
            )
            page = await result if inspect.isawaitable(result) else result
            self.accounting.calls += 1
            self.accounting.pages += 1
            rows = _rows(page)
            if not rows:
                break
            if len(rows) > self.page_limit:
                raise ValueError("provider page exceeded the market-data page limit")
            page_records: list[SourceBarRecord] = []
            for row in rows:
                record = _row_record(
                    row,
                    venue=self.venue,
                    instrument_id=instrument_id,
                    asset=asset,
                    timeframe=timeframe,
                )
                if record.bar.bar_open_at < start or record.bar.bar_close_at > end:
                    continue
                if (
                    record.bar.bar_close_at > acquisition_cutoff
                    or record.exchange_close_at > acquisition_cutoff
                ):
                    raise ValueError(
                        "provider returned a bar that was not closed at the captured acquisition cutoff"
                    )
                if record.bar.bar_open_at in seen_open:
                    raise ValueError("provider returned duplicate candle")
                seen_open.add(record.bar.bar_open_at)
                page_records.append(record)
            if not page_records:
                raise ValueError("provider page made no progress")
            records.extend(page_records)
            last_open = max(item.bar.bar_open_at for item in page_records)
            next_cursor = last_open + duration
            if next_cursor <= cursor:
                raise ValueError("provider page stalled")
            cursor = next_cursor
        ordered = tuple(sorted(records, key=lambda item: item.bar.bar_open_at))
        self._validate_records(
            ordered,
            venue=self.venue,
            instrument_id=instrument_id,
            asset=asset,
            timeframe=timeframe,
            start=start,
            end=end,
            acquisition_cutoff=acquisition_cutoff,
        )
        return ordered

    @staticmethod
    def _validate_records(
        records: Sequence[SourceBarRecord],
        *,
        venue: str,
        instrument_id: str,
        asset: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        acquisition_cutoff: datetime | None = None,
    ) -> None:
        if any(
            item.venue != venue
            or item.instrument_id != instrument_id
            or item.asset != asset
            or item.bar.timeframe != timeframe
            for item in records
        ):
            raise ValueError("research source identity/timeframe mismatch")
        for item in records:
            expected_identity = _canonical_source_identity(
                venue=venue,
                instrument_id=instrument_id,
                asset=asset,
                timeframe=timeframe,
                opened=item.bar.bar_open_at,
                exchange_close_at=item.exchange_close_at,
            )
            if item.source_identity != expected_identity:
                raise ValueError(
                    "research source identity does not authenticate record contents"
                )
            if item.exchange_close_at is None:
                raise ValueError("research source is missing exchange close evidence")
            if (
                not item.bar.bar_open_at
                < item.exchange_close_at
                <= item.bar.bar_close_at
            ):
                raise ValueError(
                    "research source exchange close evidence is out of interval"
                )
            if acquisition_cutoff is not None and (
                item.bar.bar_close_at > acquisition_cutoff
                or item.exchange_close_at > acquisition_cutoff
            ):
                raise ValueError(
                    "research source contains a bar that was not closed at acquisition cutoff"
                )
        if not records:
            raise ValueError("research source returned no closed bars")
        if records[0].bar.bar_open_at != start or records[-1].bar.bar_close_at != end:
            raise ValueError(
                "research source does not cover the exact requested bounds"
            )
        grid_for(timeframe).validate_contiguous(
            tuple(item.bar.bar_open_at for item in records),
            tuple(item.bar.bar_close_at for item in records),
        )

    @staticmethod
    def _record_json(item: SourceBarRecord) -> str:
        row = {
            "venue": item.venue,
            "instrument_id": item.instrument_id,
            "asset": item.asset,
            "timeframe": item.bar.timeframe,
            "bar_open_at": item.bar.bar_open_at.isoformat(timespec="microseconds"),
            "bar_close_at": item.bar.bar_close_at.isoformat(timespec="microseconds"),
            "open": str(item.bar.open),
            "high": str(item.bar.high),
            "low": str(item.bar.low),
            "close": str(item.bar.close),
            "volume": str(item.bar.volume),
            "taker_buy_base": None
            if item.bar.taker_buy_base is None
            else str(item.bar.taker_buy_base),
            "exchange_close_at": None
            if item.exchange_close_at is None
            else item.exchange_close_at.isoformat(timespec="microseconds"),
            "source_identity": item.source_identity,
        }
        return json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"

    @staticmethod
    def _write_cache_manifest(
        path: Path,
        manifest: SourceManifest,
        *,
        evidence: Mapping[str, Any],
        evidence_sha256: str,
    ) -> None:
        if path.is_symlink():
            raise ValueError("research cache manifest path must not be a symlink")
        payload = {
            "schema_version": RESEARCH_CACHE_SCHEMA_VERSION,
            "manifest_id": manifest.manifest_id,
            "source_sha256": manifest.source_sha256,
            "records": manifest.records,
            "venue": manifest.venue,
            "instrument_ids": list(manifest.instrument_ids),
            "timeframes": list(manifest.timeframes),
            "assets": list(manifest.assets),
            "acquisition": {
                **{
                    key: value.isoformat(timespec="microseconds")
                    if isinstance(value, datetime)
                    else value
                    for key, value in evidence.items()
                },
                "evidence_sha256": evidence_sha256,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if path.exists() and path.read_bytes() != encoded:
            raise FileExistsError(
                "research cache manifest identity already exists with different bytes"
            )
        if not path.exists():
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_bytes(encoded)
            temporary.replace(path)

    @staticmethod
    def _verify_cache_manifest(
        path: Path,
        manifest: SourceManifest,
        *,
        venue: str,
        instrument_id: str,
        asset: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> tuple[datetime, str, str]:
        if not path.is_file() or path.is_symlink():
            raise ValueError("content-addressed research cache manifest is missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("invalid research cache manifest") from exc
        expected = {
            "schema_version": RESEARCH_CACHE_SCHEMA_VERSION,
            "manifest_id": manifest.manifest_id,
            "source_sha256": manifest.source_sha256,
            "records": manifest.records,
            "venue": manifest.venue,
            "instrument_ids": list(manifest.instrument_ids),
            "timeframes": list(manifest.timeframes),
            "assets": list(manifest.assets),
        }
        if not isinstance(payload, Mapping) or any(
            payload.get(key) != value for key, value in expected.items()
        ):
            raise ValueError(
                "research cache manifest does not authenticate source bytes"
            )
        acquisition = payload.get("acquisition")
        if not isinstance(acquisition, Mapping):
            raise TypeError(
                "research cache manifest lacks authenticated acquisition evidence"
            )
        return _validate_acquisition_evidence(
            acquisition,
            manifest=manifest,
            venue=venue,
            instrument_id=instrument_id,
            asset=asset,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    def load_sync(self, **kwargs: Any) -> ResearchDataResult:
        return asyncio.run(self.load(**kwargs))


def _verify_authenticated_result(
    result: ResearchDataResult,
    *,
    timeframe: str,
    venue: str,
    instrument_id: str,
    asset: str,
    start: datetime,
    end: datetime,
) -> None:
    if not isinstance(result, ResearchDataResult):
        raise TypeError("source-set entries must be ResearchDataResult values")
    manifest = result.manifest
    if manifest.venue != venue or manifest.instrument_ids != (instrument_id,):
        raise ValueError("source-set manifest market identity mismatch")
    if manifest.timeframes != (timeframe,) or manifest.assets != (asset,):
        raise ValueError("source-set manifest timeframe/asset mismatch")
    if (
        result.cache_path is None
        or result.cache_path.is_symlink()
        or not result.cache_path.is_file()
    ):
        raise ValueError(
            "source-set result must retain a regular authenticated cache file"
        )
    if (
        result.manifest_path is None
        or result.manifest_path.is_symlink()
        or not result.manifest_path.is_file()
    ):
        raise ValueError(
            "source-set result must retain a regular authenticated manifest file"
        )
    acquisition_cutoff, origin_mode, evidence_sha256 = (
        BinanceUSDMResearchLoader._verify_cache_manifest(
            result.manifest_path,
            manifest,
            venue=venue,
            instrument_id=instrument_id,
            asset=asset,
            timeframe=timeframe,
            start=start,
            end=end,
        )
    )
    if (
        result.origin_mode != origin_mode
        or result.acquisition_cutoff != acquisition_cutoff
        or result.acquisition_evidence_sha256 != evidence_sha256
    ):
        raise ValueError(
            "source-set result acquisition evidence does not match its authenticated sidecar"
        )
    loaded_manifest, loaded_records = load_source_jsonl(
        result.cache_path,
        expected_sha256=manifest.source_sha256,
    )
    if loaded_manifest != manifest or tuple(
        item.source_identity for item in loaded_records
    ) != tuple(item.source_identity for item in result.records):
        raise ValueError(
            "source-set result records do not match authenticated cache bytes"
        )
    BinanceUSDMResearchLoader._validate_records(
        loaded_records,
        venue=venue,
        instrument_id=instrument_id,
        asset=asset,
        timeframe=timeframe,
        start=start,
        end=end,
    )


def build_research_source_set_manifest(
    results_by_timeframe: Mapping[str, ResearchDataResult],
    *,
    ladder: Sequence[str],
    venue: str,
    instrument_id: str,
    asset: str,
    bounds: Mapping[str, tuple[datetime, datetime]],
) -> ResearchSourceSetManifest:
    """Authenticate and aggregate one verified cache result per timeframe."""

    ordered_ladder = tuple(ladder)
    if set(results_by_timeframe) != set(ordered_ladder) or set(bounds) != set(
        ordered_ladder
    ):
        raise ValueError(
            "source-set results and bounds must cover the exact resolved ladder"
        )
    entries: list[Mapping[str, Any]] = []
    ordered_results: list[ResearchDataResult] = []
    for timeframe in ordered_ladder:
        start, end = bounds[timeframe]
        _verify_authenticated_result(
            results_by_timeframe[timeframe],
            timeframe=timeframe,
            venue=venue,
            instrument_id=instrument_id,
            asset=asset,
            start=start,
            end=end,
        )
        result = results_by_timeframe[timeframe]
        entries.append(
            {
                "manifest_id": result.manifest.manifest_id,
                "source_sha256": result.manifest.source_sha256,
                "records": result.manifest.records,
                "venue": venue,
                "instrument_id": instrument_id,
                "asset": asset,
                "timeframe": timeframe,
                "requested_start": start,
                "requested_end": end,
                "source_mode": result.source_mode,
                "cache_access_mode": result.cache_access_mode,
                "origin_mode": result.origin_mode,
                "acquisition_cutoff": result.acquisition_cutoff,
                "acquisition_evidence_sha256": result.acquisition_evidence_sha256,
            }
        )
        ordered_results.append(result)
    semantic = {"schema_version": 1, "entries": _source_set_identity_entries(entries)}
    return ResearchSourceSetManifest(
        manifest_id=canonical_hash(semantic),
        source_sha256=canonical_hash(
            {"source_sha256s": tuple(entry["source_sha256"] for entry in entries)}
        ),
        records=sum(int(entry["records"]) for entry in entries),
        venue=venue,
        instrument_ids=(instrument_id,),
        timeframes=ordered_ladder,
        entries=tuple(entries),
        source_results=tuple(ordered_results),
    )


__all__ = [
    "RESEARCH_CACHE_SCHEMA_VERSION",
    "AuthenticatedSourceSlice",
    "BinanceUSDMResearchLoader",
    "HistoricalAdapter",
    "ProviderCallAccounting",
    "ResearchDataResult",
    "ResearchSourceSetManifest",
    "authenticated_slice",
    "build_research_source_set_manifest",
]
