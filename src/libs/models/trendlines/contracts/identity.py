"""Deterministic point-in-time identity contracts for trendline outputs."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd


IDENTITY_SEMANTICS_VERSION = "trendlines.identity.v1"
SOURCE_FINGERPRINT_SEMANTICS_VERSION = "trendlines.source-fingerprint.v1"
CONFIG_ID_SEMANTICS_VERSION = "trendlines.config-id.v1"
CHECKPOINT_ID_SEMANTICS_VERSION = "trendlines.checkpoint-id.v1"
SNAPSHOT_ID_SEMANTICS_VERSION = "trendlines.snapshot-id.v1"
CONTENT_ID_SEMANTICS_VERSION = "trendlines.content-id.v1"
REVISION_ID_SEMANTICS_VERSION = "trendlines.revision-id.v1"


class UnsupportedIdentityValueError(TypeError):
    """Raised when identity canonicalisation sees an unsupported value."""


class TrendlineIdentityProvider(Protocol):
    """Protocol for custom components with deterministic identity state."""

    def trendline_identity_payload(self) -> Mapping[str, Any]:
        """Return behaviour-affecting, canonically supported component state."""


class TrendlineExecutionMode(str, Enum):
    """Caller intent for trendline extraction."""

    RUNTIME = "runtime"
    RESEARCH = "research"


class PivotFinality(str, Enum):
    """Temporal finality contract exposed by a pivot extractor."""

    CONFIRMED_APPEND_ONLY = "confirmed_append_only"
    RETROSPECTIVE_PREFIX_REVISING = "retrospective_prefix_revising"


class SourceIdentityKind(str, Enum):
    """Provenance of a trendline source identity."""

    COMPUTED = "computed"
    PROVIDED = "provided"


class TrendlineSnapshotStage(str, Enum):
    """Pipeline stage represented by a snapshot identity."""

    FIT = "fit"
    BOUNDARY = "boundary"
    SIGNAL = "signal"


class TrendlineSnapshotFinality(str, Enum):
    """Point-in-time finality of a materialized trendline snapshot."""

    CONFIRMED_AS_OF = "confirmed_as_of"
    RETROSPECTIVE_REVISING = "retrospective_revising"


def _canonicalize(value: Any) -> Any:
    """Convert supported values into deterministic JSON-compatible data."""

    if isinstance(value, Enum):
        return {"__enum__": f"{type(value).__name__}:{value.value}"}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonicalize(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, pd.Timestamp):
        return {"__timestamp__": value.isoformat()}
    if isinstance(value, (datetime, date)):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, Path):
        return {"__path__": value.as_posix()}
    if isinstance(value, pd.Index):
        return {
            "__index__": {
                "dtype": str(value.dtype),
                "name": value.name,
                "values": _canonicalize(value.to_numpy(copy=False)),
            }
        }
    if isinstance(value, np.ndarray):
        contiguous = np.ascontiguousarray(value)
        if contiguous.dtype.kind == "O":
            encoded = _canonical_json(contiguous.tolist()).encode("utf-8")
        else:
            encoded = contiguous.tobytes()
        return {
            "__ndarray__": {
                "dtype": str(contiguous.dtype),
                "shape": list(contiguous.shape),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        }
    if isinstance(value, np.generic):
        return _canonicalize(value.item())
    if isinstance(value, Mapping):
        pairs = [
            [_canonicalize(key), _canonicalize(item)]
            for key, item in value.items()
        ]
        pairs.sort(key=lambda pair: _canonical_json(pair[0]))
        return {"__mapping__": pairs}
    if isinstance(value, list):
        return {"__list__": [_canonicalize(item) for item in value]}
    if isinstance(value, tuple):
        return {"__tuple__": [_canonicalize(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        items.sort(key=_canonical_json)
        return {"__set__": items}
    if isinstance(value, float):
        if math.isnan(value):
            return {"__float__": "nan"}
        if math.isinf(value):
            return {"__float__": "-inf" if value < 0 else "inf"}
        return value
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    value_type = type(value)
    qualified_name = f"{value_type.__module__}.{value_type.__qualname__}"
    raise UnsupportedIdentityValueError(
        f"Unsupported identity value type: {qualified_name}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_json(value: Any) -> str:
    """Return compact deterministic JSON for supported identity values."""

    return _canonical_json(value)


def canonical_hash(value: Any, *, semantics_version: str = IDENTITY_SEMANTICS_VERSION) -> str:
    """Hash canonical data with an explicit identity-semantics version."""

    envelope = {
        "semantics_version": semantics_version,
        "payload": value,
    }
    return hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()


def canonical_point_text(value: Any) -> str:
    """Serialize an index point consistently for source contracts."""

    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _qualified_component_name(component: Any) -> str:
    component_type = type(component)
    return f"{component_type.__module__}.{component_type.__qualname__}"


def _component_role(component: Any) -> str | None:
    has_extract = callable(getattr(component, "extract", None))
    has_fit = callable(getattr(component, "fit", None))
    if has_extract and not has_fit:
        return "extractor"
    if has_fit and not has_extract:
        return "fitter"
    return None


def _is_builtin_dataclass_component(component: Any) -> bool:
    component_type = type(component)
    module_name = component_type.__module__
    return dataclasses.is_dataclass(component) and (
        module_name == "libs.models.trendlines"
        or module_name.startswith("libs.models.trendlines.")
    )


def _canonical_component_field(value: Any) -> Any:
    nested_role = _component_role(value)
    if nested_role is not None:
        return resolve_component_identity_payload(value, role=nested_role)
    return _canonicalize(value)


def resolve_component_identity_payload(
    component: Any,
    *,
    role: str,
    canonical_name: str | None = None,
) -> Mapping[str, Any]:
    """Resolve deterministic identity for one extractor or fitter instance.

    Registered built-in dataclasses use their declared fields. Custom
    components must expose ``trendline_identity_payload`` explicitly.
    """

    if role not in {"extractor", "fitter"}:
        raise ValueError("component role must be 'extractor' or 'fitter'")
    expected_method = "extract" if role == "extractor" else "fit"
    if not callable(getattr(component, expected_method, None)):
        raise TypeError(
            f"{role.capitalize()} component {_qualified_component_name(component)} "
            f"must define {expected_method}()"
        )

    provider = getattr(component, "trendline_identity_payload", None)
    if callable(provider):
        payload = provider()
        if not isinstance(payload, Mapping):
            raise TypeError(
                f"{role.capitalize()} component {_qualified_component_name(component)} "
                "trendline_identity_payload() must return a mapping"
            )
        if not payload:
            raise ValueError(
                f"{role.capitalize()} component {_qualified_component_name(component)} "
                "trendline_identity_payload() must return a non-empty mapping"
            )
        state = _canonicalize(payload)
    elif _is_builtin_dataclass_component(component):
        state = {
            field.name: _canonical_component_field(getattr(component, field.name))
            for field in dataclasses.fields(component)
        }
    else:
        raise UnsupportedIdentityValueError(
            f"{role.capitalize()} component {_qualified_component_name(component)} "
            "must provide trendline_identity_payload()"
        )

    return {
        "role": role,
        "module": type(component).__module__,
        "qualified_class_name": _qualified_component_name(component),
        "canonical_name": canonical_name,
        "state": state,
    }


def _same_point(left: Any, right: Any) -> bool:
    try:
        equal = left == right
        if isinstance(equal, (bool, np.bool_)) and bool(equal):
            return True
    except (TypeError, ValueError):
        pass
    return canonical_point_text(left) == canonical_point_text(right)


@dataclass(frozen=True)
class TrendlineSourceRef:
    """Identity and horizon of the exact frame supplied to a pipeline."""

    source_id: str
    source_start: str
    as_of: str
    row_count: int
    columns: tuple[str, ...]
    identity_kind: SourceIdentityKind

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip()
        source_start = str(self.source_start).strip()
        as_of = str(self.as_of).strip()
        columns = tuple(str(column).strip() for column in self.columns)
        if not source_id:
            raise ValueError("source_id must be non-empty")
        if not source_start or not as_of:
            raise ValueError("source_start and as_of must be non-empty")
        if int(self.row_count) < 1:
            raise ValueError("row_count must be >= 1")
        if not columns or any(not column for column in columns):
            raise ValueError("columns must be non-empty")
        if len(set(columns)) != len(columns):
            raise ValueError("columns must be unique")
        if not isinstance(self.identity_kind, SourceIdentityKind):
            raise TypeError("identity_kind must be a SourceIdentityKind")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_start", source_start)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "row_count", int(self.row_count))
        object.__setattr__(self, "columns", columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_start": self.source_start,
            "as_of": self.as_of,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "identity_kind": self.identity_kind.value,
        }


@dataclass(frozen=True)
class TrendlineCheckpoint:
    """Source/configuration checkpoint shared by output stages."""

    checkpoint_id: str
    source: TrendlineSourceRef
    config_id: str
    execution_mode: TrendlineExecutionMode
    extractor_finality: PivotFinality

    def __post_init__(self) -> None:
        if not str(self.checkpoint_id).strip():
            raise ValueError("checkpoint_id must be non-empty")
        if not str(self.config_id).strip():
            raise ValueError("config_id must be non-empty")
        if not isinstance(self.source, TrendlineSourceRef):
            raise TypeError("source must be a TrendlineSourceRef")
        if not isinstance(self.execution_mode, TrendlineExecutionMode):
            raise TypeError("execution_mode must be a TrendlineExecutionMode")
        if not isinstance(self.extractor_finality, PivotFinality):
            raise TypeError("extractor_finality must be a PivotFinality")

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "source": self.source.to_dict(),
            "config_id": self.config_id,
            "execution_mode": self.execution_mode.value,
            "extractor_finality": self.extractor_finality.value,
        }


@dataclass(frozen=True)
class TrendlineSnapshotIdentity:
    """Logical snapshot and content revision identity."""

    snapshot_id: str
    revision_id: str
    checkpoint: TrendlineCheckpoint
    stage: TrendlineSnapshotStage
    finality: TrendlineSnapshotFinality
    content_id: str
    asset: str | None = None
    timeframe: str | None = None

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "revision_id", "content_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.checkpoint, TrendlineCheckpoint):
            raise TypeError("checkpoint must be a TrendlineCheckpoint")
        if not isinstance(self.stage, TrendlineSnapshotStage):
            raise TypeError("stage must be a TrendlineSnapshotStage")
        if not isinstance(self.finality, TrendlineSnapshotFinality):
            raise TypeError("finality must be a TrendlineSnapshotFinality")
        if (self.asset is None) != (self.timeframe is None):
            raise ValueError("asset and timeframe must be supplied together")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "revision_id": self.revision_id,
            "checkpoint": self.checkpoint.to_dict(),
            "stage": self.stage.value,
            "finality": self.finality.value,
            "content_id": self.content_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
        }


def _model_visible_columns(df: pd.DataFrame) -> tuple[str, ...]:
    preferred = ("open", "high", "low", "close", "volume")
    visible = tuple(column for column in preferred if column in df.columns)
    if visible:
        return visible
    return tuple(str(column) for column in df.columns)


def resolve_source_horizon(
    df: pd.DataFrame,
    *,
    as_of: Any | None = None,
) -> tuple[str, str, int, tuple[str, ...]]:
    """Validate frame ordering and return its exact source horizon."""

    if df.empty:
        raise ValueError("trendline source frame must be non-empty")
    if not df.index.is_monotonic_increasing:
        raise ValueError("trendline source index must be monotonic increasing")
    if not df.index.is_unique:
        raise ValueError("trendline source index must be unique")
    if not df.columns.is_unique:
        raise ValueError("trendline source columns must be unique")

    first = df.index[0]
    last = df.index[-1]
    if as_of is not None and not _same_point(as_of, last):
        raise ValueError(
            "as_of must exactly equal the final supplied frame index; "
            "pass the corresponding frame prefix for an earlier point in time"
        )
    columns = _model_visible_columns(df)
    if not columns:
        raise ValueError("trendline source frame must contain at least one column")
    if len(set(columns)) != len(columns):
        raise ValueError("trendline source columns must be unique")
    return (
        canonical_point_text(first),
        canonical_point_text(last),
        len(df),
        columns,
    )


def resolve_source_ref(
    df: pd.DataFrame,
    *,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
) -> TrendlineSourceRef:
    """Resolve one source identity, using provided refs without frame hashing."""

    source_start, final_as_of, row_count, columns = resolve_source_horizon(df, as_of=as_of)
    if source_ref is not None:
        if not isinstance(source_ref, TrendlineSourceRef):
            raise TypeError("source_ref must be a TrendlineSourceRef")
        if source_ref.source_start != source_start:
            raise ValueError("source_ref.source_start does not match supplied frame")
        if source_ref.as_of != final_as_of:
            raise ValueError("source_ref.as_of does not match supplied frame")
        if source_ref.row_count != row_count:
            raise ValueError("source_ref.row_count does not match supplied frame")
        if source_ref.columns != columns:
            raise ValueError("source_ref.columns do not match model-visible frame columns")
        return source_ref

    return TrendlineSourceRef(
        source_id=compute_source_id(
            df,
            source_start=source_start,
            as_of=final_as_of,
            row_count=row_count,
            columns=columns,
        ),
        source_start=source_start,
        as_of=final_as_of,
        row_count=row_count,
        columns=columns,
        identity_kind=SourceIdentityKind.COMPUTED,
    )


def compute_source_id(
    df: pd.DataFrame,
    *,
    source_start: str,
    as_of: str,
    row_count: int,
    columns: tuple[str, ...],
) -> str:
    """Compute one deterministic source fingerprint for a validated frame."""

    payload = {
        "source_start": source_start,
        "as_of": as_of,
        "row_count": row_count,
        "index": df.index,
        "columns": [
            {
                "name": column,
                "dtype": str(df[column].dtype),
                "values": df[column].to_numpy(copy=False),
            }
            for column in columns
        ],
    }
    return canonical_hash(
        payload,
        semantics_version=SOURCE_FINGERPRINT_SEMANTICS_VERSION,
    )


def build_config_id(
    *,
    config_payload: Any,
    extractor_name: str,
    extractor_params: Mapping[str, Any],
    extractor_identity: Mapping[str, Any],
    fitter_name: str,
    fitter_params: Mapping[str, Any],
    fitter_identity: Mapping[str, Any],
    execution_mode: TrendlineExecutionMode,
    extractor_capabilities: Any,
) -> str:
    """Compute identity for all fit-stage behaviour-affecting configuration."""

    return canonical_hash(
        {
            "config": config_payload,
            "extractor": extractor_name,
            "extractor_params": dict(extractor_params),
            "extractor_identity": extractor_identity,
            "fitter": fitter_name,
            "fitter_params": dict(fitter_params),
            "fitter_identity": fitter_identity,
            "execution_mode": execution_mode.value,
            "extractor_capabilities": extractor_capabilities,
        },
        semantics_version=CONFIG_ID_SEMANTICS_VERSION,
    )


def build_checkpoint(
    *,
    source: TrendlineSourceRef,
    config_id: str,
    execution_mode: TrendlineExecutionMode,
    extractor_finality: PivotFinality,
) -> TrendlineCheckpoint:
    """Build stable checkpoint identity from source and effective config."""

    checkpoint_id = canonical_hash(
        {
            "source": source,
            "config_id": config_id,
            "execution_mode": execution_mode,
            "extractor_finality": extractor_finality,
        },
        semantics_version=CHECKPOINT_ID_SEMANTICS_VERSION,
    )
    return TrendlineCheckpoint(
        checkpoint_id=checkpoint_id,
        source=source,
        config_id=config_id,
        execution_mode=execution_mode,
        extractor_finality=extractor_finality,
    )


def snapshot_finality_for(extractor_finality: PivotFinality) -> TrendlineSnapshotFinality:
    """Map extractor temporal capability to output snapshot finality."""

    if extractor_finality is PivotFinality.CONFIRMED_APPEND_ONLY:
        return TrendlineSnapshotFinality.CONFIRMED_AS_OF
    if extractor_finality is PivotFinality.RETROSPECTIVE_PREFIX_REVISING:
        return TrendlineSnapshotFinality.RETROSPECTIVE_REVISING
    raise ValueError(f"Unsupported extractor finality: {extractor_finality!r}")


def build_snapshot_identity(
    *,
    checkpoint: TrendlineCheckpoint,
    stage: TrendlineSnapshotStage,
    content_payload: Any,
    asset: str | None = None,
    timeframe: str | None = None,
) -> TrendlineSnapshotIdentity:
    """Build logical snapshot and content revision identities."""

    if not isinstance(stage, TrendlineSnapshotStage):
        stage = TrendlineSnapshotStage(str(stage).strip().lower())
    if (asset is None) != (timeframe is None):
        raise ValueError("asset and timeframe must be supplied together")
    content_id = canonical_hash(
        {"stage": stage.value, "payload": content_payload},
        semantics_version=CONTENT_ID_SEMANTICS_VERSION,
    )
    logical_payload = {
        "asset": asset,
        "timeframe": timeframe,
        "as_of": checkpoint.source.as_of,
        "stage": stage.value,
    }
    if asset is None and timeframe is None:
        logical_payload["source_id"] = checkpoint.source.source_id
    snapshot_id = canonical_hash(
        logical_payload,
        semantics_version=SNAPSHOT_ID_SEMANTICS_VERSION,
    )
    revision_id = canonical_hash(
        {
            "snapshot_id": snapshot_id,
            "checkpoint_id": checkpoint.checkpoint_id,
            "content_id": content_id,
        },
        semantics_version=REVISION_ID_SEMANTICS_VERSION,
    )
    return TrendlineSnapshotIdentity(
        snapshot_id=snapshot_id,
        revision_id=revision_id,
        checkpoint=checkpoint,
        stage=stage,
        finality=snapshot_finality_for(checkpoint.extractor_finality),
        content_id=content_id,
        asset=asset,
        timeframe=timeframe,
    )


__all__ = [
    "CHECKPOINT_ID_SEMANTICS_VERSION",
    "CONFIG_ID_SEMANTICS_VERSION",
    "CONTENT_ID_SEMANTICS_VERSION",
    "IDENTITY_SEMANTICS_VERSION",
    "PivotFinality",
    "REVISION_ID_SEMANTICS_VERSION",
    "SNAPSHOT_ID_SEMANTICS_VERSION",
    "SOURCE_FINGERPRINT_SEMANTICS_VERSION",
    "SourceIdentityKind",
    "TrendlineCheckpoint",
    "TrendlineExecutionMode",
    "TrendlineSnapshotFinality",
    "TrendlineSnapshotIdentity",
    "TrendlineSnapshotStage",
    "TrendlineSourceRef",
    "TrendlineIdentityProvider",
    "UnsupportedIdentityValueError",
    "build_checkpoint",
    "build_config_id",
    "build_snapshot_identity",
    "canonical_hash",
    "canonical_json",
    "canonical_point_text",
    "compute_source_id",
    "resolve_source_horizon",
    "resolve_component_identity_payload",
    "resolve_source_ref",
    "snapshot_finality_for",
]
