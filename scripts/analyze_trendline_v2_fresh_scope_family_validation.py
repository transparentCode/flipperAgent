"""Run the bounded Phase 9C.2 fresh-scope eligibility-family study.

The runner owns only research orchestration and artifact accounting.  It uses
the public Trendline V2 discovery API over the immutable Phase 9C.1 inputs and
never imports a network adapter, runtime selector, tracker, or evaluator.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import tempfile
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from libs.models.trendline_v2.api import discover_trendlines
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ProviderDiagnostics,
    ProviderInput,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
)
from libs.models.trendline_v2.domain.candidates import LineCandidate
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame
from scripts import freeze_trendline_v2_fresh_scope_sources as phase9c1


UTC = timezone.utc
NANOSECONDS = 1_000_000_000
DAY_SECONDS = 86_400.0
SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c1_fresh_scope_sources/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
SUPERSEDED_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation_superseded/20260522_20260701_pre_physical_horizon_remediation"
)
SOURCE_COMMIT = "2d1da900399d9dc9a4d0dc2c9791f668b8b9fb86"
COHORT_CONTRACT_ID = "55fabdf05929e923776d810c9958b26c44a8e85a5b92f73ec3027ab92dfcf00a"
COHORT_SOURCE_IDENTITY = "c8cb7ecb7337020d09b3fe7a3026a14b84d07734252aa9bfa3f563d30f36ae72"
SOURCE_DECISION_ID = "215600f4b80c356e95e969948dfd12ba57b17a55b140c25a8ea78ad3c9c15424"
SOURCE_MANIFEST_ID = "e2afa4234054396ce5a7343eeb30f0e409fb56f0766c9c11a067180162374d56"
SOURCE_INVENTORY_SHA256 = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
SUPERSEDED_INVENTORY_SHA256 = "c4dde7c52c8c9735af218ee6e53353f312c5c36dea7a1345c0fc7c93b8a3cc20"
SUPERSEDED_MANIFEST_ID = "1870c98fbfa14c493c236017ba08721979aa5b63ec6dec5059bd340ce8eb3c2c"
SUPERSEDED_DECISION_ID = "ab6ec96989afdcdb03b2826bb4bcd4e9b1732be8fbec2e3b78e4db0284908320"
SUPERSEDED_VALIDATION_LOCK_ID = "415f1e6a8ccc78bb9987dd9fc52b2ec1dd3f4cc76417745c4e991522294bc20e"
FOUNDATION_CONFIG_ID = "02cdb171472b8ede327c2466c08ce295d72b16e34367047928757f80fd4f8396"
PROVIDER_CONFIG_ID = "2aea7331fad4032db1803f21faa2df42fb2142f365331edce0723db5c55a2e6c"
COMBINED_CONFIG_ID = "7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636"
PROVIDER_CONTRACT_ID = "13828b02b649fc002681137bae82761d91283e8d1f19d3a3fbd719b8f1cf0e99"
SELECTOR_CONTRACT_ID = "1b19f356e186b5fa6ee802e7b738ca06edd7fccdf65c768841911f5a10bc3eb1"
MIDPOINT = datetime(2026, 6, 11, tzinfo=UTC)
STUDY_SCHEMA = "trendline_v2_phase_9c2_fresh_scope_family_validation_v1"
RESULT_ID_NAMESPACE = "trendline_v2_phase_9c2_provider_result_v1"
STRUCTURE_NAMESPACE = "trendline_v2_phase_9c2_candidate_structure_v1"
VALIDATION_LOCK_NAMESPACE = "trendline_v2_phase_9c2_validation_lock_v1"
MANIFEST_NAMESPACE = "trendline_v2_phase_9c2_manifest_v1"

DATASET_ORDER = (
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "1h"),
    ("ETHUSDT", "4h"),
    ("SUIUSDT", "1h"),
    ("SUIUSDT", "4h"),
)
VALIDATION_DATASETS = tuple(f"{asset.lower()}_{timeframe}" for asset, timeframe in DATASET_ORDER[:4])
HOLDOUT_DATASETS = tuple(f"{asset.lower()}_{timeframe}" for asset, timeframe in DATASET_ORDER[4:])
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
HORIZON_BARS_BY_TIMEFRAME = {
    "1h": {"24h": 24, "48h": 48, "96h": 96},
    "4h": {"24h": 6, "48h": 12, "96h": 24},
}
HORIZON_NAMES = ("24h", "48h", "96h")
HORIZONS = tuple((name, None) for name in HORIZON_NAMES)
ROLES = ("support", "resistance")
SEGMENTS = ("early", "late")
FAMILY_IDS = (
    "all_candidates_control_v1",
    "adjacent_extrema_only_v1",
    "skip_le_1_v1",
    "skip_le_3_v1",
    "latest_valid_predecessor_v1",
    "earliest_valid_predecessor_v1",
    "max_minimum_body_clearance_v1",
    "max_minimum_anchor_prominence_v1",
)
FAMILY_DEFINITIONS = (
    {
        "family_id": FAMILY_IDS[0],
        "kind": "control",
        "membership": "all persisted Phase 9B.1 birth records",
    },
    {
        "family_id": FAMILY_IDS[1],
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count == 0",
    },
    {
        "family_id": FAMILY_IDS[2],
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count <= 1",
    },
    {
        "family_id": FAMILY_IDS[3],
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count <= 3",
    },
    {
        "family_id": FAMILY_IDS[4],
        "kind": "one_per_second_anchor",
        "membership": "greatest first_anchor_time, then structure ID, then candidate ID",
    },
    {
        "family_id": FAMILY_IDS[5],
        "kind": "one_per_second_anchor",
        "membership": "smallest first_anchor_time, then structure ID, then candidate ID",
    },
    {
        "family_id": FAMILY_IDS[6],
        "kind": "one_per_second_anchor",
        "membership": "greatest minimum_body_clearance_bps, then structure ID, then candidate ID",
    },
    {
        "family_id": FAMILY_IDS[7],
        "kind": "one_per_second_anchor",
        "membership": "greatest minimum_anchor_prominence_bps, then structure ID, then candidate ID",
    },
)
SELECTOR_FIELDS = (
    "candidate_id",
    "candidate_structure_id",
    "role",
    "first_anchor_id",
    "second_anchor_id",
    "first_anchor_time",
    "second_anchor_time",
    "same_role_extrema_skip_count",
    "minimum_body_clearance_bps",
    "minimum_anchor_prominence_bps",
)
FORBIDDEN_SELECTOR_FIELDS = (
    "evaluations",
    "future_contact_count",
    "future_body_violation_count",
    "has_exact_contact",
    "survives_exact_side",
    "contact_and_survives_exact_side",
    "first_contact_offset_bars",
    "first_body_violation_offset_bars",
    "chronological_outcome_aggregates",
)
FIXED_PROVIDER_VALUES = {
    "lookback_duration_seconds": 10_540_800.0,
    "left_confirmation_bars": 1,
    "right_confirmation_bars": 1,
    "min_extrema_per_role": 2,
    "max_hypotheses": 100_000,
    "max_output_candidates": 10_000,
}
VALIDATION_GATES = {
    "minimum_second_anchor_coverage_ratio": 0.90,
    "maximum_candidate_fraction_of_control": 0.35,
    "maximum_finite_overlap_p95_ratio_vs_control": 0.15,
    "maximum_admissions_p95": 8,
    "minimum_group_survival_delta_median": -0.10,
    "minimum_group_contact_and_survival_delta_median": -0.05,
    "maximum_survival_delta_below_minus_020": 2,
    "maximum_contact_and_survival_delta_below_minus_010": 2,
    "minimum_evaluated_second_anchor_groups": 20,
    "minimum_evaluated_groups_per_role_segment": 5,
}


class StudyArtifactError(RuntimeError):
    """Expected bounded-study validation or artifact failure."""


class ProviderScopeBlocked(StudyArtifactError):
    """The fixed provider scope cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class DatasetContext:
    dataset_id: str
    asset: str
    timeframe: str
    input_data: ProviderInput
    dataset_source_identity: str
    request_order: int

    @property
    def interval(self) -> timedelta:
        return timedelta(seconds=INTERVAL_SECONDS[self.timeframe])


@dataclass(frozen=True, slots=True)
class CohortContext:
    datasets: tuple[DatasetContext, ...]
    cohort_contract_id: str
    cohort_source_identity: str
    source_inventory: tuple[dict[str, Any], ...]
    source_inventory_sha256: str
    source_decision_id: str
    source_manifest_id: str


ProviderCall = Callable[..., ProviderResult]
BeforeSUIHook = Callable[[Path, str], None]


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise StudyArtifactError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise StudyArtifactError(f"non-canonical JSON artifact: {path}")
    return value


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_from_ns(value: int) -> datetime:
    seconds, remainder = divmod(int(value), NANOSECONDS)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=remainder // 1_000
    )


def _finite(value: object, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StudyArtifactError(f"{field_name} is not numeric") from exc
    if not math.isfinite(result):
        raise StudyArtifactError(f"{field_name} is not finite")
    return result


def _bps(delta: float, base: float, *, field_name: str) -> float:
    denominator = _finite(base, field_name=f"{field_name}.base")
    if denominator == 0.0:
        raise StudyArtifactError(f"{field_name} base cannot be zero")
    return _finite(delta / abs(denominator) * 10_000.0, field_name=field_name)


def _percentile95(values: Sequence[float | int]) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _stats(values: Sequence[float | int]) -> dict[str, Any]:
    if not values:
        return {"minimum": None, "median": None, "p95": None, "maximum": None}
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "p95": _percentile95(values),
        "maximum": max(values),
    }


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise StudyArtifactError(f"source root is missing: {root}")
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(result)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False)
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output: {path}")
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise StudyArtifactError("cannot serialize empty CSV")
    buffer = io.StringIO(newline="")
    fieldnames = tuple(rows[0])
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows({field: row.get(field) for field in fieldnames} for row in rows)
    return buffer.getvalue().encode("utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    data = _csv_bytes(rows)
    output = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False)
    temporary = Path(output.name)
    try:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
        output.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output: {path}")
        os.replace(temporary, path)
    except Exception:
        output.close()
        temporary.unlink(missing_ok=True)
        raise


def _foundation_config() -> ResolvedTrendlineV2Config:
    result = resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )
    if result.semantic_hash != FOUNDATION_CONFIG_ID:
        raise StudyArtifactError("foundation configuration identity drift")
    return result


def _provider_config() -> ConfirmedExtremaPairConfig:
    result = ConfirmedExtremaPairConfig(**FIXED_PROVIDER_VALUES)
    if result.semantic_hash != PROVIDER_CONFIG_ID or result.provider_contract_identity != PROVIDER_CONTRACT_ID:
        raise StudyArtifactError("provider configuration identity drift")
    return result


def _frame_for(dataset: DatasetContext) -> ConfirmedOHLCVFrame:
    data = dataset.input_data
    index = pd.to_datetime(data.timestamps, unit="ns", utc=True)
    frame = pd.DataFrame(
        {
            "open": data.open,
            "high": data.high,
            "low": data.low,
            "close": data.close,
            "volume": data.volume,
        },
        index=index,
    )
    return ConfirmedOHLCVFrame.from_frame(
        frame,
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
    )


def _load_cohort(source_root: Path = SOURCE_ROOT) -> CohortContext:
    try:
        verified = phase9c1.verify_bundle(source_root)
        inventory = _inventory(source_root)
    except Exception as exc:
        raise StudyArtifactError("Phase 9C.1 source verification failed") from exc
    if verified["cohort_contract_id"] != COHORT_CONTRACT_ID:
        raise StudyArtifactError("Phase 9C.1 cohort contract drift")
    if verified["cohort_source_identity"] != COHORT_SOURCE_IDENTITY:
        raise StudyArtifactError("Phase 9C.1 cohort source identity drift")
    if verified["decision_id"] != SOURCE_DECISION_ID or verified["manifest_id"] != SOURCE_MANIFEST_ID:
        raise StudyArtifactError("Phase 9C.1 decision or manifest drift")
    if _inventory_sha256(inventory) != SOURCE_INVENTORY_SHA256:
        raise StudyArtifactError("Phase 9C.1 complete inventory drift")
    reports = {report["dataset_id"]: report for report in verified["dataset_reports"]}
    datasets: list[DatasetContext] = []
    expected_input_ids = {
        "btcusdt_1h": "dde3d8a82109e4eda6dfec8b1a128e7896dc6845bcd47bab5754eefcc79623e9",
        "btcusdt_4h": "2de51ce8f76920b92269fe94c78efb636944d4c804d5dd723875903df5bc8aa8",
        "ethusdt_1h": "483d29e4aa2b32d85d00f8a58f956f84dfbf3ba14f6e80b80210968e85424469",
        "ethusdt_4h": "35965d4fe6b90298340a130063596011b3e0bcbff26463d68525f6097a762239",
        "suiusdt_1h": "713f24aa59bb0d8f9dbb4040cdbd56fa89c1890c263d9b9c6bc72c3c669679ae",
        "suiusdt_4h": "7a43ce7b5b8489e46edebe61a32144046c2309387a1998077f4ba2d08214cfae",
    }
    for order, (asset, timeframe) in enumerate(DATASET_ORDER, start=1):
        dataset_id = f"{asset.lower()}_{timeframe}"
        payload = phase9c1._load_json(source_root / "datasets" / dataset_id / "provider_input.json")
        data = phase9c1._provider_input_from_dict(payload)
        report = reports.get(dataset_id)
        if report is None or data.input_identity != expected_input_ids[dataset_id]:
            raise StudyArtifactError(f"Phase 9C.1 input identity drift: {dataset_id}")
        if data.row_count != (960 if timeframe == "1h" else 240):
            raise StudyArtifactError(f"Phase 9C.1 row-count drift: {dataset_id}")
        if report["input_identity"] != data.input_identity:
            raise StudyArtifactError(f"Phase 9C.1 report/input mismatch: {dataset_id}")
        datasets.append(
            DatasetContext(
                dataset_id=dataset_id,
                asset=asset,
                timeframe=timeframe,
                input_data=data,
                dataset_source_identity=report["dataset_source_identity"],
                request_order=order,
            )
        )
    return CohortContext(
        datasets=tuple(datasets),
        cohort_contract_id=COHORT_CONTRACT_ID,
        cohort_source_identity=COHORT_SOURCE_IDENTITY,
        source_inventory=inventory,
        source_inventory_sha256=SOURCE_INVENTORY_SHA256,
        source_decision_id=SOURCE_DECISION_ID,
        source_manifest_id=SOURCE_MANIFEST_ID,
    )


def _typed_result(payload: Mapping[str, Any]) -> ProviderResult:
    try:
        request_payload = payload["request"]
        input_payload = request_payload["input_data"]
        model = request_payload["config"]["model"]
        active = request_payload["provider_config"]["active_config"]
        config = ResolvedTrendlineV2Config(
            model_name=model["name"],
            model_version=model["version"],
            schema_version=model["schema_version"],
            provenance=request_payload["config"]["provenance"],
        )
        provider_config = ConfirmedExtremaPairConfig(**dict(active))
        input_data = ProviderInput(
            asset=input_payload["asset"],
            timeframe=input_payload["timeframe"],
            observed_at=datetime.fromisoformat(input_payload["observed_at"].replace("Z", "+00:00")),
            confirmed_through=datetime.fromisoformat(input_payload["confirmed_through"].replace("Z", "+00:00")),
            timestamps=tuple(input_payload["timestamps"]),
            open=tuple(input_payload["open"]),
            high=tuple(input_payload["high"]),
            low=tuple(input_payload["low"]),
            close=tuple(input_payload["close"]),
            volume=tuple(input_payload["volume"]),
        )
        request = ProviderRequest(input_data=input_data, config=config, provider_config=provider_config)
        result = ProviderResult(
            provider_name=payload["provider_name"],
            provider_version=payload["provider_version"],
            request=request,
            status=payload["status"],
            candidates=tuple(LineCandidate.from_dict(item) for item in payload["candidates"]),
            evidence=tuple(ConfirmedExtremaPairEvidence.from_dict(item) for item in payload["evidence"]),
            diagnostics=ProviderDiagnostics(**dict(payload["diagnostics"])),
            reason=payload["reason"],
            detail=payload["detail"],
        )
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise StudyArtifactError("provider result typed validation failed") from exc
    if canonical_json(result.to_dict()) != canonical_json(dict(payload)):
        raise StudyArtifactError("provider result semantic round-trip mismatch")
    return result


def _provider_result_id(result: ProviderResult) -> str:
    return deterministic_hash(RESULT_ID_NAMESPACE, result.to_dict())


@dataclass(frozen=True, slots=True)
class ResearchExtremum:
    kind: str
    source_position: int
    confirmation_position: int
    price: float


def _extract_extrema(values: Sequence[float], *, kind: str) -> tuple[ResearchExtremum, ...]:
    result: list[ResearchExtremum] = []
    for position in range(1, len(values) - 1):
        value = float(values[position])
        left = float(values[position - 1])
        right = float(values[position + 1])
        valid = value > left and (value >= right if kind == "high" else value <= right)
        if kind == "low":
            valid = value < left and value <= right
        if valid:
            result.append(ResearchExtremum(kind, position, position + 1, value))
    return tuple(result)


def _extrema_by_role(data: ProviderInput) -> dict[str, tuple[ResearchExtremum, ...]]:
    return {
        "support": _extract_extrema(data.low, kind="low"),
        "resistance": _extract_extrema(data.high, kind="high"),
    }


def _structure_id(candidate: LineCandidate) -> str:
    return deterministic_hash(
        STRUCTURE_NAMESPACE,
        {
            "asset": candidate.asset,
            "timeframe": candidate.timeframe,
            "role": candidate.role.value,
            "geometry": candidate.geometry.to_dict(),
            "anchors": [anchor.to_dict() for anchor in candidate.anchors],
            "evidence": candidate.evidence.to_dict(),
            "provider_name": candidate.provider_name,
            "provider_version": candidate.provider_version,
        },
    )


def _future_evaluation(
    candidate: LineCandidate,
    data: ProviderInput,
    *,
    horizon: str,
    availability_position: int,
    horizon_bars: int,
) -> dict[str, Any]:
    end = availability_position + horizon_bars
    if end > data.row_count:
        return {
            "horizon": horizon,
            "horizon_bars": horizon_bars,
            "evaluation_available": False,
            "future_contact_count": None,
            "future_contact_without_body_violation_count": None,
            "future_body_violation_count": None,
            "has_exact_contact": None,
            "survives_exact_side": None,
            "contact_and_survives_exact_side": None,
            "first_contact_offset_bars": None,
            "first_body_violation_offset_bars": None,
        }
    contacts = clean_contacts = violations = 0
    first_contact: int | None = None
    first_violation: int | None = None
    for offset, position in enumerate(range(availability_position, end)):
        projected = _finite(
            candidate.geometry.value_at(_datetime_from_ns(data.timestamps[position])),
            field_name="future projected line",
        )
        contact = data.low[position] <= projected <= data.high[position]
        floor = min(data.open[position], data.close[position])
        ceiling = max(data.open[position], data.close[position])
        violation = projected > floor if candidate.role.value == "support" else projected < ceiling
        if contact:
            contacts += 1
            if first_contact is None:
                first_contact = offset
        if violation:
            violations += 1
            if first_violation is None:
                first_violation = offset
        if contact and not violation:
            clean_contacts += 1
    return {
        "horizon": horizon,
        "horizon_bars": horizon_bars,
        "evaluation_available": True,
        "future_contact_count": contacts,
        "future_contact_without_body_violation_count": clean_contacts,
        "future_body_violation_count": violations,
        "has_exact_contact": contacts > 0,
        "survives_exact_side": violations == 0,
        "contact_and_survives_exact_side": contacts > 0 and violations == 0,
        "first_contact_offset_bars": first_contact,
        "first_body_violation_offset_bars": first_violation,
    }


def _birth_features(
    candidate: LineCandidate,
    evidence: ConfirmedExtremaPairEvidence,
    data: ProviderInput,
    extrema: Mapping[str, Sequence[ResearchExtremum]],
    *,
    availability_position: int,
) -> dict[str, Any]:
    first, second = evidence.anchor_source_positions
    span_bars = second - first
    span_seconds = (data.timestamps[second] - data.timestamps[first]) / NANOSECONDS
    between = tuple(
        item for item in extrema[candidate.role.value]
        if first < item.source_position < second and item.confirmation_position < availability_position
    )
    clearances: list[float] = []
    for position in range(first + 1, second):
        projected = candidate.geometry.value_at(_datetime_from_ns(data.timestamps[position]))
        floor = min(data.open[position], data.close[position])
        ceiling = max(data.open[position], data.close[position])
        clearance = floor - projected if candidate.role.value == "support" else projected - ceiling
        if clearance < -1e-8:
            raise StudyArtifactError("provider candidate has negative body clearance")
        clearances.append(_bps(max(0.0, clearance), projected, field_name="body clearance"))
    prominence: list[float] = []
    for position, anchor in zip(evidence.anchor_source_positions, candidate.anchors):
        if position - 1 < 0 or position + 1 >= availability_position:
            raise StudyArtifactError("anchor prominence reads beyond candidate availability")
        if candidate.role.value == "support":
            raw = min(data.low[position - 1], data.low[position + 1]) - anchor.price
        else:
            raw = anchor.price - max(data.high[position - 1], data.high[position + 1])
        prominence.append(_bps(raw, anchor.price, field_name="anchor prominence"))
    candidate_available_at = _datetime_from_ns(data.timestamps[max(evidence.confirmation_positions)]) + timedelta(
        seconds=INTERVAL_SECONDS[data.timeframe]
    )
    if candidate_available_at > data.confirmed_through:
        raise StudyArtifactError("candidate availability is after confirmed boundary")
    slope = _bps(
        candidate.anchors[1].price - candidate.anchors[0].price,
        candidate.anchors[0].price,
        field_name="slope",
    ) / (span_seconds / DAY_SECONDS)
    return {
        "anchor_span_bars": span_bars,
        "anchor_span_seconds": span_seconds,
        "anchor_price_change_bps": _bps(
            candidate.anchors[1].price - candidate.anchors[0].price,
            candidate.anchors[0].price,
            field_name="anchor price change",
        ),
        "slope_bps_per_day": slope,
        "absolute_slope_bps_per_day": abs(slope),
        "same_role_confirmed_extrema_between_anchors": len(between),
        "same_role_extrema_skip_count": len(between),
        "minimum_body_clearance_bps": min(clearances) if clearances else 0.0,
        "median_body_clearance_bps": statistics.median(clearances) if clearances else 0.0,
        "maximum_body_clearance_bps": max(clearances) if clearances else 0.0,
        "first_anchor_prominence_bps": prominence[0],
        "second_anchor_prominence_bps": prominence[1],
        "minimum_anchor_prominence_bps": min(prominence),
        "mean_anchor_prominence_bps": statistics.mean(prominence),
        "candidate_available_at": _iso(candidate_available_at),
        "chronological_segment": "early" if candidate_available_at < MIDPOINT else "late",
    }


def _candidate_record(
    candidate: LineCandidate,
    evidence: ConfirmedExtremaPairEvidence,
    data: ProviderInput,
    extrema: Mapping[str, Sequence[ResearchExtremum]],
) -> dict[str, Any]:
    if evidence.candidate_id != candidate.candidate_id:
        raise StudyArtifactError("candidate/evidence IDs are not one-to-one")
    positions = tuple(evidence.anchor_source_positions)
    confirmations = tuple(evidence.confirmation_positions)
    all_positions = (*positions, *confirmations)
    if any(position < 0 or position >= data.row_count for position in all_positions):
        raise StudyArtifactError("candidate evidence position is outside source")
    if positions[1] <= positions[0] or confirmations[1] <= confirmations[0]:
        raise StudyArtifactError("candidate anchor positions are not ordered")
    availability = max(confirmations) + 1
    if availability > data.row_count:
        raise StudyArtifactError("candidate availability position is outside source")
    if any(position >= availability for position in confirmations):
        raise StudyArtifactError("candidate confirmation is not complete before availability")
    if candidate.observed_at != data.observed_at:
        raise StudyArtifactError("candidate observed_at mismatch")
    if evidence.validated_intermediate_count != positions[1] - positions[0] - 1:
        raise StudyArtifactError("candidate intermediate count mismatch")
    if candidate.anchors[0].pivot_time != _datetime_from_ns(data.timestamps[positions[0]]) or candidate.anchors[1].pivot_time != _datetime_from_ns(data.timestamps[positions[1]]):
        raise StudyArtifactError("candidate anchor timestamp mismatch")
    birth = _birth_features(candidate, evidence, data, extrema, availability_position=availability)
    evaluations = {
        horizon: _future_evaluation(
            candidate,
            data,
            horizon=horizon,
            availability_position=availability,
            horizon_bars=HORIZON_BARS_BY_TIMEFRAME[data.timeframe][horizon],
        )
        for horizon in HORIZON_NAMES
    }
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_structure_id": _structure_id(candidate),
        "role": candidate.role.value,
        "first_anchor_id": candidate.anchors[0].anchor_id,
        "second_anchor_id": candidate.anchors[1].anchor_id,
        "first_anchor_time": _iso(candidate.anchors[0].pivot_time),
        "second_anchor_time": _iso(candidate.anchors[1].pivot_time),
        "anchor_source_positions": list(positions),
        "confirmation_positions": list(confirmations),
        "confirmation_bar_open": _iso(_datetime_from_ns(data.timestamps[max(confirmations)])),
        "availability_position": availability,
        **birth,
        "evaluations": evaluations,
    }


def _record_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record["role"],
        record["second_anchor_time"],
        record["first_anchor_time"],
        record["candidate_structure_id"],
        record["candidate_id"],
    )


def _group_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return record["role"], record["second_anchor_id"]


def _select_one(records: Sequence[Mapping[str, Any]], *, value_field: str | None, reverse: bool) -> tuple[dict[str, Any], ...]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[_group_key(record)].append(record)
    selected: list[dict[str, Any]] = []
    for group in groups.values():
        if value_field is None:
            target = max(item["first_anchor_time"] for item in group) if reverse else min(item["first_anchor_time"] for item in group)
            ordered = sorted(
                (item for item in group if item["first_anchor_time"] == target),
                key=lambda item: (item["candidate_structure_id"], item["candidate_id"]),
            )
        else:
            ordered = sorted(
                group,
                key=lambda item: (
                    -_finite(item[value_field], field_name=value_field) if reverse else _finite(item[value_field], field_name=value_field),
                    item["candidate_structure_id"],
                    item["candidate_id"],
                ),
            )
        selected.append(dict(ordered[0]))
    return tuple(sorted(selected, key=_record_sort_key))


def select_families(records: Sequence[Mapping[str, Any]]) -> dict[str, tuple[dict[str, Any], ...]]:
    ordered = tuple(sorted((dict(record) for record in records), key=_record_sort_key))
    return {
        FAMILY_IDS[0]: ordered,
        FAMILY_IDS[1]: tuple(item for item in ordered if item["same_role_extrema_skip_count"] == 0),
        FAMILY_IDS[2]: tuple(item for item in ordered if item["same_role_extrema_skip_count"] <= 1),
        FAMILY_IDS[3]: tuple(item for item in ordered if item["same_role_extrema_skip_count"] <= 3),
        FAMILY_IDS[4]: _select_one(ordered, value_field=None, reverse=True),
        FAMILY_IDS[5]: _select_one(ordered, value_field=None, reverse=False),
        FAMILY_IDS[6]: _select_one(ordered, value_field="minimum_body_clearance_bps", reverse=True),
        FAMILY_IDS[7]: _select_one(ordered, value_field="minimum_anchor_prominence_bps", reverse=True),
    }


def _mutate_future_labels(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Change only persisted future outcomes for a selector invariance probe."""

    mutated: list[dict[str, Any]] = []
    for record in records:
        changed = dict(record)
        evaluations: dict[str, dict[str, Any]] = {}
        for horizon in HORIZON_NAMES:
            evaluation = dict(record["evaluations"][horizon])
            evaluation["future_contact_count"] = 999_999
            evaluation["future_contact_without_body_violation_count"] = 999_999
            evaluation["future_body_violation_count"] = 999_999
            evaluation["has_exact_contact"] = True
            evaluation["survives_exact_side"] = False
            evaluation["contact_and_survives_exact_side"] = False
            evaluation["first_contact_offset_bars"] = 999_999
            evaluation["first_body_violation_offset_bars"] = 0
            evaluations[horizon] = evaluation
        changed["evaluations"] = evaluations
        mutated.append(changed)
    return tuple(mutated)


def _family_id_sequences(
    families: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, tuple[str, ...]]:
    return {
        family_id: tuple(item["candidate_id"] for item in families[family_id])
        for family_id in FAMILY_IDS
    }


def _membership_stability(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, tuple[dict[str, Any], ...]], dict[str, dict[str, Any]]]:
    baseline = select_families(records)
    reversed_families = select_families(tuple(reversed(records)))
    mutated_families = select_families(_mutate_future_labels(records))
    baseline_ids = _family_id_sequences(baseline)
    reversed_ids = _family_id_sequences(reversed_families)
    mutated_ids = _family_id_sequences(mutated_families)
    evidence: dict[str, dict[str, Any]] = {}
    for family_id in FAMILY_IDS:
        current = baseline_ids[family_id]
        reversed_membership = reversed_ids[family_id]
        mutated_membership = mutated_ids[family_id]
        evidence[family_id] = {
            "candidate_count": len(current),
            "reversed_candidate_count": len(reversed_membership),
            "future_label_mutated_candidate_count": len(mutated_membership),
            "input_order_independent_membership": current == reversed_membership,
            "future_label_mutation_membership_invariant": current == mutated_membership,
            "input_order_mismatch_candidate_ids": sorted(set(current) ^ set(reversed_membership)),
            "future_label_mutation_mismatch_candidate_ids": sorted(set(current) ^ set(mutated_membership)),
        }
    return baseline, evidence


def _verify_family_invariants(families: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    if tuple(families) != FAMILY_IDS:
        raise StudyArtifactError("family definition set drifted")
    control_ids = {item["candidate_id"] for item in families[FAMILY_IDS[0]]}
    if len(control_ids) != len(families[FAMILY_IDS[0]]):
        raise StudyArtifactError("control contains duplicate candidates")
    for family_id, records in families.items():
        ids = [item["candidate_id"] for item in records]
        if len(ids) != len(set(ids)) or not set(ids).issubset(control_ids):
            raise StudyArtifactError(f"invalid family membership: {family_id}")
    if not (
        {item["candidate_id"] for item in families[FAMILY_IDS[1]]}
        <= {item["candidate_id"] for item in families[FAMILY_IDS[2]]}
        <= {item["candidate_id"] for item in families[FAMILY_IDS[3]]}
        <= control_ids
    ):
        raise StudyArtifactError("skip-family containment failed")
    for family_id in FAMILY_IDS[4:]:
        counts = Counter(_group_key(item) for item in families[family_id])
        control_groups = {_group_key(item) for item in families[FAMILY_IDS[0]]}
        if set(counts) != control_groups or any(value != 1 for value in counts.values()):
            raise StudyArtifactError(f"one-per-second-anchor invariant failed: {family_id}")


def _metric_summary(records: Sequence[Mapping[str, Any]], horizon: str) -> dict[str, Any]:
    eligible = [item for item in records if item["evaluations"][horizon]["evaluation_available"]]
    if not eligible:
        return {
            "evaluation_available_count": 0,
            "contact_rate": None,
            "exact_side_survival_rate": None,
            "contact_and_survival_rate": None,
            "median_future_contact_count": None,
            "median_future_body_violation_count": None,
        }
    evaluations = [item["evaluations"][horizon] for item in eligible]
    return {
        "evaluation_available_count": len(eligible),
        "contact_rate": statistics.mean(item["has_exact_contact"] for item in evaluations),
        "exact_side_survival_rate": statistics.mean(item["survives_exact_side"] for item in evaluations),
        "contact_and_survival_rate": statistics.mean(item["contact_and_survives_exact_side"] for item in evaluations),
        "median_future_contact_count": statistics.median(item["future_contact_count"] for item in evaluations),
        "median_future_body_violation_count": statistics.median(item["future_body_violation_count"] for item in evaluations),
    }


def _group_metric(records: Sequence[Mapping[str, Any]], horizon: str) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[_group_key(record)].append(record)
    group_values: list[dict[str, Any]] = []
    for group in groups.values():
        metric = _metric_summary(group, horizon)
        if metric["evaluation_available_count"] == 0:
            continue
        eligible = [item for item in group if item["evaluations"][horizon]["evaluation_available"]]
        evaluations = [item["evaluations"][horizon] for item in eligible]
        group_values.append(
            {
                "metric": metric,
                "mean_future_contact_count": statistics.mean(item["future_contact_count"] for item in evaluations),
                "mean_future_body_violation_count": statistics.mean(item["future_body_violation_count"] for item in evaluations),
            }
        )
    if not group_values:
        return {
            "evaluation_available_count": 0,
            "weighted_group_count": 0,
            "contact_rate": None,
            "exact_side_survival_rate": None,
            "contact_and_survival_rate": None,
            "mean_of_group_mean_future_contact_count": None,
            "mean_of_group_mean_future_body_violation_count": None,
        }
    return {
        "evaluation_available_count": sum(item["metric"]["evaluation_available_count"] for item in group_values),
        "weighted_group_count": len(group_values),
        "contact_rate": statistics.mean(item["metric"]["contact_rate"] for item in group_values),
        "exact_side_survival_rate": statistics.mean(item["metric"]["exact_side_survival_rate"] for item in group_values),
        "contact_and_survival_rate": statistics.mean(item["metric"]["contact_and_survival_rate"] for item in group_values),
        "mean_of_group_mean_future_contact_count": statistics.mean(item["mean_future_contact_count"] for item in group_values),
        "mean_of_group_mean_future_body_violation_count": statistics.mean(item["mean_future_body_violation_count"] for item in group_values),
    }


def _delta(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _outcomes(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon, _ in HORIZONS:
        role_segment: dict[str, Any] = {}
        for role in ROLES:
            for segment in SEGMENTS:
                cohort = [item for item in records if item["role"] == role and item["chronological_segment"] == segment]
                role_segment[f"{role}/{segment}"] = {
                    "candidate_count": len(cohort),
                    "unique_second_anchor_group_count": len({_group_key(item) for item in cohort}),
                    "candidate_weighted_descriptive": _metric_summary(cohort, horizon),
                    "second_anchor_group_weighted_descriptive": _group_metric(cohort, horizon),
                }
        result[horizon] = {
            "candidate_weighted_descriptive": _metric_summary(records, horizon),
            "second_anchor_group_weighted_descriptive": _group_metric(records, horizon),
            "role_segment": role_segment,
            "late_minus_early": {
                role: {
                    weighting: {
                        field: _delta(
                            role_segment[f"{role}/late"][weighting].get(field),
                            role_segment[f"{role}/early"][weighting].get(field),
                        )
                        for field in (
                            "contact_rate",
                            "exact_side_survival_rate",
                            "contact_and_survival_rate",
                        )
                    }
                    for weighting in ("candidate_weighted_descriptive", "second_anchor_group_weighted_descriptive")
                }
                for role in ROLES
            },
        }
    return result


def _finite_overlap(records: Sequence[Mapping[str, Any]], row_count: int) -> dict[str, Any]:
    counts = [
        sum(first <= position <= second for item in records for first, second in (item["anchor_source_positions"],))
        for position in range(row_count)
    ]
    return {
        "definition": "finite_anchor_to_anchor_overlap; inclusive source-position intervals",
        "row_count": row_count,
        "counts": _stats(counts),
    }


def _family_metrics(
    records: Sequence[Mapping[str, Any]],
    *,
    control_group_count: int,
    control_count: int,
    row_count: int,
) -> dict[str, Any]:
    groups = {_group_key(item) for item in records}
    group_counts = Counter(_group_key(item) for item in records)
    admissions = Counter(item["candidate_available_at"] for item in records)
    return {
        "candidate_count": len(records),
        "candidate_fraction_of_control": len(records) / control_count if control_count else None,
        "support_count": sum(item["role"] == "support" for item in records),
        "resistance_count": sum(item["role"] == "resistance" for item in records),
        "early_count": sum(item["chronological_segment"] == "early" for item in records),
        "late_count": sum(item["chronological_segment"] == "late" for item in records),
        "unique_anchor_count": len({anchor for item in records for anchor in (item["first_anchor_id"], item["second_anchor_id"])}),
        "unique_second_anchor_group_count": len(groups),
        "second_anchor_group_coverage_ratio": len(groups) / control_group_count if control_group_count else None,
        "candidate_count_per_second_anchor": {
            "nonempty_group_count": len(group_counts),
            "distribution": _stats(list(group_counts.values())),
        },
        "admission_burst": {
            "availability_bar_count": len(admissions),
            "admissions_per_availability_bar": _stats(list(admissions.values())),
        },
        "finite_anchor_to_anchor_overlap": _finite_overlap(records, row_count),
        "outcomes": _outcomes(records),
    }


def _support_status(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_horizon: dict[str, Any] = {}
    enough = True
    for horizon, _ in HORIZONS:
        evaluated_groups = {
            _group_key(item)
            for item in records
            if item["evaluations"][horizon]["evaluation_available"]
        }
        cells = {
            f"{role}/{segment}": len({
                _group_key(item)
                for item in records
                if item["role"] == role and item["chronological_segment"] == segment
                and item["evaluations"][horizon]["evaluation_available"]
            })
            for role in ROLES for segment in SEGMENTS
        }
        horizon_enough = len(evaluated_groups) >= VALIDATION_GATES["minimum_evaluated_second_anchor_groups"] and all(
            count >= VALIDATION_GATES["minimum_evaluated_groups_per_role_segment"] for count in cells.values()
        )
        enough = enough and horizon_enough
        by_horizon[horizon] = {
            "evaluated_second_anchor_group_count": len(evaluated_groups),
            "evaluated_groups_per_role_segment": cells,
            "sufficient_for_ranking": horizon_enough,
        }
    return {"by_horizon": by_horizon, "sufficient_for_ranking": enough}


def _architecture_classification(
    family_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    control_ids: set[str],
    repeat_matches: bool,
    future_label_matches: bool,
) -> str:
    ids = {item["candidate_id"] for item in records}
    if not ids.issubset(control_ids):
        return "INVALID_MEMBERSHIP_CONTRACT"
    if not repeat_matches:
        return "INVALID_NONDETERMINISTIC_SELECTOR"
    if not future_label_matches:
        return "INVALID_NONCAUSAL_SELECTOR"
    if not records or {item["role"] for item in records} != set(ROLES) or {item["chronological_segment"] for item in records} != set(SEGMENTS):
        return "INVALID_ROLE_OR_SEGMENT_COVERAGE"
    if family_id in FAMILY_IDS[4:] and len({_group_key(item) for item in records}) != len(records):
        return "INVALID_MEMBERSHIP_CONTRACT"
    if not _support_status(records)["sufficient_for_ranking"]:
        return "INCONCLUSIVE_EVALUATION_SUPPORT"
    return "ARCHITECTURALLY_VALID"


def _comparison_metrics(family: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon, _ in HORIZONS:
        family_group = family["outcomes"][horizon]["second_anchor_group_weighted_descriptive"]
        control_group = control["outcomes"][horizon]["second_anchor_group_weighted_descriptive"]
        result[horizon] = {
            "survival_delta": _delta(family_group["exact_side_survival_rate"], control_group["exact_side_survival_rate"]),
            "contact_and_survival_delta": _delta(family_group["contact_and_survival_rate"], control_group["contact_and_survival_rate"]),
            "contact_delta": _delta(family_group["contact_rate"], control_group["contact_rate"]),
        }
    return result


def _validation_gate(
    family_id: str,
    by_dataset: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    if family_id == FAMILY_IDS[0]:
        reasons.append("control_is_not_a_density_reduction_family")
    for dataset_id in VALIDATION_DATASETS:
        metrics = by_dataset[dataset_id]
        if metrics["architecture_classification"] != "ARCHITECTURALLY_VALID":
            reasons.append(f"{dataset_id}:architecture={metrics['architecture_classification']}")
        if metrics["second_anchor_group_coverage_ratio"] is None or metrics["second_anchor_group_coverage_ratio"] < VALIDATION_GATES["minimum_second_anchor_coverage_ratio"]:
            reasons.append(f"{dataset_id}:coverage_below_minimum")
        if metrics["candidate_fraction_of_control"] is None or metrics["candidate_fraction_of_control"] > VALIDATION_GATES["maximum_candidate_fraction_of_control"]:
            reasons.append(f"{dataset_id}:candidate_fraction_above_maximum")
        control = by_dataset[dataset_id]["control_metrics"]
        overlap = metrics["finite_anchor_to_anchor_overlap"]["counts"]["p95"]
        control_overlap = control["finite_anchor_to_anchor_overlap"]["counts"]["p95"]
        ratio = overlap / control_overlap if overlap is not None and control_overlap not in (None, 0) else None
        if ratio is None or ratio > VALIDATION_GATES["maximum_finite_overlap_p95_ratio_vs_control"]:
            reasons.append(f"{dataset_id}:finite_overlap_p95_ratio_above_maximum")
        admissions = metrics["admission_burst"]["admissions_per_availability_bar"]["p95"]
        if admissions is None or admissions > VALIDATION_GATES["maximum_admissions_p95"]:
            reasons.append(f"{dataset_id}:admissions_p95_above_maximum")
        if not metrics["evaluation_support"]["sufficient_for_ranking"]:
            reasons.append(f"{dataset_id}:evaluation_support_insufficient")
    comparison_by_horizon: dict[str, list[float]] = defaultdict(list)
    contact_survival_by_horizon: dict[str, list[float]] = defaultdict(list)
    bad_survival = bad_contact_survival = 0
    for dataset_id in VALIDATION_DATASETS:
        for horizon, _ in HORIZONS:
            delta = by_dataset[dataset_id]["comparison_to_control"][horizon]
            if delta["survival_delta"] is None or delta["contact_and_survival_delta"] is None:
                reasons.append(f"{dataset_id}/{horizon}:outcome_delta_undefined")
                continue
            comparison_by_horizon[horizon].append(delta["survival_delta"])
            contact_survival_by_horizon[horizon].append(delta["contact_and_survival_delta"])
            bad_survival += delta["survival_delta"] < -0.20
            bad_contact_survival += delta["contact_and_survival_delta"] < -0.10
    horizon_medians = {
        horizon: {
            "survival_delta_median": statistics.median(comparison_by_horizon[horizon]) if comparison_by_horizon[horizon] else None,
            "contact_and_survival_delta_median": statistics.median(contact_survival_by_horizon[horizon]) if contact_survival_by_horizon[horizon] else None,
        }
        for horizon, _ in HORIZONS
    }
    for horizon, values in horizon_medians.items():
        if values["survival_delta_median"] is None or values["survival_delta_median"] < VALIDATION_GATES["minimum_group_survival_delta_median"]:
            reasons.append(f"{horizon}:survival_delta_median_below_minimum")
        if values["contact_and_survival_delta_median"] is None or values["contact_and_survival_delta_median"] < VALIDATION_GATES["minimum_group_contact_and_survival_delta_median"]:
            reasons.append(f"{horizon}:contact_and_survival_delta_median_below_minimum")
    if bad_survival > VALIDATION_GATES["maximum_survival_delta_below_minus_020"]:
        reasons.append("too_many_survival_deltas_below_minus_020")
    if bad_contact_survival > VALIDATION_GATES["maximum_contact_and_survival_delta_below_minus_010"]:
        reasons.append("too_many_contact_and_survival_deltas_below_minus_010")
    return {
        "eligible": not reasons,
        "rejection_reasons": reasons,
        "outcome_gate_summary": {
            "by_horizon": horizon_medians,
            "survival_deltas_below_minus_020": bad_survival,
            "contact_and_survival_deltas_below_minus_010": bad_contact_survival,
        },
    }


def _ranking_key(family_id: str, by_dataset: Mapping[str, Mapping[str, Any]]) -> tuple[Any, ...]:
    coverages = [by_dataset[dataset]["second_anchor_group_coverage_ratio"] for dataset in VALIDATION_DATASETS]
    overlap_ratios = []
    admissions = []
    fractions = []
    contact_survival: list[float] = []
    survival: list[float] = []
    for dataset in VALIDATION_DATASETS:
        metrics = by_dataset[dataset]
        control = metrics["control_metrics"]
        overlap = metrics["finite_anchor_to_anchor_overlap"]["counts"]["p95"]
        control_overlap = control["finite_anchor_to_anchor_overlap"]["counts"]["p95"]
        overlap_ratios.append(overlap / control_overlap if control_overlap else float("inf"))
        admissions.append(metrics["admission_burst"]["admissions_per_availability_bar"]["p95"] or float("inf"))
        fractions.append(metrics["candidate_fraction_of_control"] or float("inf"))
        for horizon, _ in HORIZONS:
            delta = metrics["comparison_to_control"][horizon]
            if delta["contact_and_survival_delta"] is not None:
                contact_survival.append(delta["contact_and_survival_delta"])
            if delta["survival_delta"] is not None:
                survival.append(delta["survival_delta"])
    return (
        -min(coverages),
        max(overlap_ratios),
        max(admissions),
        max(fractions),
        -statistics.median(contact_survival),
        -statistics.median(survival),
        family_id,
    )


def _membership_payload(families: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": "trendline_v2_phase_9c2_family_membership_v1",
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "families": {
            family_id: [
                {
                    "candidate_id": record["candidate_id"],
                    "candidate_structure_id": record["candidate_structure_id"],
                    "role": record["role"],
                    "first_anchor_id": record["first_anchor_id"],
                    "second_anchor_id": record["second_anchor_id"],
                    "candidate_available_at": record["candidate_available_at"],
                }
                for record in records
            ]
            for family_id, records in families.items()
        },
    }


def _summary_rows(dataset_id: str, families: Mapping[str, Sequence[Mapping[str, Any]]], metrics: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for family_id in FAMILY_IDS:
        family_records = families[family_id]
        for role in ROLES:
            for segment in SEGMENTS:
                cohort = [item for item in family_records if item["role"] == role and item["chronological_segment"] == segment]
                for horizon, _ in HORIZONS:
                    candidate_metric = _metric_summary(cohort, horizon)
                    group_metric = _group_metric(cohort, horizon)
                    rows.append({
                        "dataset_id": dataset_id,
                        "family_id": family_id,
                        "role": role,
                        "chronological_segment": segment,
                        "horizon": horizon,
                        "candidate_count": len(cohort),
                        "unique_second_anchor_group_count": len({_group_key(item) for item in cohort}),
                        "candidate_evaluation_available_count": candidate_metric["evaluation_available_count"],
                        "candidate_contact_rate": candidate_metric["contact_rate"],
                        "candidate_exact_side_survival_rate": candidate_metric["exact_side_survival_rate"],
                        "candidate_contact_and_survival_rate": candidate_metric["contact_and_survival_rate"],
                        "group_evaluation_available_count": group_metric["evaluation_available_count"],
                        "group_weighted_group_count": group_metric["weighted_group_count"],
                        "group_contact_rate": group_metric["contact_rate"],
                        "group_exact_side_survival_rate": group_metric["exact_side_survival_rate"],
                        "group_contact_and_survival_rate": group_metric["contact_and_survival_rate"],
                    })
    return tuple(rows)


def _study_contract(config: ResolvedTrendlineV2Config, provider_config: ConfirmedExtremaPairConfig) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_contract",
        "source": {
            "phase9c1_commit": SOURCE_COMMIT,
            "cohort_contract_id": COHORT_CONTRACT_ID,
            "cohort_source_identity": COHORT_SOURCE_IDENTITY,
            "source_decision_id": SOURCE_DECISION_ID,
            "source_manifest_id": SOURCE_MANIFEST_ID,
            "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        },
        "provider": {
            "name": provider_config.provider_name,
            "version": provider_config.provider_version,
            "foundation_config_identity": config.semantic_hash,
            "provider_config_identity": provider_config.semantic_hash,
            "combined_config_identity": deterministic_hash(
                "trendline_v2_combined_configuration",
                {"foundation_config_identity": config.semantic_hash, "provider_config_identity": provider_config.semantic_hash},
            ),
            "provider_contract_identity": provider_config.provider_contract_identity,
            "configuration": dict(FIXED_PROVIDER_VALUES),
            "classification": ["SMOKE_ONLY", "UNRESOLVED", "NOT_PROMOTED", "NOT_CANONICAL"],
        },
        "selector": {
            "selector_contract_id": SELECTOR_CONTRACT_ID,
            "families": list(FAMILY_DEFINITIONS),
            "grouping_key": ["role", "second_anchor_id"],
            "allowed_fields": list(SELECTOR_FIELDS),
            "forbidden_fields": list(FORBIDDEN_SELECTOR_FIELDS),
        },
        "horizons": [
            {
                "horizon": name,
                "bars_by_timeframe": dict(
                    (timeframe, HORIZON_BARS_BY_TIMEFRAME[timeframe][name])
                    for timeframe in INTERVAL_SECONDS
                ),
            }
            for name in HORIZON_NAMES
        ],
        "midpoint": _iso(MIDPOINT),
        "future_label_policy": {
            "contact": "low <= projected_line <= high",
            "support_body_violation": "projected_line > min(open, close)",
            "resistance_body_violation": "projected_line < max(open, close)",
            "forbidden": ["ATR", "bands", "bounce", "breakout", "breakdown", "retest", "role_reversal", "PnL", "trading_signal"],
        },
        "validation_gates": VALIDATION_GATES,
        "execution": {"network_request_count": 0, "retry_count": 0, "fallback_count": 0, "configuration_variants": 0},
    }


def _execute_provider(dataset: DatasetContext, config: ResolvedTrendlineV2Config, provider_config: ConfirmedExtremaPairConfig, provider: ProviderCall) -> ProviderResult:
    result = provider(_frame_for(dataset), config=config, provider_config=provider_config)
    if not isinstance(result, ProviderResult):
        raise ProviderScopeBlocked(f"provider returned invalid result: {dataset.dataset_id}")
    if result.status is not ProviderStatus.SUCCESS or result.reason is not None:
        raise ProviderScopeBlocked(f"BLOCKED_PROVIDER_SCOPE: {dataset.dataset_id} status={result.status.value} reason={getattr(result.reason, 'value', result.reason)}")
    if not result.candidates or len(result.candidates) > FIXED_PROVIDER_VALUES["max_output_candidates"]:
        raise ProviderScopeBlocked(f"BLOCKED_PROVIDER_SCOPE: invalid candidate count {dataset.dataset_id}")
    if result.request.input_identity != dataset.input_data.input_identity or result.request.asset != dataset.asset or result.request.timeframe != dataset.timeframe:
        raise ProviderScopeBlocked(f"BLOCKED_PROVIDER_SCOPE: provider request binding mismatch {dataset.dataset_id}")
    if result.request.config.semantic_hash != config.semantic_hash or result.request.provider_config.semantic_hash != provider_config.semantic_hash:
        raise ProviderScopeBlocked(f"BLOCKED_PROVIDER_SCOPE: provider configuration mismatch {dataset.dataset_id}")
    if len(result.evidence) != len(result.candidates):
        raise ProviderScopeBlocked(f"BLOCKED_PROVIDER_SCOPE: evidence mismatch {dataset.dataset_id}")
    return result


def _execution_rows(
    context: CohortContext,
    results: Mapping[str, ProviderResult],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "execution_order": dataset.request_order,
            "dataset_id": dataset.dataset_id,
            "input_identity": dataset.input_data.input_identity,
            "request_identity": results[dataset.dataset_id].request.request_identity,
            "status": results[dataset.dataset_id].status.value,
            "reason": None,
            "candidate_count": len(results[dataset.dataset_id].candidates),
            "provider_execution_count": 1,
            "network_request_count": 0,
        }
        for dataset in context.datasets
    )


def _provider_artifact(dataset: DatasetContext, result: ProviderResult, config: ResolvedTrendlineV2Config, provider_config: ConfirmedExtremaPairConfig) -> dict[str, Any]:
    combined = result.request.config_identity
    return {
        "schema_version": f"{STUDY_SCHEMA}_provider_result",
        "dataset_id": dataset.dataset_id,
        "input_identity": dataset.input_data.input_identity,
        "dataset_source_identity": dataset.dataset_source_identity,
        "foundation_config_identity": config.semantic_hash,
        "provider_config_identity": provider_config.semantic_hash,
        "combined_config_identity": combined,
        "provider_contract_identity": provider_config.provider_contract_identity,
        "request_identity": result.request.request_identity,
        "provider_execution_count": 1,
        "network_request_count": 0,
        "provider_result_id": _provider_result_id(result),
        "snapshot_id": result.to_snapshot().snapshot_id,
        "candidate_count": len(result.candidates),
        "support_count": sum(candidate.role.value == "support" for candidate in result.candidates),
        "resistance_count": sum(candidate.role.value == "resistance" for candidate in result.candidates),
        "provider_result": result.to_dict(),
    }


def _load_persisted_provider_result(
    root: Path,
    dataset: DatasetContext,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
) -> ProviderResult:
    artifact = _load_json(root / "datasets" / dataset.dataset_id / "provider_result.json")
    try:
        result = _typed_result(artifact["provider_result"])
    except (KeyError, TypeError) as exc:
        raise StudyArtifactError(f"provider artifact is malformed: {dataset.dataset_id}") from exc
    if (
        result.request.input_identity != dataset.input_data.input_identity
        or result.request.asset != dataset.asset
        or result.request.timeframe != dataset.timeframe
        or result.request.config.semantic_hash != config.semantic_hash
        or result.request.provider_config.semantic_hash != provider_config.semantic_hash
        or len(result.candidates) != len(result.evidence)
        or not result.candidates
        or len(result.candidates) > FIXED_PROVIDER_VALUES["max_output_candidates"]
    ):
        raise StudyArtifactError(f"provider result binding mismatch: {dataset.dataset_id}")
    expected = _provider_artifact(dataset, result, config, provider_config)
    if canonical_json(artifact) != canonical_json(expected):
        raise StudyArtifactError(f"provider artifact semantic mismatch: {dataset.dataset_id}")
    if result.status is not ProviderStatus.SUCCESS or result.reason is not None:
        raise StudyArtifactError(f"persisted provider result is not successful: {dataset.dataset_id}")
    return result


def _validate_superseded_bundle(root: Path) -> tuple[dict[str, Any], ...]:
    inventory = _inventory(root)
    if len(inventory) != 38 or _inventory_sha256(inventory) != SUPERSEDED_INVENTORY_SHA256:
        raise StudyArtifactError("superseded Phase 9C.2 inventory mismatch")
    manifest = _validate_manifest(root)
    if manifest["manifest_id"] != SUPERSEDED_MANIFEST_ID:
        raise StudyArtifactError("superseded manifest identity mismatch")
    decision = _load_json(root / "decision.json")
    if decision.get("decision_id") != SUPERSEDED_DECISION_ID:
        raise StudyArtifactError("superseded decision identity mismatch")
    lock = _load_json(root / "validation_lock.json")
    if lock.get("validation_lock_id") != SUPERSEDED_VALIDATION_LOCK_ID:
        raise StudyArtifactError("superseded validation lock identity mismatch")
    return inventory


def regenerate_offline(
    *,
    superseded_root: str | Path = SUPERSEDED_ROOT,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Rebuild derived study evidence from persisted provider results only."""

    superseded_root = Path(superseded_root)
    source_root = Path(source_root)
    output_root = Path(output_root)
    superseded_inventory = _validate_superseded_bundle(superseded_root)
    context = _load_cohort(source_root)
    config = _foundation_config()
    provider_config = _provider_config()
    results = {
        dataset.dataset_id: _load_persisted_provider_result(
            superseded_root,
            dataset,
            config,
            provider_config,
        )
        for dataset in context.datasets
    }
    if tuple(results) != tuple(
        item[0].lower() + "_" + item[1] for item in DATASET_ORDER
    ):
        raise StudyArtifactError("offline provider-result order mismatch")
    return run_study(
        source_root=source_root,
        output_root=output_root,
        _cohort_context=context,
        _provider_results=results,
        _remediation_source_bundle_inventory_sha256=_inventory_sha256(superseded_inventory),
    )


def _dataset_metrics(
    dataset: DatasetContext,
    families: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    control = families[FAMILY_IDS[0]]
    control_group_count = len({_group_key(item) for item in control})
    control_count = len(control)
    base: dict[str, Any] = {}
    for family_id in FAMILY_IDS:
        metrics = _family_metrics(families[family_id], control_group_count=control_group_count, control_count=control_count, row_count=dataset.input_data.row_count)
        base[family_id] = metrics
    control_metrics = dict(base[FAMILY_IDS[0]])
    for family_id in FAMILY_IDS:
        base[family_id]["control_metrics"] = control_metrics
        base[family_id]["evaluation_support"] = _support_status(families[family_id])
        base[family_id]["comparison_to_control"] = _comparison_metrics(base[family_id], base[FAMILY_IDS[0]])
    control_ids = {item["candidate_id"] for item in control}
    stable_families, stability = _membership_stability(control)
    for family_id in FAMILY_IDS:
        stability_result = stability[family_id]
        current_ids = tuple(item["candidate_id"] for item in families[family_id])
        if current_ids != tuple(item["candidate_id"] for item in stable_families[family_id]):
            raise StudyArtifactError(f"family stability baseline mismatch: {dataset.dataset_id}/{family_id}")
        base[family_id]["membership_stability"] = stability_result
        base[family_id]["architecture_classification"] = _architecture_classification(
            family_id,
            families[family_id],
            control_ids=control_ids,
            repeat_matches=stability_result["input_order_independent_membership"],
            future_label_matches=stability_result["future_label_mutation_membership_invariant"],
        )
    return base


def _derive_dataset_outputs(
    dataset: DatasetContext,
    result: ProviderResult,
) -> tuple[tuple[dict[str, Any], ...], dict[str, tuple[dict[str, Any], ...]], dict[str, Any]]:
    if len(result.candidates) != len(result.evidence):
        raise StudyArtifactError(f"provider candidate/evidence count mismatch: {dataset.dataset_id}")
    extrema = _extrema_by_role(dataset.input_data)
    records = tuple(
        _candidate_record(candidate, evidence, dataset.input_data, extrema)
        for candidate, evidence in zip(result.candidates, result.evidence)
    )
    families = select_families(records)
    _verify_family_invariants(families)
    return records, families, _dataset_metrics(dataset, families)


def _validation_result(all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> dict[str, Any]:
    by_family: dict[str, Any] = {}
    eligible: list[str] = []
    for family_id in FAMILY_IDS:
        dataset_metrics = {
            dataset_id: all_metrics[dataset_id][family_id]
            for dataset_id in VALIDATION_DATASETS
        }
        gate = _validation_gate(family_id, dataset_metrics)
        by_family[family_id] = {"by_dataset": dataset_metrics, "gate": gate}
        if gate["eligible"]:
            eligible.append(family_id)
    ranking = sorted(eligible, key=lambda family_id: _ranking_key(family_id, {dataset: all_metrics[dataset][family_id] for dataset in VALIDATION_DATASETS}))
    return {
        "family_results": by_family,
        "eligible_family_ids": ranking,
        "ordered_validation_ranking": ranking,
        "validation_winner_family_id": ranking[0] if ranking else None,
        "validation_status": "VALIDATION_FINALIST_FROZEN" if ranking else "NO_VALIDATION_FINALIST",
    }


def _holdout_result(
    validation: Mapping[str, Any],
    all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    winner = validation["validation_winner_family_id"]
    if winner is None:
        return {"locked_winner_family_id": None, "winner_results": {}, "passes": False, "status": "NO_VALIDATION_FINALIST"}
    result: dict[str, Any] = {}
    passes = True
    for dataset_id in HOLDOUT_DATASETS:
        metrics = all_metrics[dataset_id][winner]
        reasons: list[str] = []
        if metrics["architecture_classification"] != "ARCHITECTURALLY_VALID":
            reasons.append("architecture_not_valid")
        if not metrics["evaluation_support"]["sufficient_for_ranking"]:
            reasons.append("evaluation_support_insufficient")
        if metrics["second_anchor_group_coverage_ratio"] < 0.90:
            reasons.append("coverage_below_minimum")
        if metrics["candidate_fraction_of_control"] > 0.35:
            reasons.append("candidate_fraction_above_maximum")
        control = all_metrics[dataset_id][FAMILY_IDS[0]]
        ratio = metrics["finite_anchor_to_anchor_overlap"]["counts"]["p95"] / control["finite_anchor_to_anchor_overlap"]["counts"]["p95"]
        if ratio > 0.15:
            reasons.append("finite_overlap_p95_ratio_above_maximum")
        if metrics["admission_burst"]["admissions_per_availability_bar"]["p95"] > 8:
            reasons.append("admissions_p95_above_maximum")
        survival_deltas = [metrics["comparison_to_control"][h]["survival_delta"] for h, _ in HORIZONS]
        contact_deltas = [metrics["comparison_to_control"][h]["contact_and_survival_delta"] for h, _ in HORIZONS]
        if statistics.median(survival_deltas) < -0.10 or statistics.median(contact_deltas) < -0.05:
            reasons.append("median_outcome_delta_below_minimum")
        if any(value < -0.20 for value in survival_deltas) or any(value < -0.10 for value in contact_deltas):
            reasons.append("worst_horizon_outcome_delta_below_minimum")
        passes = passes and not reasons
        result[dataset_id] = {
            "family_id": winner,
            "gate_passed": not reasons,
            "rejection_reasons": reasons,
            "metrics": metrics,
        }
    return {
        "locked_winner_family_id": winner,
        "winner_results": result,
        "passes": passes,
        "status": "FRESH_SCOPE_PROMOTION_CANDIDATE" if passes else "REJECT_HOLDOUT_GATE",
    }


def _source_audit(context: CohortContext) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_source_audit",
        "phase9c1_commit": SOURCE_COMMIT,
        "cohort_contract_id": context.cohort_contract_id,
        "cohort_source_identity": context.cohort_source_identity,
        "phase9c1_decision_id": context.source_decision_id,
        "phase9c1_manifest_id": context.source_manifest_id,
        "phase9c1_inventory_sha256": context.source_inventory_sha256,
        "pre_run_source_inventory": list(context.source_inventory),
        "post_run_source_inventory": list(context.source_inventory),
        "pre_run_inventory_sha256": context.source_inventory_sha256,
        "post_run_inventory_sha256": context.source_inventory_sha256,
        "source_immutability_verified": True,
    }


def _execution_audit(
    rows: Sequence[Mapping[str, Any]],
    *,
    remediation_source_bundle_inventory_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_provider_execution_audit",
        "executions": list(rows),
        "provider_execution_count": len(rows),
        "historical_provider_execution_count": len(rows),
        "remediation_provider_execution_count": 0,
        "remediation_source_bundle_inventory_sha256": remediation_source_bundle_inventory_sha256,
        "network_request_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "configuration_variant_count": 0,
    }


def _stability_summary(
    all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    execution_rows: Sequence[Mapping[str, Any]],
    *,
    source_immutability_verified: bool,
) -> dict[str, Any]:
    per_dataset: dict[str, Any] = {}
    input_order_invariant = True
    future_label_invariant = True
    for dataset_id in (item[0].lower() + "_" + item[1] for item in DATASET_ORDER):
        per_dataset[dataset_id] = {}
        for family_id in FAMILY_IDS:
            stability = all_metrics[dataset_id][family_id]["membership_stability"]
            per_dataset[dataset_id][family_id] = stability
            input_order_invariant = input_order_invariant and stability["input_order_independent_membership"]
            future_label_invariant = future_label_invariant and stability["future_label_mutation_membership_invariant"]
    return {
        "schema_version": f"{STUDY_SCHEMA}_stability",
        "input_order_independent_membership": input_order_invariant,
        "future_label_mutation_membership_invariant": future_label_invariant,
        "per_dataset_family": per_dataset,
        "provider_execution_count": len(execution_rows),
        "network_request_count": 0,
        "source_immutability_verified": source_immutability_verified,
        "structure_fingerprint_policy": "RESEARCH_ONLY_NOT_MODEL_IDENTITY_NOT_TRACKING_IDENTITY_NOT_RUNTIME_IDENTITY",
    }


def _cross_scope_rows(
    all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for dataset_id in all_metrics:
        for family_id in FAMILY_IDS:
            for horizon, _ in HORIZONS:
                metric = all_metrics[dataset_id][family_id]["outcomes"][horizon][
                    "second_anchor_group_weighted_descriptive"
                ]
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "family_id": family_id,
                        "horizon": horizon,
                        "candidate_count": all_metrics[dataset_id][family_id]["candidate_count"],
                        "candidate_fraction_of_control": all_metrics[dataset_id][family_id]["candidate_fraction_of_control"],
                        "coverage": all_metrics[dataset_id][family_id]["second_anchor_group_coverage_ratio"],
                        "architecture_classification": all_metrics[dataset_id][family_id]["architecture_classification"],
                        "group_count": metric["weighted_group_count"],
                        "group_contact_rate": metric["contact_rate"],
                        "group_exact_side_survival_rate": metric["exact_side_survival_rate"],
                        "group_contact_and_survival_rate": metric["contact_and_survival_rate"],
                    }
                )
    return tuple(rows)


def _lock_payload(
    context: CohortContext,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    without_id = {
        "schema_version": f"{STUDY_SCHEMA}_validation_lock",
        "source": {"cohort_contract_id": context.cohort_contract_id, "cohort_source_identity": context.cohort_source_identity, "source_inventory_sha256": context.source_inventory_sha256},
        "configuration": {"foundation_config_identity": config.semantic_hash, "provider_config_identity": provider_config.semantic_hash, "combined_config_identity": deterministic_hash("trendline_v2_combined_configuration", {"foundation_config_identity": config.semantic_hash, "provider_config_identity": provider_config.semantic_hash}), "provider_contract_identity": provider_config.provider_contract_identity},
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "validation_dataset_ids": list(VALIDATION_DATASETS),
        "validation_metrics": {dataset: all_metrics[dataset] for dataset in VALIDATION_DATASETS},
        "validation_gates": VALIDATION_GATES,
        "eligible_family_ids": validation["eligible_family_ids"],
        "ordered_validation_ranking": validation["ordered_validation_ranking"],
        "validation_winner_family_id": validation["validation_winner_family_id"],
        "validation_status": validation["validation_status"],
    }
    return {**without_id, "validation_lock_id": deterministic_hash(VALIDATION_LOCK_NAMESPACE, without_id)}


def _build_decision(
    context: CohortContext,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    validation: Mapping[str, Any],
    holdout: Mapping[str, Any],
    all_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    lock: Mapping[str, Any],
    execution_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    status = holdout["status"]
    without_id = {
        "schema_version": f"{STUDY_SCHEMA}_decision",
        "study_status": status,
        "source": {"phase9c1_commit": SOURCE_COMMIT, "cohort_contract_id": context.cohort_contract_id, "cohort_source_identity": context.cohort_source_identity, "source_inventory_sha256": context.source_inventory_sha256},
        "configuration": {"foundation_config_identity": config.semantic_hash, "provider_config_identity": provider_config.semantic_hash, "combined_config_identity": lock["configuration"]["combined_config_identity"], "provider_contract_identity": provider_config.provider_contract_identity},
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "validation_lock_id": lock["validation_lock_id"],
        "validation_eligible_families": validation["eligible_family_ids"],
        "validation_ranking": validation["ordered_validation_ranking"],
        "validation_winner_family_id": validation["validation_winner_family_id"],
        "validation_status": validation["validation_status"],
        "holdout_results": holdout,
        "dataset_provider_counts": {row["dataset_id"]: row["candidate_count"] for row in execution_rows},
        "dataset_family_counts": {dataset: {family: all_metrics[dataset][family]["candidate_count"] for family in FAMILY_IDS} for dataset in all_metrics},
        "cross_scope_density_summary": {dataset: {family: {"candidate_count": all_metrics[dataset][family]["candidate_count"], "coverage": all_metrics[dataset][family]["second_anchor_group_coverage_ratio"]} for family in FAMILY_IDS} for dataset in all_metrics},
        "cross_scope_outcome_summary": {dataset: {family: all_metrics[dataset][family]["outcomes"] for family in FAMILY_IDS} for dataset in all_metrics},
        "limitations": [
            "The selected classification concerns one fixed provider configuration and exact-side descriptive continuation evidence. It is not evidence of trading profitability, statistical independence, production readiness, or canonical provider-parameter adequacy.",
            "Candidate rows share anchors and geometry; all candidate-weighted and second-anchor-group-weighted outcomes are descriptive evidence rather than independent-sample inference.",
            "No runtime filter, canonical configuration, provider parameter, tracker, MTF or trading policy was changed or promoted.",
        ],
        "RUNTIME_FILTER_IMPLEMENTATION": "NOT_AUTHORIZED",
        "CANONICAL_CONFIG_PROMOTION": "NOT_AUTHORIZED",
        "PROVIDER_PARAMETER_PROMOTION": "NOT_AUTHORIZED",
        "TRACKER_START": "NOT_AUTHORIZED",
        "MTF": "NOT_AUTHORIZED",
    }
    return {**without_id, "decision_id": deterministic_hash(f"{STUDY_SCHEMA}_decision", without_id)}


def _manifest(root: Path, *, context: CohortContext, validation_lock: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    members = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"):
        members.append({"path": path.relative_to(root).as_posix(), "byte_length": path.stat().st_size, "sha256": _sha256_file(path)})
    without_id = {
        "schema_version": f"{STUDY_SCHEMA}_manifest",
        "study_status": decision["study_status"],
        "cohort_source_identity": context.cohort_source_identity,
        "source_inventory_sha256": context.source_inventory_sha256,
        "validation_lock_id": validation_lock["validation_lock_id"],
        "validation_lock_sha256": _sha256_file(root / "validation_lock.json"),
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": members,
    }
    return {**without_id, "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, without_id)}


def run_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    provider: ProviderCall = discover_trendlines,
    _cohort_context: CohortContext | None = None,
    _provider_results: Mapping[str, ProviderResult] | None = None,
    _remediation_source_bundle_inventory_sha256: str | None = None,
    _before_sui: BeforeSUIHook | None = None,
) -> dict[str, Any]:
    """Execute or assemble the fixed six-dataset study and publish atomically."""

    source_root = Path(source_root)
    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    context = _load_cohort(source_root) if _cohort_context is None else _cohort_context
    source_before = _inventory(source_root)
    source_before_sha = _inventory_sha256(source_before)
    if _cohort_context is None and source_before_sha != SOURCE_INVENTORY_SHA256:
        raise StudyArtifactError("source inventory changed before execution")
    config = _foundation_config()
    provider_config = _provider_config()
    if deterministic_hash("trendline_v2_combined_configuration", {"foundation_config_identity": config.semantic_hash, "provider_config_identity": provider_config.semantic_hash}) != COMBINED_CONFIG_ID:
        raise StudyArtifactError("combined configuration identity drift")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".phase9c2-", dir=output_root.parent))
    execution_rows: list[dict[str, Any]] = []
    all_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    try:
        datasets = {dataset.dataset_id: dataset for dataset in context.datasets}
        results: dict[str, ProviderResult] = {}
        families_by_dataset: dict[str, dict[str, tuple[dict[str, Any], ...]]] = {}
        for dataset_id in VALIDATION_DATASETS:
            dataset = datasets[dataset_id]
            result = (
                _provider_results[dataset_id]
                if _provider_results is not None
                else _execute_provider(dataset, config, provider_config, provider)
            )
            results[dataset_id] = result
            artifact = _provider_artifact(dataset, result, config, provider_config)
            dataset_dir = staging / "datasets" / dataset_id
            dataset_dir.mkdir(parents=True, exist_ok=False)
            _write_json(dataset_dir / "provider_result.json", artifact)
            extrema = _extrema_by_role(dataset.input_data)
            records = tuple(_candidate_record(candidate, evidence, dataset.input_data, extrema) for candidate, evidence in zip(result.candidates, result.evidence))
            families = select_families(records)
            _verify_family_invariants(families)
            families_by_dataset[dataset_id] = families
            _write_json(dataset_dir / "candidate_records.json", {"schema_version": f"{STUDY_SCHEMA}_candidate_records", "dataset_id": dataset_id, "input_identity": dataset.input_data.input_identity, "records": list(records)})
            _write_json(dataset_dir / "family_membership.json", _membership_payload(families))
            metrics = _dataset_metrics(dataset, families)
            all_metrics[dataset_id] = metrics
            _write_json(dataset_dir / "family_metrics.json", {"schema_version": f"{STUDY_SCHEMA}_family_metrics", "dataset_id": dataset_id, "families": metrics})
            _write_csv(dataset_dir / "family_summary.csv", _summary_rows(dataset_id, families, metrics))
            execution_rows.append({"execution_order": dataset.request_order, "dataset_id": dataset_id, "input_identity": dataset.input_data.input_identity, "request_identity": result.request.request_identity, "status": result.status.value, "reason": None, "candidate_count": len(result.candidates), "provider_execution_count": 1, "network_request_count": 0})
            if dataset_id == VALIDATION_DATASETS[-1]:
                if source_before != _inventory(source_root):
                    raise StudyArtifactError("source changed during validation execution")
        validation = _validation_result(all_metrics)
        lock = _lock_payload(context, config, provider_config, all_metrics, validation)
        _write_json(staging / "validation_lock.json", lock)
        lock_sha = _sha256_file(staging / "validation_lock.json")
        if _before_sui is not None:
            _before_sui(staging, lock_sha)
        for dataset_id in HOLDOUT_DATASETS:
            dataset = datasets[dataset_id]
            result = (
                _provider_results[dataset_id]
                if _provider_results is not None
                else _execute_provider(dataset, config, provider_config, provider)
            )
            artifact = _provider_artifact(dataset, result, config, provider_config)
            dataset_dir = staging / "datasets" / dataset_id
            dataset_dir.mkdir(parents=True, exist_ok=False)
            _write_json(dataset_dir / "provider_result.json", artifact)
            extrema = _extrema_by_role(dataset.input_data)
            records = tuple(_candidate_record(candidate, evidence, dataset.input_data, extrema) for candidate, evidence in zip(result.candidates, result.evidence))
            families = select_families(records)
            _verify_family_invariants(families)
            families_by_dataset[dataset_id] = families
            _write_json(dataset_dir / "candidate_records.json", {"schema_version": f"{STUDY_SCHEMA}_candidate_records", "dataset_id": dataset_id, "input_identity": dataset.input_data.input_identity, "records": list(records)})
            _write_json(dataset_dir / "family_membership.json", _membership_payload(families))
            metrics = _dataset_metrics(dataset, families)
            all_metrics[dataset_id] = metrics
            _write_json(dataset_dir / "family_metrics.json", {"schema_version": f"{STUDY_SCHEMA}_family_metrics", "dataset_id": dataset_id, "families": metrics})
            _write_csv(dataset_dir / "family_summary.csv", _summary_rows(dataset_id, families, metrics))
            execution_rows.append({"execution_order": dataset.request_order, "dataset_id": dataset_id, "input_identity": dataset.input_data.input_identity, "request_identity": result.request.request_identity, "status": result.status.value, "reason": None, "candidate_count": len(result.candidates), "provider_execution_count": 1, "network_request_count": 0})
        if _sha256_file(staging / "validation_lock.json") != lock_sha:
            raise StudyArtifactError("validation lock changed after holdout execution")
        source_after = _inventory(source_root)
        if source_after != source_before:
            raise StudyArtifactError("source changed during study")
        all_metrics = {dataset_id: all_metrics[dataset_id] for dataset_id in (item[0].lower() + "_" + item[1] for item in DATASET_ORDER)}
        holdout = _holdout_result(validation, all_metrics)
        _write_json(staging / "study_contract.json", _study_contract(config, provider_config))
        _write_json(staging / "source_audit.json", _source_audit(CohortContext(context.datasets, context.cohort_contract_id, context.cohort_source_identity, source_before, source_before_sha, context.source_decision_id, context.source_manifest_id)))
        _write_json(
            staging / "provider_execution_audit.json",
            _execution_audit(
                execution_rows,
                remediation_source_bundle_inventory_sha256=_remediation_source_bundle_inventory_sha256,
            ),
        )
        _write_csv(staging / "cross_scope_summary.csv", _cross_scope_rows(all_metrics))
        stability = _stability_summary(
            all_metrics,
            execution_rows,
            source_immutability_verified=source_after == source_before,
        )
        _write_json(staging / "stability_summary.json", stability)
        decision = _build_decision(context, config, provider_config, validation, holdout, all_metrics, lock, execution_rows)
        _write_json(staging / "decision.json", decision)
        manifest = _manifest(staging, context=context, validation_lock=lock, decision=decision)
        _write_json(staging / "manifest.json", manifest)
        if len(manifest["members"]) != 37:
            raise StudyArtifactError(f"expected 37 manifest members, got {len(manifest['members'])}")
        if _inventory(source_root) != source_before:
            raise StudyArtifactError("source changed after manifest generation")
        if output_root.exists():
            raise FileExistsError(f"refusing existing output root: {output_root}")
        os.replace(staging, output_root)
        return {"output_root": str(output_root), "manifest_id": manifest["manifest_id"], "decision_id": decision["decision_id"], "validation_lock_id": lock["validation_lock_id"], "validation_lock_sha256": lock_sha, "study_status": decision["study_status"], "execution_audit": execution_rows}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_manifest(root: Path) -> dict[str, Any]:
    manifest = _load_json(root / "manifest.json")
    without_id = dict(manifest)
    manifest_id = without_id.pop("manifest_id", None)
    if manifest_id != deterministic_hash(MANIFEST_NAMESPACE, without_id):
        raise StudyArtifactError("manifest ID mismatch")
    actual = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"):
        actual.append({"path": path.relative_to(root).as_posix(), "byte_length": path.stat().st_size, "sha256": _sha256_file(path)})
    if manifest["members"] != actual or manifest["member_count"] != len(actual) or len(actual) != 37:
        raise StudyArtifactError("manifest members mismatch")
    return manifest


def verify_study_bundle(*, source_root: str | Path = SOURCE_ROOT, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Reconstruct and validate every derived artifact without provider calls."""

    root = Path(output_root)
    manifest = _validate_manifest(root)
    context = _load_cohort(Path(source_root))
    config = _foundation_config()
    provider_config = _provider_config()
    expected_source_audit = _source_audit(context)
    source_audit = _load_json(root / "source_audit.json")
    if source_audit != expected_source_audit:
        raise StudyArtifactError("source audit semantic mismatch")

    results: dict[str, ProviderResult] = {}
    all_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for dataset in context.datasets:
        result = _load_persisted_provider_result(root, dataset, config, provider_config)
        results[dataset.dataset_id] = result
        expected_artifact = _provider_artifact(dataset, result, config, provider_config)
        actual_artifact = _load_json(root / "datasets" / dataset.dataset_id / "provider_result.json")
        if canonical_json(actual_artifact) != canonical_json(expected_artifact):
            raise StudyArtifactError(f"provider artifact semantic mismatch: {dataset.dataset_id}")
        records, families, metrics = _derive_dataset_outputs(dataset, result)
        records_payload = _load_json(root / "datasets" / dataset.dataset_id / "candidate_records.json")
        expected_records_payload = {
            "schema_version": f"{STUDY_SCHEMA}_candidate_records",
            "dataset_id": dataset.dataset_id,
            "input_identity": dataset.input_data.input_identity,
            "records": list(records),
        }
        if records_payload != expected_records_payload:
            raise StudyArtifactError(f"candidate record mismatch: {dataset.dataset_id}")
        membership = _load_json(root / "datasets" / dataset.dataset_id / "family_membership.json")
        if membership != _membership_payload(families):
            raise StudyArtifactError(f"family membership mismatch: {dataset.dataset_id}")
        family_metrics = _load_json(root / "datasets" / dataset.dataset_id / "family_metrics.json")
        expected_family_metrics = {
            "schema_version": f"{STUDY_SCHEMA}_family_metrics",
            "dataset_id": dataset.dataset_id,
            "families": metrics,
        }
        if family_metrics != expected_family_metrics:
            raise StudyArtifactError(f"family metrics mismatch: {dataset.dataset_id}")
        summary = _summary_rows(dataset.dataset_id, families, metrics)
        if (root / "datasets" / dataset.dataset_id / "family_summary.csv").read_bytes() != _csv_bytes(summary):
            raise StudyArtifactError(f"family summary mismatch: {dataset.dataset_id}")
        all_metrics[dataset.dataset_id] = metrics

    ordered_dataset_ids = tuple(item[0].lower() + "_" + item[1] for item in DATASET_ORDER)
    all_metrics = {dataset_id: all_metrics[dataset_id] for dataset_id in ordered_dataset_ids}
    expected_execution_rows = _execution_rows(context, results)
    execution = _load_json(root / "provider_execution_audit.json")
    expected_execution = _execution_audit(
        expected_execution_rows,
        remediation_source_bundle_inventory_sha256=SUPERSEDED_INVENTORY_SHA256,
    )
    if execution != expected_execution:
        raise StudyArtifactError("provider execution audit semantic mismatch")

    validation = _validation_result(all_metrics)
    lock = _load_json(root / "validation_lock.json")
    expected_lock = _lock_payload(context, config, provider_config, all_metrics, validation)
    if lock != expected_lock:
        raise StudyArtifactError("validation lock semantic mismatch")
    holdout = _holdout_result(validation, all_metrics)
    expected_contract = _study_contract(config, provider_config)
    if _load_json(root / "study_contract.json") != expected_contract:
        raise StudyArtifactError("study contract semantic mismatch")
    cross_scope = root / "cross_scope_summary.csv"
    if cross_scope.read_bytes() != _csv_bytes(_cross_scope_rows(all_metrics)):
        raise StudyArtifactError("cross-scope summary mismatch")
    expected_stability = _stability_summary(
        all_metrics,
        expected_execution_rows,
        source_immutability_verified=True,
    )
    if _load_json(root / "stability_summary.json") != expected_stability:
        raise StudyArtifactError("stability summary semantic mismatch")
    decision = _load_json(root / "decision.json")
    expected_decision = _build_decision(
        context,
        config,
        provider_config,
        validation,
        holdout,
        all_metrics,
        lock,
        expected_execution_rows,
    )
    if decision != expected_decision:
        raise StudyArtifactError("decision semantic mismatch")
    expected_manifest = _manifest(
        root,
        context=context,
        validation_lock=lock,
        decision=decision,
    )
    if manifest != expected_manifest:
        raise StudyArtifactError("manifest semantic mismatch")
    return {
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "validation_lock_id": lock["validation_lock_id"],
        "study_status": decision["study_status"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--superseded-root", type=Path, default=SUPERSEDED_ROOT)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--offline-remediate", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_study_bundle(source_root=args.source_root, output_root=args.output_root)
        elif args.offline_remediate:
            result = regenerate_offline(
                superseded_root=args.superseded_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
        else:
            result = run_study(source_root=args.source_root, output_root=args.output_root)
    except (StudyArtifactError, ProviderScopeBlocked, FileExistsError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
