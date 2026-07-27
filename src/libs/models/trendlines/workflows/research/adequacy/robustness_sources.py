"""Frozen source-matrix contracts for L2-D5A robustness acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any, Mapping

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from ..data import validate_research_frame


ROBUSTNESS_SOURCE_MEMBER_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-source-member.v1"
)
ROBUSTNESS_SOURCE_EVIDENCE_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-source-evidence.v1"
)
ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION = (
    "trendlines.adequacy-robustness-source-matrix.v1"
)
ROBUSTNESS_REFERENCE_D2_BUNDLE_ID = (
    "f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f"
)
ROBUSTNESS_REFERENCE_D3_BUNDLE_ID = (
    "56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4"
)
ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID = (
    "664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663"
)
ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID = (
    "98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db"
)

ROBUSTNESS_RELATIONS = (
    "reference",
    "temporal",
    "cross_asset",
    "cross_timeframe",
)
ROBUSTNESS_SOURCE_KINDS = ("frozen_reference", "provider_single_page")
ROBUSTNESS_TIMESTAMP_SEMANTICS = "open_time"
ROBUSTNESS_AVAILABILITY_SOURCE = "exchange_close_time"
ROBUSTNESS_EXPECTED_ROWS = 312
ROBUSTNESS_REFERENCE_MEMBER_NAME = "reference-btcusdt-1h-20250101-v1"
ROBUSTNESS_MEMBER_NAMES = (
    ROBUSTNESS_REFERENCE_MEMBER_NAME,
    "temporal-btcusdt-1h-20250401-v1",
    "cross-asset-ethusdt-1h-20250401-v1",
    "cross-asset-solusdt-1h-20250401-v1",
    "cross-timeframe-btcusdt-4h-20250401-v1",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMEFRAME_RE = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>[mhd])$")


class TrendlineRobustnessSourceContractError(ValueError):
    """Raised when source-matrix scope or evidence is invalid."""


class TrendlineRobustnessRelation(str, Enum):
    """Fixed source-matrix member relationships."""

    REFERENCE = "reference"
    TEMPORAL = "temporal"
    CROSS_ASSET = "cross_asset"
    CROSS_TIMEFRAME = "cross_timeframe"


class TrendlineRobustnessSourceKind(str, Enum):
    """Permitted source origins for D5A members."""

    FROZEN_REFERENCE = "frozen_reference"
    PROVIDER_SINGLE_PAGE = "provider_single_page"


def _utc(value: Any, *, name: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrendlineRobustnessSourceContractError(
            f"{name} must be timezone-aware"
        )
    return timestamp.tz_convert("UTC").to_pydatetime()


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrendlineRobustnessSourceContractError(
            f"{name} must be a non-boolean integer"
        )
    if value < minimum:
        raise TrendlineRobustnessSourceContractError(
            f"{name} must be >= {minimum}"
        )
    return value


def _sha256(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise TrendlineRobustnessSourceContractError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return value


def _nonempty(value: Any, *, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise TrendlineRobustnessSourceContractError(f"{name} is required")
    return result


def _timeframe_delta(timeframe: str) -> timedelta:
    match = _TIMEFRAME_RE.fullmatch(timeframe)
    if match is None:
        raise TrendlineRobustnessSourceContractError(
            f"unsupported timeframe cadence: {timeframe}"
        )
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def _expected_bounds(
    spec: "TrendlineRobustnessSourceMemberSpec",
) -> tuple[datetime, datetime, datetime, datetime]:
    cadence = _timeframe_delta(spec.timeframe)
    first_event = spec.event_start
    last_event = first_event + cadence * (spec.expected_row_count - 1)
    first_available = first_event + cadence - timedelta(milliseconds=1)
    last_available = last_event + cadence - timedelta(milliseconds=1)
    return first_event, last_event, first_available, last_available


@dataclass(frozen=True)
class TrendlineRobustnessSourceMemberSpec:
    """One explicit source member in frozen D5A scope."""

    name: str
    relation: str
    asset: str
    timeframe: str
    event_start: datetime
    knowledge_cutoff: datetime
    expected_row_count: int
    source_kind: str
    provider_call_budget: int
    timestamp_semantics: str = ROBUSTNESS_TIMESTAMP_SEMANTICS
    availability_source: str = ROBUSTNESS_AVAILABILITY_SOURCE
    semantics_version: str = ROBUSTNESS_SOURCE_MEMBER_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        name = _nonempty(self.name, name="member name")
        relation = _nonempty(self.relation, name="member relation")
        source_kind = _nonempty(self.source_kind, name="member source_kind")
        asset = _nonempty(self.asset, name="member asset").upper()
        timeframe = _nonempty(self.timeframe, name="member timeframe")
        if relation not in ROBUSTNESS_RELATIONS:
            raise TrendlineRobustnessSourceContractError(
                f"unsupported member relation: {relation}"
            )
        if source_kind not in ROBUSTNESS_SOURCE_KINDS:
            raise TrendlineRobustnessSourceContractError(
                f"unsupported source kind: {source_kind}"
            )
        event_start = _utc(self.event_start, name="event_start")
        knowledge_cutoff = _utc(
            self.knowledge_cutoff,
            name="knowledge_cutoff",
        )
        if knowledge_cutoff <= event_start:
            raise TrendlineRobustnessSourceContractError(
                "knowledge_cutoff must be after event_start"
            )
        row_count = _strict_int(
            self.expected_row_count,
            name="expected_row_count",
            minimum=1,
        )
        provider_budget = _strict_int(
            self.provider_call_budget,
            name="provider_call_budget",
        )
        if source_kind == TrendlineRobustnessSourceKind.FROZEN_REFERENCE.value:
            if provider_budget != 0:
                raise TrendlineRobustnessSourceContractError(
                    "frozen_reference provider budget must be zero"
                )
        elif provider_budget != 1:
            raise TrendlineRobustnessSourceContractError(
                "provider_single_page provider budget must be one"
            )
        timestamp_semantics = _nonempty(
            self.timestamp_semantics,
            name="timestamp_semantics",
        )
        availability_source = _nonempty(
            self.availability_source,
            name="availability_source",
        )
        if timestamp_semantics != ROBUSTNESS_TIMESTAMP_SEMANTICS:
            raise TrendlineRobustnessSourceContractError(
                "only open_time timestamp semantics are supported"
            )
        if availability_source != ROBUSTNESS_AVAILABILITY_SOURCE:
            raise TrendlineRobustnessSourceContractError(
                "only exchange_close_time availability is supported"
            )
        semantics_version = _nonempty(
            self.semantics_version,
            name="semantics_version",
        )
        if semantics_version != ROBUSTNESS_SOURCE_MEMBER_SEMANTICS_VERSION:
            raise TrendlineRobustnessSourceContractError(
                "unsupported source-member semantics version"
            )
        _timeframe_delta(timeframe)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "event_start", event_start)
        object.__setattr__(self, "knowledge_cutoff", knowledge_cutoff)
        object.__setattr__(self, "expected_row_count", row_count)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "provider_call_budget", provider_budget)
        object.__setattr__(self, "timestamp_semantics", timestamp_semantics)
        object.__setattr__(self, "availability_source", availability_source)
        object.__setattr__(self, "semantics_version", semantics_version)

    def _payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "relation": self.relation,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "event_start": self.event_start.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "expected_row_count": self.expected_row_count,
            "source_kind": self.source_kind,
            "provider_call_budget": self.provider_call_budget,
            "timestamp_semantics": self.timestamp_semantics,
            "availability_source": self.availability_source,
            "semantics_version": self.semantics_version,
        }

    @property
    def member_spec_id(self) -> str:
        return canonical_hash(
            self._payload(),
            semantics_version=ROBUSTNESS_SOURCE_MEMBER_SEMANTICS_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "member_spec_id": self.member_spec_id}


@dataclass(frozen=True)
class TrendlineRobustnessSourceMemberEvidence:
    """Identity and source-bound summary for one persisted frame artifact."""

    member_spec_id: str
    artifact_id: str
    artifact_sha256: str
    source_id: str
    availability_id: str
    dataset_id: str
    research_configuration_id: str
    preparation_id: str
    row_count: int
    first_event_at: datetime
    last_event_at: datetime
    first_availability_at: datetime
    last_availability_at: datetime
    provider_calls: int
    page_count: int
    semantics_version: str = ROBUSTNESS_SOURCE_EVIDENCE_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        member_spec_id = _sha256(self.member_spec_id, name="member_spec_id")
        artifact_id = _sha256(self.artifact_id, name="artifact_id")
        artifact_sha256 = _sha256(
            self.artifact_sha256,
            name="artifact_sha256",
        )
        source_id = _sha256(self.source_id, name="source_id")
        availability_id = _sha256(
            self.availability_id,
            name="availability_id",
        )
        dataset_id = _sha256(self.dataset_id, name="dataset_id")
        configuration_id = _sha256(
            self.research_configuration_id,
            name="research_configuration_id",
        )
        preparation_id = _sha256(self.preparation_id, name="preparation_id")
        row_count = _strict_int(self.row_count, name="row_count", minimum=1)
        first_event = _utc(self.first_event_at, name="first_event_at")
        last_event = _utc(self.last_event_at, name="last_event_at")
        first_available = _utc(
            self.first_availability_at,
            name="first_availability_at",
        )
        last_available = _utc(
            self.last_availability_at,
            name="last_availability_at",
        )
        if first_event > last_event:
            raise TrendlineRobustnessSourceContractError(
                "event bounds must be ordered"
            )
        if first_available > last_available:
            raise TrendlineRobustnessSourceContractError(
                "availability bounds must be ordered"
            )
        provider_calls = _strict_int(
            self.provider_calls,
            name="provider_calls",
        )
        page_count = _strict_int(self.page_count, name="page_count")
        if self.semantics_version != ROBUSTNESS_SOURCE_EVIDENCE_SEMANTICS_VERSION:
            raise TrendlineRobustnessSourceContractError(
                "unsupported source-evidence semantics version"
            )
        object.__setattr__(self, "member_spec_id", member_spec_id)
        object.__setattr__(self, "artifact_id", artifact_id)
        object.__setattr__(self, "artifact_sha256", artifact_sha256)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "availability_id", availability_id)
        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "research_configuration_id", configuration_id)
        object.__setattr__(self, "preparation_id", preparation_id)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "first_event_at", first_event)
        object.__setattr__(self, "last_event_at", last_event)
        object.__setattr__(self, "first_availability_at", first_available)
        object.__setattr__(self, "last_availability_at", last_available)
        object.__setattr__(self, "provider_calls", provider_calls)
        object.__setattr__(self, "page_count", page_count)

    def _payload(self) -> dict[str, Any]:
        return {
            "member_spec_id": self.member_spec_id,
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "source_id": self.source_id,
            "availability_id": self.availability_id,
            "dataset_id": self.dataset_id,
            "research_configuration_id": self.research_configuration_id,
            "preparation_id": self.preparation_id,
            "row_count": self.row_count,
            "first_event_at": self.first_event_at.isoformat(),
            "last_event_at": self.last_event_at.isoformat(),
            "first_availability_at": self.first_availability_at.isoformat(),
            "last_availability_at": self.last_availability_at.isoformat(),
            "provider_calls": self.provider_calls,
            "page_count": self.page_count,
            "semantics_version": self.semantics_version,
        }

    @property
    def member_evidence_id(self) -> str:
        return canonical_hash(
            self._payload(),
            semantics_version=ROBUSTNESS_SOURCE_EVIDENCE_SEMANTICS_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "member_evidence_id": self.member_evidence_id}


def validate_robustness_source_frame(
    frame: pd.DataFrame,
    spec: TrendlineRobustnessSourceMemberSpec,
) -> pd.DataFrame:
    """Validate exact D5A cadence, availability and complete-bar grid."""

    if not isinstance(spec, TrendlineRobustnessSourceMemberSpec):
        raise TypeError("spec must be a TrendlineRobustnessSourceMemberSpec")
    try:
        normalized, semantics, provenance = validate_research_frame(
            frame,
            spec.timeframe,
            knowledge_cutoff=spec.knowledge_cutoff,
        )
    except (TypeError, ValueError) as exc:
        raise TrendlineRobustnessSourceContractError(
            f"invalid source frame for {spec.name}: {exc}"
        ) from exc
    if semantics.value != spec.timestamp_semantics:
        raise TrendlineRobustnessSourceContractError(
            "frame timestamp semantics differ from member spec"
        )
    if provenance.value != spec.availability_source:
        raise TrendlineRobustnessSourceContractError(
            "frame availability source differs from member spec"
        )
    if normalized.index.name != "timestamp":
        raise TrendlineRobustnessSourceContractError(
            "source frame index name must be timestamp"
        )
    if len(normalized) != spec.expected_row_count:
        raise TrendlineRobustnessSourceContractError(
            f"expected {spec.expected_row_count} rows, got {len(normalized)}"
        )
    cadence = _timeframe_delta(spec.timeframe)
    expected_events = pd.date_range(
        start=pd.Timestamp(spec.event_start),
        periods=spec.expected_row_count,
        freq=pd.Timedelta(cadence),
        name="timestamp",
    )
    actual_events = pd.DatetimeIndex(normalized.index)
    if not actual_events.equals(expected_events):
        raise TrendlineRobustnessSourceContractError(
            "source event grid is not exact, ordered and complete"
        )
    expected_availability = expected_events + pd.Timedelta(cadence) - pd.Timedelta(
        milliseconds=1
    )
    actual_availability = pd.DatetimeIndex(normalized["bar_available_at"])
    if not actual_availability.equals(expected_availability):
        raise TrendlineRobustnessSourceContractError(
            "source availability grid is not exact exchange close-time grid"
        )
    if actual_availability[-1].to_pydatetime() != spec.knowledge_cutoff:
        raise TrendlineRobustnessSourceContractError(
            "last availability does not equal knowledge cutoff"
        )
    return normalized


def build_robustness_source_member_evidence(
    spec: TrendlineRobustnessSourceMemberSpec,
    frame: pd.DataFrame,
    *,
    artifact_id: str,
    artifact_sha256: str,
    source_id: str,
    availability_id: str,
    dataset_id: str,
    research_configuration_id: str,
    preparation_id: str,
    provider_calls: int,
    page_count: int,
) -> TrendlineRobustnessSourceMemberEvidence:
    """Build one evidence row after strict frame and accounting checks."""

    normalized = validate_robustness_source_frame(frame, spec)
    evidence = TrendlineRobustnessSourceMemberEvidence(
        member_spec_id=spec.member_spec_id,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
        source_id=source_id,
        availability_id=availability_id,
        dataset_id=dataset_id,
        research_configuration_id=research_configuration_id,
        preparation_id=preparation_id,
        row_count=len(normalized),
        first_event_at=normalized.index[0].to_pydatetime(),
        last_event_at=normalized.index[-1].to_pydatetime(),
        first_availability_at=pd.Timestamp(
            normalized["bar_available_at"].iloc[0]
        ).to_pydatetime(),
        last_availability_at=pd.Timestamp(
            normalized["bar_available_at"].iloc[-1]
        ).to_pydatetime(),
        provider_calls=provider_calls,
        page_count=page_count,
    )
    validate_robustness_source_member_evidence(spec, evidence)
    return evidence


def validate_robustness_source_member_evidence(
    spec: TrendlineRobustnessSourceMemberSpec,
    evidence: TrendlineRobustnessSourceMemberEvidence,
) -> None:
    """Validate evidence accounting and expected temporal bounds."""

    if not isinstance(evidence, TrendlineRobustnessSourceMemberEvidence):
        raise TypeError("evidence must be a TrendlineRobustnessSourceMemberEvidence")
    if evidence.member_spec_id != spec.member_spec_id:
        raise TrendlineRobustnessSourceContractError(
            f"evidence member_spec_id differs for {spec.name}"
        )
    if evidence.row_count != spec.expected_row_count:
        raise TrendlineRobustnessSourceContractError(
            f"evidence row count differs for {spec.name}"
        )
    expected = _expected_bounds(spec)
    actual = (
        evidence.first_event_at,
        evidence.last_event_at,
        evidence.first_availability_at,
        evidence.last_availability_at,
    )
    if actual != expected:
        raise TrendlineRobustnessSourceContractError(
            f"evidence temporal bounds differ for {spec.name}"
        )
    if evidence.provider_calls != spec.provider_call_budget:
        raise TrendlineRobustnessSourceContractError(
            f"provider call count differs for {spec.name}"
        )
    expected_pages = 0 if spec.source_kind == "frozen_reference" else 1
    if evidence.page_count != expected_pages:
        raise TrendlineRobustnessSourceContractError(
            f"page count differs for {spec.name}"
        )


def _expected_member_specs() -> tuple[TrendlineRobustnessSourceMemberSpec, ...]:
    utc = timezone.utc
    return (
        TrendlineRobustnessSourceMemberSpec(
            name=ROBUSTNESS_REFERENCE_MEMBER_NAME,
            relation="reference",
            asset="BTCUSDT",
            timeframe="1h",
            event_start=datetime(2025, 1, 1, tzinfo=utc),
            knowledge_cutoff=datetime(2025, 1, 13, 23, 59, 59, 999000, tzinfo=utc),
            expected_row_count=312,
            source_kind="frozen_reference",
            provider_call_budget=0,
        ),
        TrendlineRobustnessSourceMemberSpec(
            name="temporal-btcusdt-1h-20250401-v1",
            relation="temporal",
            asset="BTCUSDT",
            timeframe="1h",
            event_start=datetime(2025, 4, 1, tzinfo=utc),
            knowledge_cutoff=datetime(2025, 4, 13, 23, 59, 59, 999000, tzinfo=utc),
            expected_row_count=312,
            source_kind="provider_single_page",
            provider_call_budget=1,
        ),
        TrendlineRobustnessSourceMemberSpec(
            name="cross-asset-ethusdt-1h-20250401-v1",
            relation="cross_asset",
            asset="ETHUSDT",
            timeframe="1h",
            event_start=datetime(2025, 4, 1, tzinfo=utc),
            knowledge_cutoff=datetime(2025, 4, 13, 23, 59, 59, 999000, tzinfo=utc),
            expected_row_count=312,
            source_kind="provider_single_page",
            provider_call_budget=1,
        ),
        TrendlineRobustnessSourceMemberSpec(
            name="cross-asset-solusdt-1h-20250401-v1",
            relation="cross_asset",
            asset="SOLUSDT",
            timeframe="1h",
            event_start=datetime(2025, 4, 1, tzinfo=utc),
            knowledge_cutoff=datetime(2025, 4, 13, 23, 59, 59, 999000, tzinfo=utc),
            expected_row_count=312,
            source_kind="provider_single_page",
            provider_call_budget=1,
        ),
        TrendlineRobustnessSourceMemberSpec(
            name="cross-timeframe-btcusdt-4h-20250401-v1",
            relation="cross_timeframe",
            asset="BTCUSDT",
            timeframe="4h",
            event_start=datetime(2025, 4, 1, tzinfo=utc),
            knowledge_cutoff=datetime(2025, 5, 22, 23, 59, 59, 999000, tzinfo=utc),
            expected_row_count=312,
            source_kind="provider_single_page",
            provider_call_budget=1,
        ),
    )


def frozen_robustness_source_member_specs() -> tuple[
    TrendlineRobustnessSourceMemberSpec, ...
]:
    """Return exact ordered D5A source scope."""

    return _expected_member_specs()


def _validate_member_spec_order(
    specs: tuple[TrendlineRobustnessSourceMemberSpec, ...],
) -> None:
    expected_specs = _expected_member_specs()
    if tuple(spec.to_dict() for spec in specs) != tuple(
        spec.to_dict() for spec in expected_specs
    ):
        raise TrendlineRobustnessSourceContractError(
            "D5A members must use exact frozen specifications and order"
        )
    if tuple(spec.name for spec in specs) != tuple(dict.fromkeys(spec.name for spec in specs)):
        raise TrendlineRobustnessSourceContractError("member names must be unique")
    if len({(spec.asset, spec.timeframe, spec.event_start, spec.knowledge_cutoff) for spec in specs}) != len(specs):
        raise TrendlineRobustnessSourceContractError(
            "asset/timeframe/window members must be unique"
        )
    reference = specs[0]
    if reference.relation != "reference" or reference.source_kind != "frozen_reference":
        raise TrendlineRobustnessSourceContractError("first member must be reference")
    if reference.provider_call_budget != 0:
        raise TrendlineRobustnessSourceContractError("reference provider budget must be zero")
    fresh = specs[1:]
    if any(spec.source_kind != "provider_single_page" for spec in fresh):
        raise TrendlineRobustnessSourceContractError("fresh members require provider source kind")
    if any(spec.provider_call_budget != 1 for spec in fresh):
        raise TrendlineRobustnessSourceContractError("fresh members require one-call budget")
    fresh_1h = fresh[:3]
    if len({(spec.event_start, spec.knowledge_cutoff) for spec in fresh_1h}) != 1:
        raise TrendlineRobustnessSourceContractError(
            "fresh 1h members must share event and knowledge bounds"
        )
    if specs[4].asset != "BTCUSDT" or specs[4].timeframe != "4h":
        raise TrendlineRobustnessSourceContractError(
            "cross-timeframe member must be BTCUSDT 4h"
        )
    reference_start = reference.event_start
    reference_end = reference.knowledge_cutoff
    for spec in fresh:
        if spec.event_start <= reference_end and spec.knowledge_cutoff >= reference_start:
            raise TrendlineRobustnessSourceContractError(
                f"fresh member overlaps reference window: {spec.name}"
            )


@dataclass(frozen=True)
class TrendlineRobustnessSourceMatrixBundle:
    """Content-addressed, ordered D5A source matrix."""

    member_specs: tuple[TrendlineRobustnessSourceMemberSpec, ...]
    member_evidence: tuple[TrendlineRobustnessSourceMemberEvidence, ...]
    reference_d2_bundle_id: str
    reference_d3_bundle_id: str
    reference_d4a_bundle_id: str
    reference_d4b_bundle_id: str
    semantics_version: str = ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        specs = tuple(self.member_specs)
        evidence = tuple(self.member_evidence)
        if not all(isinstance(value, TrendlineRobustnessSourceMemberSpec) for value in specs):
            raise TrendlineRobustnessSourceContractError("member_specs must be typed")
        if not all(isinstance(value, TrendlineRobustnessSourceMemberEvidence) for value in evidence):
            raise TrendlineRobustnessSourceContractError("member_evidence must be typed")
        if len(specs) != len(evidence):
            raise TrendlineRobustnessSourceContractError(
                "member spec/evidence counts must match"
            )
        _validate_member_spec_order(specs)
        for spec, row in zip(specs, evidence):
            validate_robustness_source_member_evidence(spec, row)
        for name, value, expected in (
            ("reference_d2_bundle_id", self.reference_d2_bundle_id, ROBUSTNESS_REFERENCE_D2_BUNDLE_ID),
            ("reference_d3_bundle_id", self.reference_d3_bundle_id, ROBUSTNESS_REFERENCE_D3_BUNDLE_ID),
            ("reference_d4a_bundle_id", self.reference_d4a_bundle_id, ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID),
            ("reference_d4b_bundle_id", self.reference_d4b_bundle_id, ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID),
        ):
            identity = _sha256(value, name=name)
            if identity != expected:
                raise TrendlineRobustnessSourceContractError(
                    f"{name} differs from committed reference evidence"
                )
        if self.semantics_version != ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION:
            raise TrendlineRobustnessSourceContractError(
                "unsupported source-matrix semantics version"
            )
        object.__setattr__(self, "member_specs", specs)
        object.__setattr__(self, "member_evidence", evidence)

    def _payload(self) -> dict[str, Any]:
        return {
            "member_specs": [value.to_dict() for value in self.member_specs],
            "member_evidence": [value.to_dict() for value in self.member_evidence],
            "reference_d2_bundle_id": self.reference_d2_bundle_id,
            "reference_d3_bundle_id": self.reference_d3_bundle_id,
            "reference_d4a_bundle_id": self.reference_d4a_bundle_id,
            "reference_d4b_bundle_id": self.reference_d4b_bundle_id,
            "semantics_version": self.semantics_version,
        }

    @property
    def robustness_source_matrix_bundle_id(self) -> str:
        return canonical_hash(
            self._payload(),
            semantics_version=ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "robustness_source_matrix_bundle_id": self.robustness_source_matrix_bundle_id,
        }


def build_robustness_source_matrix_bundle(
    member_specs: tuple[TrendlineRobustnessSourceMemberSpec, ...],
    member_evidence: tuple[TrendlineRobustnessSourceMemberEvidence, ...],
) -> TrendlineRobustnessSourceMatrixBundle:
    """Build and validate one exact five-member source matrix."""

    return TrendlineRobustnessSourceMatrixBundle(
        member_specs=tuple(member_specs),
        member_evidence=tuple(member_evidence),
        reference_d2_bundle_id=ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
        reference_d3_bundle_id=ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
        reference_d4a_bundle_id=ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
        reference_d4b_bundle_id=ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
    )


def _config_has_asset_timeframe(config: Any, asset: str, timeframe: str) -> bool:
    assets = getattr(config, "assets", None)
    if not isinstance(assets, Mapping) or asset not in assets:
        return False
    asset_config = assets[asset]
    timeframes = getattr(asset_config, "timeframes", None)
    return isinstance(timeframes, Mapping) and timeframe in timeframes


def validate_robustness_source_matrix_bundle(
    bundle: TrendlineRobustnessSourceMatrixBundle,
    *,
    trendlines_config: Any | None = None,
) -> None:
    """Validate matrix scope, identities and optional canonical YAML coverage."""

    if not isinstance(bundle, TrendlineRobustnessSourceMatrixBundle):
        raise TypeError("bundle must be a TrendlineRobustnessSourceMatrixBundle")
    _validate_member_spec_order(bundle.member_specs)
    for spec, evidence in zip(bundle.member_specs, bundle.member_evidence):
        validate_robustness_source_member_evidence(spec, evidence)
        if trendlines_config is not None and not _config_has_asset_timeframe(
            trendlines_config,
            spec.asset,
            spec.timeframe,
        ):
            raise TrendlineRobustnessSourceContractError(
                f"asset/timeframe is absent from canonical YAML: {spec.asset} {spec.timeframe}"
            )
    if bundle.robustness_source_matrix_bundle_id != canonical_hash(
        bundle._payload(),
        semantics_version=ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION,
    ):
        raise TrendlineRobustnessSourceContractError(
            "robustness_source_matrix_bundle_id does not match contents"
        )


__all__ = [
    "ROBUSTNESS_AVAILABILITY_SOURCE",
    "ROBUSTNESS_EXPECTED_ROWS",
    "ROBUSTNESS_MEMBER_NAMES",
    "ROBUSTNESS_REFERENCE_D2_BUNDLE_ID",
    "ROBUSTNESS_REFERENCE_D3_BUNDLE_ID",
    "ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID",
    "ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID",
    "ROBUSTNESS_REFERENCE_MEMBER_NAME",
    "ROBUSTNESS_RELATIONS",
    "ROBUSTNESS_SOURCE_KINDS",
    "ROBUSTNESS_SOURCE_MATRIX_SEMANTICS_VERSION",
    "ROBUSTNESS_SOURCE_MEMBER_SEMANTICS_VERSION",
    "ROBUSTNESS_TIMESTAMP_SEMANTICS",
    "TrendlineRobustnessRelation",
    "TrendlineRobustnessSourceContractError",
    "TrendlineRobustnessSourceKind",
    "TrendlineRobustnessSourceMatrixBundle",
    "TrendlineRobustnessSourceMemberEvidence",
    "TrendlineRobustnessSourceMemberSpec",
    "build_robustness_source_matrix_bundle",
    "build_robustness_source_member_evidence",
    "frozen_robustness_source_member_specs",
    "validate_robustness_source_frame",
    "validate_robustness_source_matrix_bundle",
    "validate_robustness_source_member_evidence",
]
