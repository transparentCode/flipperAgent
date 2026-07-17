"""Resolved SR configuration identity and field-level provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping

from libs.models.sr.domain.identity import ContractValidationError, deterministic_hash

from .schema import _PARAMETER_PATHS
from .sections import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
    _string,
)


def _validate_resolved_config_types(
    *,
    detection: Any,
    association: Any,
    lifecycle: Any,
    runtime: Any,
) -> None:
    expected = {
        "detection": DetectionConfig,
        "association": AssociationConfig,
        "lifecycle": LifecycleConfig,
        "runtime": RuntimeConfig,
    }
    actual = {
        "detection": detection,
        "association": association,
        "lifecycle": lifecycle,
        "runtime": runtime,
    }
    for name, config_type in expected.items():
        if type(actual[name]) is not config_type:
            raise ContractValidationError(
                f"{name} must be exactly {config_type.__name__}"
            )


def _normalize_provenance(
    value: Any,
    *,
    asset: str,
    timeframe: str,
) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        entries = tuple(value.items())
    elif isinstance(value, (list, tuple)):
        entries = tuple(value)
    else:
        raise ContractValidationError(
            "field_provenance must contain one entry for each approved parameter"
        )

    if len(entries) != len(_PARAMETER_PATHS):
        raise ContractValidationError(
            "field_provenance must contain exactly "
            f"{len(_PARAMETER_PATHS)} entries"
        )

    normalized: list[tuple[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ContractValidationError(
                f"field_provenance[{index}] must be a path/source pair"
            )
        path, source = entry
        _string(path, field_name=f"field_provenance[{index}].path")
        _string(source, field_name=f"field_provenance[{index}].source")
        normalized.append((path, source))

    paths = [path for path, _ in normalized]
    if len(set(paths)) != len(paths):
        raise ContractValidationError("field_provenance must not contain duplicate paths")
    expected_paths = set(_PARAMETER_PATHS)
    actual_paths = set(paths)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unknown = sorted(actual_paths - expected_paths)
        raise ContractValidationError(
            "field_provenance paths must match the approved parameter surface; "
            f"missing={missing}, unknown={unknown}"
        )

    allowed_sources = {
        "defaults",
        f"timeframe:{timeframe}",
        f"asset:{asset}",
        f"asset_timeframe:{asset}:{timeframe}",
    }
    for path, source in normalized:
        if source not in allowed_sources:
            raise ContractValidationError(
                f"invalid provenance source for {path}: {source!r}"
            )
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class ResolvedSRConfig:
    """Fully resolved SR configuration with field-level provenance and hash."""

    version: str
    asset: str
    timeframe: str
    detection: DetectionConfig
    association: AssociationConfig
    lifecycle: LifecycleConfig
    runtime: RuntimeConfig
    field_provenance: tuple[tuple[str, str], ...]
    resolved_config_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _string(self.version, field_name="version"))
        if self.version != "1":
            raise ContractValidationError(
                f"unsupported config version: {self.version!r}"
            )
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(
            self, "timeframe", _string(self.timeframe, field_name="timeframe")
        )
        _validate_resolved_config_types(
            detection=self.detection,
            association=self.association,
            lifecycle=self.lifecycle,
            runtime=self.runtime,
        )
        object.__setattr__(
            self,
            "field_provenance",
            _normalize_provenance(
                self.field_provenance,
                asset=self.asset,
                timeframe=self.timeframe,
            ),
        )
        if (
            not isinstance(self.resolved_config_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.resolved_config_hash) is None
        ):
            raise ContractValidationError(
                "resolved_config_hash must be a lowercase SHA-256 hex string"
            )
        if self.resolved_config_hash != deterministic_hash(self._hash_payload()):
            raise ContractValidationError("resolved_config_hash does not match content")

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "detection": asdict(self.detection),
            "association": asdict(self.association),
            "lifecycle": asdict(self.lifecycle),
            "runtime": asdict(self.runtime),
            "field_provenance": sorted(self.field_provenance),
        }

    @classmethod
    def create(
        cls,
        *,
        version: str,
        asset: str,
        timeframe: str,
        detection: DetectionConfig,
        association: AssociationConfig,
        lifecycle: LifecycleConfig,
        runtime: RuntimeConfig,
        field_provenance: Mapping[str, str],
    ) -> ResolvedSRConfig:
        version = _string(version, field_name="version")
        if version != "1":
            raise ContractValidationError(
                f"unsupported config version: {version!r}"
            )
        asset = _string(asset, field_name="asset")
        timeframe = _string(timeframe, field_name="timeframe")
        _validate_resolved_config_types(
            detection=detection,
            association=association,
            lifecycle=lifecycle,
            runtime=runtime,
        )
        provenance_tuple = _normalize_provenance(
            field_provenance,
            asset=asset,
            timeframe=timeframe,
        )
        payload = {
            "version": version,
            "asset": asset,
            "timeframe": timeframe,
            "detection": asdict(detection),
            "association": asdict(association),
            "lifecycle": asdict(lifecycle),
            "runtime": asdict(runtime),
            "field_provenance": sorted(provenance_tuple),
        }
        return cls(
            version=version,
            asset=asset,
            timeframe=timeframe,
            detection=detection,
            association=association,
            lifecycle=lifecycle,
            runtime=runtime,
            field_provenance=provenance_tuple,
            resolved_config_hash=deterministic_hash(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "detection": asdict(self.detection),
            "association": asdict(self.association),
            "lifecycle": asdict(self.lifecycle),
            "runtime": asdict(self.runtime),
            "field_provenance": dict(self.field_provenance),
            "resolved_config_hash": self.resolved_config_hash,
        }


__all__ = ["ResolvedSRConfig"]
