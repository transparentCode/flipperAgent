"""Protected canonical JSONL source and manifest loaders."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config.schema import SUPPORTED_TIMEFRAMES
from ..contracts import require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash
from ..features.time import grid_for


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate protected manifest key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceManifest:
    manifest_id: str
    source_sha256: str
    records: int
    venue: str
    instrument_ids: tuple[str, ...]
    timeframes: tuple[str, ...]
    assets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.manifest_id.strip() or len(self.source_sha256) != 64:
            raise ValueError("invalid source manifest identity")
        if self.records < 0:
            raise ValueError("records must be non-negative")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("source manifest instrument IDs must be unique")
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError("source manifest timeframes must be unique")
        if len(set(self.assets)) != len(self.assets):
            raise ValueError("source manifest assets must be unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceBarRecord:
    venue: str
    instrument_id: str
    asset: str
    bar: SRBar
    source_identity: str
    exchange_close_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.venue.strip() or not self.instrument_id.strip() or not self.asset.strip():
            raise ValueError("source identity fields must be non-empty")
        if not self.source_identity.strip():
            raise ValueError("source_identity must be non-empty")
        if self.exchange_close_at is not None:
            require_utc(self.exchange_close_at, field_name="exchange_close_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtectedManifestFile:
    path: str
    sha256: str
    records: int
    venue: str
    instrument_ids: tuple[str, ...]
    asset: str
    timeframe: str
    interval_start: datetime
    interval_end: datetime
    source_records: tuple[SourceBarRecord, ...] = ()

    def __post_init__(self) -> None:
        if not self.path.strip() or len(self.sha256) != 64:
            raise ValueError("invalid protected file identity")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ValueError("protected file SHA-256 must be hexadecimal") from exc
        if self.records < 0 or not self.venue.strip() or not self.asset.strip():
            raise ValueError("invalid protected file metadata")
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError("protected file timeframe is unsupported")
        require_utc(self.interval_start, field_name="interval_start")
        require_utc(self.interval_end, field_name="interval_end")
        if self.interval_end <= self.interval_start:
            raise ValueError("protected file interval must be positive")
        if any(not isinstance(item, SourceBarRecord) for item in self.source_records):
            raise TypeError("source_records must contain SourceBarRecord values")
        if self.source_records and len(self.source_records) != self.records:
            raise ValueError("authenticated source record count differs from manifest")
        if len({item.source_identity for item in self.source_records}) != len(self.source_records):
            raise ValueError("authenticated source identities must be unique")

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "records": self.records,
            "venue": self.venue,
            "instrument_ids": self.instrument_ids,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "interval_start": self.interval_start.isoformat(timespec="microseconds"),
            "interval_end": self.interval_end.isoformat(timespec="microseconds"),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtectedManifest:
    schema_version: int
    content_id: str
    files: tuple[ProtectedManifestFile, ...]
    allowed_market_identities: tuple[str, ...]
    allowed_timeframes: tuple[str, ...]
    declared_series_intervals: tuple[Mapping[str, Any], ...]
    provider_identity: str
    creation_cutoff: datetime
    manifest_sha256: str | None = None

    @property
    def manifest_id(self) -> str:
        return self.content_id

    def semantic_mapping(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "files": tuple(item.to_mapping() for item in self.files),
            "allowed_market_identities": self.allowed_market_identities,
            "allowed_timeframes": self.allowed_timeframes,
            "declared_series_intervals": self.declared_series_intervals,
            "provider_identity": self.provider_identity,
            "creation_cutoff": self.creation_cutoff,
        }

    def source_record_for(self, *, file_path: str, source_record_identity: str) -> SourceBarRecord:
        """Return one record from the authenticated manifest bytes."""

        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("source file path must be non-empty")
        if not isinstance(source_record_identity, str) or not source_record_identity.strip():
            raise ValueError("source record identity must be non-empty")
        matching_files = [item for item in self.files if item.path == file_path]
        if len(matching_files) != 1:
            raise ValueError("source file is not declared by protected manifest")
        matching_records = [
            item for item in matching_files[0].source_records
            if item.source_identity == source_record_identity
        ]
        if len(matching_records) != 1:
            raise ValueError("source record is not declared by protected manifest file")
        return matching_records[0]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.content_id.strip():
            raise ValueError("invalid protected manifest schema/identity")
        if not self.files:
            raise ValueError("protected manifest must declare files")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("protected manifest file paths must be unique")
        if len(set(self.allowed_market_identities)) != len(self.allowed_market_identities):
            raise ValueError("protected market identities must be unique")
        if len(set(self.allowed_timeframes)) != len(self.allowed_timeframes):
            raise ValueError("protected timeframes must be unique")
        if not self.provider_identity.strip():
            raise ValueError("provider_identity must be non-empty")
        require_utc(self.creation_cutoff, field_name="creation_cutoff")
        if self.content_id != canonical_hash(self.semantic_mapping()):
            raise ValueError("protected manifest content_id does not match contents")
        if self.manifest_sha256 is not None:
            if len(self.manifest_sha256) != 64:
                raise ValueError("manifest_sha256 must be SHA-256")
            try:
                int(self.manifest_sha256, 16)
            except ValueError as exc:
                raise ValueError("manifest_sha256 must be hexadecimal") from exc


def _hash_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _parse_source_record(raw: Mapping[str, Any], line_number: int) -> SourceBarRecord:
    required = {
        "venue", "instrument_id", "asset", "timeframe", "bar_open_at",
        "bar_close_at", "open", "high", "low", "close", "volume",
        "source_identity",
    }
    if set(raw) - (required | {"taker_buy_base", "exchange_close_at"}) or not required.issubset(raw):
        raise ValueError(f"source record keys invalid at line {line_number}")
    open_at = datetime.fromisoformat(str(raw["bar_open_at"]))
    close_at = datetime.fromisoformat(str(raw["bar_close_at"]))
    require_utc(open_at, field_name="bar_open_at")
    require_utc(close_at, field_name="bar_close_at")
    bar = SRBar(
        timeframe=str(raw["timeframe"]),
        bar_open_at=open_at,
        bar_close_at=close_at,
        market_as_of=close_at,
        open=_parse_decimal(raw["open"], "open"),
        high=_parse_decimal(raw["high"], "high"),
        low=_parse_decimal(raw["low"], "low"),
        close=_parse_decimal(raw["close"], "close"),
        volume=_parse_decimal(raw["volume"], "volume"),
        taker_buy_base=(None if raw.get("taker_buy_base") is None else _parse_decimal(raw["taker_buy_base"], "taker_buy_base")),
    )
    grid_for(bar.timeframe).validate_bar(bar.bar_open_at, bar.bar_close_at)
    exchange_close = raw.get("exchange_close_at")
    return SourceBarRecord(
        venue=str(raw["venue"]),
        instrument_id=str(raw["instrument_id"]),
        asset=str(raw["asset"]),
        bar=bar,
        source_identity=str(raw["source_identity"]),
        exchange_close_at=(None if exchange_close is None else datetime.fromisoformat(str(exchange_close))),
    )


def load_source_jsonl(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> tuple[SourceManifest, tuple[SourceBarRecord, ...]]:
    source_path = Path(path)
    actual_sha = _hash_bytes(source_path)
    if expected_sha256 is not None and actual_sha != expected_sha256.lower():
        raise ValueError("source manifest SHA-256 mismatch")
    records: list[SourceBarRecord] = []
    identities: set[str] = set()
    previous_by_series: dict[tuple[str, str, str], SourceBarRecord] = {}
    with source_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
            except Exception as exc:
                raise ValueError(f"invalid source JSONL at line {line_number}") from exc
            if not isinstance(raw, Mapping):
                raise TypeError("source JSONL records must be mappings")
            record = _parse_source_record(raw, line_number)
            if record.source_identity in identities:
                raise ValueError("duplicate source identity")
            identities.add(record.source_identity)
            key = (record.instrument_id, record.asset, record.bar.timeframe)
            previous = previous_by_series.get(key)
            if previous is not None and record.bar.bar_open_at != previous.bar.bar_close_at:
                raise ValueError("source series has a gap or overlap")
            previous_by_series[key] = record
            records.append(record)
    values = tuple(records)
    manifest = SourceManifest(
        manifest_id=hashlib.sha256((actual_sha + str(len(values))).encode()).hexdigest(),
        source_sha256=actual_sha,
        records=len(values),
        venue=values[0].venue if values else "empty",
        instrument_ids=tuple(sorted({item.instrument_id for item in values})),
        timeframes=tuple(sorted({item.bar.timeframe for item in values})),
        assets=tuple(sorted({item.asset for item in values})),
    )
    return manifest, values


def _parse_manifest_file(raw: Mapping[str, Any]) -> ProtectedManifestFile:
    required = {
        "path", "sha256", "records", "venue", "instrument_ids", "asset",
        "timeframe", "interval_start", "interval_end",
    }
    if set(raw) != required:
        raise ValueError("protected file keys do not match exactly")
    return ProtectedManifestFile(
        path=str(raw["path"]),
        sha256=str(raw["sha256"]),
        records=int(raw["records"]),
        venue=str(raw["venue"]),
        instrument_ids=tuple(str(item) for item in raw["instrument_ids"]),
        asset=str(raw["asset"]),
        timeframe=str(raw["timeframe"]),
        interval_start=datetime.fromisoformat(str(raw["interval_start"])),
        interval_end=datetime.fromisoformat(str(raw["interval_end"])),
    )


def load_protected_manifest(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_content_id: str | None = None,
) -> ProtectedManifest:
    """Load and verify a manifest without deriving one from evaluated data."""

    manifest_path = Path(path)
    raw_bytes = manifest_path.read_bytes()
    actual_manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ValueError("expected protected manifest SHA-256 is invalid")
        if actual_manifest_sha256 != expected_sha256.lower():
            raise ValueError("protected manifest SHA-256 mismatch")
    try:
        raw = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except Exception as exc:
        raise ValueError("invalid protected manifest JSON") from exc
    if not isinstance(raw, Mapping):
        raise TypeError("protected manifest root must be an object")
    required = {
        "schema_version", "content_id", "files", "allowed_market_identities",
        "allowed_timeframes", "declared_series_intervals", "provider_identity",
        "creation_cutoff",
    }
    if set(raw) != required:
        raise ValueError("protected manifest keys do not match exactly")
    files = tuple(_parse_manifest_file(item) for item in raw["files"])
    declared_intervals = tuple(dict(item) for item in raw["declared_series_intervals"])
    authenticated_files: list[ProtectedManifestFile] = []
    for declared in files:
        source_path = (manifest_path.parent / declared.path).resolve()
        if not source_path.is_file() or _hash_bytes(source_path) != declared.sha256:
            raise ValueError(f"protected source file hash/path mismatch: {declared.path}")
        source_manifest, records = load_source_jsonl(source_path, expected_sha256=declared.sha256)
        if source_manifest.records != declared.records:
            raise ValueError(f"protected source record count mismatch: {declared.path}")
        for record in records:
            if record.venue != declared.venue or record.instrument_id not in declared.instrument_ids or record.asset != declared.asset or record.bar.timeframe != declared.timeframe:
                raise ValueError(f"protected source identity/timeframe mismatch: {declared.path}")
        authenticated_files.append(replace(declared, source_records=records))
    manifest = ProtectedManifest(
        schema_version=int(raw["schema_version"]),
        content_id=str(raw["content_id"]),
        files=tuple(authenticated_files),
        allowed_market_identities=tuple(str(item) for item in raw["allowed_market_identities"]),
        allowed_timeframes=tuple(str(item) for item in raw["allowed_timeframes"]),
        declared_series_intervals=declared_intervals,
        provider_identity=str(raw["provider_identity"]),
        creation_cutoff=datetime.fromisoformat(str(raw["creation_cutoff"])),
        manifest_sha256=actual_manifest_sha256,
    )
    if expected_content_id is not None and manifest.content_id != expected_content_id:
        raise ValueError("protected manifest content ID mismatch")
    for declared in manifest.files:
        records = declared.source_records
        for record in records:
            market_identity = f"{record.venue}:{record.instrument_id}:{record.asset}"
            if (
                record.instrument_id not in manifest.allowed_market_identities
                and market_identity not in manifest.allowed_market_identities
            ) or record.bar.timeframe not in manifest.allowed_timeframes:
                raise ValueError("protected source violates manifest allowlist")
        if records:
            first = min(record.bar.bar_open_at for record in records)
            last = max(record.bar.bar_close_at for record in records)
            if first != declared.interval_start or last != declared.interval_end:
                raise ValueError(f"protected source interval mismatch: {declared.path}")
            if last > manifest.creation_cutoff:
                raise ValueError("protected source extends beyond manifest creation cutoff")
    if len(manifest.declared_series_intervals) != len(manifest.files):
        raise ValueError("declared series intervals must cover every protected file")
    for interval in manifest.declared_series_intervals:
        if not isinstance(interval, Mapping):
            raise TypeError("declared series interval must be a mapping")
        path_value = interval.get("path")
        matching = [item for item in manifest.files if path_value is not None and item.path == path_value]
        if len(matching) == 1:
            start_value = interval.get("interval_start", interval.get("start"))
            end_value = interval.get("interval_end", interval.get("end"))
            if start_value is not None and end_value is not None:
                start = start_value if isinstance(start_value, datetime) else datetime.fromisoformat(str(start_value))
                end = end_value if isinstance(end_value, datetime) else datetime.fromisoformat(str(end_value))
                if start != matching[0].interval_start or end != matching[0].interval_end:
                    raise ValueError("declared series interval differs from file interval")
        if not matching:
            timeframe = interval.get("timeframe")
            start_value = interval.get("interval_start", interval.get("start"))
            end_value = interval.get("interval_end", interval.get("end"))
            if timeframe is None or start_value is None or end_value is None:
                raise ValueError("declared series interval lacks identity/interval")
            start = start_value if isinstance(start_value, datetime) else datetime.fromisoformat(str(start_value))
            end = end_value if isinstance(end_value, datetime) else datetime.fromisoformat(str(end_value))
            require_utc(start, field_name="declared interval start")
            require_utc(end, field_name="declared interval end")
            matching = [item for item in manifest.files if item.timeframe == str(timeframe) and item.interval_start == start and item.interval_end == end]
        if len(matching) != 1:
            raise ValueError("declared series interval does not match exactly one file")
    return manifest


__all__ = [
    "ProtectedManifest",
    "ProtectedManifestFile",
    "SourceBarRecord",
    "SourceManifest",
    "load_protected_manifest",
    "load_source_jsonl",
]
