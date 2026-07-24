"""Run and verify the bounded Trendline V2 Phase 10B causal replay.

This script is deliberately a research/evidence boundary.  It owns no model
logic: generation calls the committed public discovery, selection and tracking
APIs, while verification reconstructs those typed values from persisted bytes
without calling a provider.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import statistics
import tempfile
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from libs.models.trendline_v2.api import (
    discover_trendlines,
    select_trendline_candidates,
    track_trendline_families,
)
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ProviderInput,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame
from libs.models.trendline_v2.selection import (
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    SelectionStatus,
)
from libs.models.trendline_v2.tracking import (
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransitionType,
    TrendlineTrackingSnapshot,
)
from libs.models.trendline_v2.domain.snapshots import DiscoverySnapshot

from scripts import analyze_trendline_v2_fresh_scope_family_validation as phase9c2
from scripts import validate_trendline_v2_canonical_selection as phase9d
from scripts import validate_trendline_v2_tracking_foundation as phase10a


UTC = timezone.utc
NANOSECONDS = 1_000_000_000

SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c1_fresh_scope_sources/20260522_20260701"
)
PHASE9D_ROOT = Path(
    "/tmp/trendline_v2_phase9d_canonical_selection/20260522_20260701"
)
PHASE10A_ROOT = Path(
    "/tmp/trendline_v2_phase10a_tracking_foundation/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase10b_causal_temporal_replay/20260603_20260701"
)

NETWORK_ENV = "TRENDLINE_V2_ALLOW_PHASE10B_PROVIDER_REPLAY"
STUDY_SCHEMA = "trendline_v2_phase_10b_causal_temporal_replay_v1"
CHECKPOINT_CONTRACT_SCHEMA = f"{STUDY_SCHEMA}_checkpoint_contract"
CHECKPOINT_SCHEMA = f"{STUDY_SCHEMA}_checkpoint"
SOURCE_AUDIT_SCHEMA = f"{STUDY_SCHEMA}_source_audit"
EXECUTION_AUDIT_SCHEMA = f"{STUDY_SCHEMA}_provider_execution_audit"
DECISION_SCHEMA = f"{STUDY_SCHEMA}_decision"
MANIFEST_SCHEMA = f"{STUDY_SCHEMA}_manifest"
DECISION_NAMESPACE = "trendline_v2_phase_10b_causal_temporal_replay_decision"
MANIFEST_NAMESPACE = "trendline_v2_phase_10b_causal_temporal_replay_manifest"
CHECKPOINT_NAMESPACE = "trendline_v2_phase_10b_checkpoint_contract"

PHASE9C1_COMMIT = "2d1da900399d9dc9a4d0dc2c9791f668b8b9fb86"
PHASE9C1_COHORT_CONTRACT_ID = (
    "55fabdf05929e923776d810c9958b26c44a8e85a5b92f73ec3027ab92dfcf00a"
)
PHASE9C1_COHORT_SOURCE_IDENTITY = (
    "c8cb7ecb7337020d09b3fe7a3026a14b84d07734252aa9bfa3f563d30f36ae72"
)
PHASE9C1_DECISION_ID = (
    "215600f4b80c356e95e969948dfd12ba57b17a55b140c25a8ea78ad3c9c15424"
)
PHASE9C1_MANIFEST_ID = (
    "e2afa4234054396ce5a7343eeb30f0e409fb56f0766c9c11a067180162374d56"
)
PHASE9C1_INVENTORY_SHA256 = (
    "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
)
PHASE9D_COMMIT = "722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f"
PHASE9D_DECISION_ID = (
    "c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd"
)
PHASE9D_MANIFEST_ID = (
    "51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585"
)
PHASE9D_INVENTORY_SHA256 = (
    "aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8"
)
PHASE10A_COMMIT = "c2210d00d96701e07d28024613113a7d6d13e2d5"
PHASE10A_DECISION_ID = (
    "44fe6f1c0c86563416f023c1c7530be61f30b0755ccf5335fbe0a4086df9ff0f"
)
PHASE10A_MANIFEST_ID = (
    "064a641c797c655d2726a4d332168cd3740159790dff1129047ca8bd12979d6a"
)
PHASE10A_INVENTORY_SHA256 = (
    "bc560cda8f4cd478313b8e4fb84338dc332679940ba6a56fde7b50dc97415080"
)

FOUNDATION_CONFIG_ID = (
    "02cdb171472b8ede327c2466c08ce295d72b16e34367047928757f80fd4f8396"
)
PROVIDER_CONFIG_ID = (
    "2aea7331fad4032db1803f21faa2df42fb2142f365331edce0723db5c55a2e6c"
)
COMBINED_CONFIG_ID = (
    "7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636"
)
PROVIDER_CONTRACT_ID = (
    "13828b02b649fc002681137bae82761d91283e8d1f19d3a3fbd719b8f1cf0e99"
)
SELECTION_POLICY_ID = (
    "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
)
TRACKING_POLICY_ID = (
    "82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce"
)
CHECKPOINT_CONTRACT_EXPECTED_ID = (
    "01e38027a396a03730bccf6479d4cc4ece4a4391d35b32fa13ce94aef01d22b5"
)
SUPERSEDED_CHECKPOINT_CONTRACT_ID = (
    "d89179340f6f6de06c9ec542e10533353170255bbfc5e8a858700762beafb93a"
)
SUPERSEDED_OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase10b_causal_temporal_replay_superseded/"
    "20260603_20260701_pre_checkpoint_identity_remediation"
)
SUPERSEDED_OUTPUT_INVENTORY_SHA256 = (
    "2bfbb333a25bf32bd2e2f79fe80ee9dcdb8b096562aafdc70c49a4d21fa91818"
)
SUPERSEDED_DECISION_ID = (
    "ed588f25583510b1ff42d7d776c777cb24652e9cde79b8f7a08642fdc55de1c0"
)

DATASET_ORDER = (
    "btcusdt_1h",
    "btcusdt_4h",
    "ethusdt_1h",
    "ethusdt_4h",
    "suiusdt_1h",
    "suiusdt_4h",
)
DATASET_MARKET = {
    "btcusdt_1h": ("BTCUSDT", "1h"),
    "btcusdt_4h": ("BTCUSDT", "4h"),
    "ethusdt_1h": ("ETHUSDT", "1h"),
    "ethusdt_4h": ("ETHUSDT", "4h"),
    "suiusdt_1h": ("SUIUSDT", "1h"),
    "suiusdt_4h": ("SUIUSDT", "4h"),
}
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
EXPECTED_FULL_INPUT_IDS = {
    "btcusdt_1h": "dde3d8a82109e4eda6dfec8b1a128e7896dc6845bcd47bab5754eefcc79623e9",
    "btcusdt_4h": "2de51ce8f76920b92269fe94c78efb636944d4c804d5dd723875903df5bc8aa8",
    "ethusdt_1h": "483d29e4aa2b32d85d00f8a58f956f84dfbf3ba14f6e80b80210968e85424469",
    "ethusdt_4h": "35965d4fe6b90298340a130063596011b3e0bcbff26463d68525f6097a762239",
    "suiusdt_1h": "713f24aa59bb0d8f9dbb4040cdbd56fa89c1890c263d9b9c6bc72c3c669679ae",
    "suiusdt_4h": "7a43ce7b5b8489e46edebe61a32144046c2309387a1998077f4ba2d08214cfae",
}
EXPECTED_PROVIDER_RESULT_IDS = {
    "btcusdt_1h": "68975843daddef910a08e390f475fdfc20fe784637767c92f4b1ff7d7cd12f9e",
    "btcusdt_4h": "ea53abf260b3b19966140bcb1157c4924b14c43d69307917e59fd95c8f973824",
    "ethusdt_1h": "b028dd306fd2131c2752f348847c65c3212060e9eb0b80e637bc84f021a66b77",
    "ethusdt_4h": "eaf1f8046f53c1316d7b3d99d5f039698c2d2f02ee7aa467d3fbf37e88dd33ca",
    "suiusdt_1h": "e00fd1762260dbcd3f58b327599fc06e09a8b0a43d39c09d29864dcd739f9e0f",
    "suiusdt_4h": "0f9b709398b4dfbdf3e078bc041e413afb88590defb09fe6a7f9efb1722734f8",
}
EXPECTED_SELECTION_SNAPSHOT_IDS = {
    "btcusdt_1h": "ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab",
    "btcusdt_4h": "31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da",
    "ethusdt_1h": "7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b",
    "ethusdt_4h": "f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56",
    "suiusdt_1h": "d2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db",
    "suiusdt_4h": "c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b",
}
EXPECTED_FINAL_ACTIVE_COUNTS = {
    "btcusdt_1h": 422,
    "btcusdt_4h": 106,
    "ethusdt_1h": 433,
    "ethusdt_4h": 109,
    "suiusdt_1h": 437,
    "suiusdt_4h": 112,
}


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    index: int
    observed_at: datetime
    expected_rows: Mapping[str, int]


CHECKPOINTS = (
    CheckpointSpec(1, datetime(2026, 6, 3, tzinfo=UTC), {"1h": 288, "4h": 72}),
    CheckpointSpec(2, datetime(2026, 6, 7, tzinfo=UTC), {"1h": 384, "4h": 96}),
    CheckpointSpec(3, datetime(2026, 6, 11, tzinfo=UTC), {"1h": 480, "4h": 120}),
    CheckpointSpec(4, datetime(2026, 6, 15, tzinfo=UTC), {"1h": 576, "4h": 144}),
    CheckpointSpec(5, datetime(2026, 6, 19, tzinfo=UTC), {"1h": 672, "4h": 168}),
    CheckpointSpec(6, datetime(2026, 6, 23, tzinfo=UTC), {"1h": 768, "4h": 192}),
    CheckpointSpec(7, datetime(2026, 6, 27, tzinfo=UTC), {"1h": 864, "4h": 216}),
    CheckpointSpec(8, datetime(2026, 7, 1, tzinfo=UTC), {"1h": 960, "4h": 240}),
)


class ReplayStudyError(RuntimeError):
    """Expected bounded replay or artifact validation failure."""


class ReplayScopeBlocked(ReplayStudyError):
    """The fixed provider replay cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ReplayDataset:
    dataset_id: str
    asset: str
    timeframe: str
    full_input: ProviderInput
    dataset_source_identity: str = ""
    request_order: int = 0


@dataclass(frozen=True, slots=True)
class FrozenReferences:
    datasets: tuple[ReplayDataset, ...]
    source_audit: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    dataset_id: str
    checkpoint: CheckpointSpec
    prefix_input: ProviderInput
    provider_result: ProviderResult
    discovery_snapshot: DiscoverySnapshot
    selection_snapshot: CandidateSelectionSnapshot
    tracking_snapshot: TrendlineTrackingSnapshot


ProviderCall = Callable[..., ProviderResult]


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


CHECKPOINT_BOUNDARY_RULE = "include source rows with timestamp < checkpoint"
CHECKPOINT_ALIGNMENT = "00:00:00Z and divisible by 1h and 4h"


def _checkpoint_contract_identity_payload_for(
    *,
    checkpoints: Sequence[CheckpointSpec],
    dataset_order: Sequence[str],
    boundary_rule: str,
    observed_at_equals_confirmed_through: bool = True,
    checkpoint_alignment: str = CHECKPOINT_ALIGNMENT,
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_CONTRACT_SCHEMA,
        "boundary_rule": boundary_rule,
        "observed_at_equals_confirmed_through": observed_at_equals_confirmed_through,
        "checkpoint_alignment": checkpoint_alignment,
        "dataset_order": list(dataset_order),
        "checkpoints": [
            {
                "checkpoint_index": checkpoint.index,
                "observed_at": _iso(checkpoint.observed_at),
                "rows_by_timeframe": dict(checkpoint.expected_rows),
            }
            for checkpoint in checkpoints
        ],
    }


def _checkpoint_contract_identity_payload() -> dict[str, Any]:
    """Return sole canonical payload for checkpoint contract identity."""

    return _checkpoint_contract_identity_payload_for(
        checkpoints=CHECKPOINTS,
        dataset_order=DATASET_ORDER,
        boundary_rule=CHECKPOINT_BOUNDARY_RULE,
    )


def _checkpoint_contract_id() -> str:
    identity = deterministic_hash(
        CHECKPOINT_NAMESPACE,
        _checkpoint_contract_identity_payload(),
    )
    if identity != CHECKPOINT_CONTRACT_EXPECTED_ID:
        raise ReplayStudyError("checkpoint contract identity drift")
    return identity


CHECKPOINT_CONTRACT_ID = _checkpoint_contract_id()


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
        raise ReplayStudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise ReplayStudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise ReplayStudyError(f"source root is missing: {root}")
    members: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ReplayStudyError(f"source file is a symlink: {path}")
        members.append(
            {
                "path": path.relative_to(root).as_posix(),
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(members)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output file: {path}")
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise ReplayStudyError("cannot serialize empty CSV")
    output = io.StringIO(newline="")
    fieldnames = tuple(rows[0])
    writer = csv.DictWriter(
        output, fieldnames=fieldnames, extrasaction="raise", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows({field: row[field] for field in fieldnames} for row in rows)
    return output.getvalue().encode("utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_atomic(path, _csv_bytes(rows))


def _fixed_configuration() -> tuple[
    ResolvedTrendlineV2Config,
    ConfirmedExtremaPairConfig,
    LatestValidPredecessorPolicy,
    ExactSelectedStructureTrackingPolicy,
]:
    config = resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )
    provider_config = ConfirmedExtremaPairConfig(
        lookback_duration_seconds=10_540_800.0,
        left_confirmation_bars=1,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        max_hypotheses=100_000,
        max_output_candidates=10_000,
    )
    selection_policy = LatestValidPredecessorPolicy()
    tracking_policy = ExactSelectedStructureTrackingPolicy()
    if config.semantic_hash != FOUNDATION_CONFIG_ID:
        raise ReplayStudyError("foundation configuration identity drift")
    if provider_config.semantic_hash != PROVIDER_CONFIG_ID:
        raise ReplayStudyError("provider configuration identity drift")
    if provider_config.provider_contract_identity != PROVIDER_CONTRACT_ID:
        raise ReplayStudyError("provider contract identity drift")
    if selection_policy.policy_identity != SELECTION_POLICY_ID:
        raise ReplayStudyError("selection policy identity drift")
    if tracking_policy.policy_identity != TRACKING_POLICY_ID:
        raise ReplayStudyError("tracking policy identity drift")
    combined = deterministic_hash(
        "trendline_v2_combined_configuration",
        {
            "foundation_config_identity": config.semantic_hash,
            "provider_config_identity": provider_config.semantic_hash,
        },
    )
    if combined != COMBINED_CONFIG_ID:
        raise ReplayStudyError("combined configuration identity drift")
    return config, provider_config, selection_policy, tracking_policy


def _checkpoint_contract() -> dict[str, Any]:
    identity_payload = _checkpoint_contract_identity_payload()
    return {
        "schema_version": CHECKPOINT_CONTRACT_SCHEMA,
        "namespace": CHECKPOINT_NAMESPACE,
        "checkpoint_contract_id": _checkpoint_contract_id(),
        "identity_payload": identity_payload,
        **{
            key: value
            for key, value in identity_payload.items()
            if key != "schema_version"
        },
    }


def _reference_inventory(root: Path, expected: str, *, label: str) -> tuple[dict[str, Any], ...]:
    inventory = _inventory(root)
    if _inventory_sha256(inventory) != expected:
        raise ReplayStudyError(f"{label} inventory drift")
    return inventory


def _load_frozen_references(source_root: Path = SOURCE_ROOT) -> FrozenReferences:
    """Validate all three frozen roots and derive datasets from Phase 9C.1."""

    before = {
        "phase9c1": _reference_inventory(
            source_root, PHASE9C1_INVENTORY_SHA256, label="Phase 9C.1 source"
        ),
        "phase9d": _reference_inventory(
            PHASE9D_ROOT, PHASE9D_INVENTORY_SHA256, label="Phase 9D source"
        ),
        "phase10a": _reference_inventory(
            PHASE10A_ROOT, PHASE10A_INVENTORY_SHA256, label="Phase 10A source"
        ),
    }
    try:
        cohort = phase9c2._load_cohort(source_root)
        p9d = phase9d.verify_study_bundle(
            source_root=phase9d.SOURCE_ROOT, output_root=PHASE9D_ROOT
        )
        p10a = phase10a.verify_study_bundle(
            source_root=PHASE9D_ROOT, output_root=PHASE10A_ROOT
        )
    except Exception as exc:
        raise ReplayStudyError("frozen source/reference verification failed") from exc
    if (
        cohort.cohort_contract_id != PHASE9C1_COHORT_CONTRACT_ID
        or cohort.cohort_source_identity != PHASE9C1_COHORT_SOURCE_IDENTITY
        or cohort.source_decision_id != PHASE9C1_DECISION_ID
        or cohort.source_manifest_id != PHASE9C1_MANIFEST_ID
        or cohort.source_inventory_sha256 != PHASE9C1_INVENTORY_SHA256
        or p9d["decision_id"] != PHASE9D_DECISION_ID
        or p9d["manifest_id"] != PHASE9D_MANIFEST_ID
        or p9d["output_inventory_sha256"] != PHASE9D_INVENTORY_SHA256
        or p10a["decision_id"] != PHASE10A_DECISION_ID
        or p10a["manifest_id"] != PHASE10A_MANIFEST_ID
        or p10a["output_inventory_sha256"] != PHASE10A_INVENTORY_SHA256
    ):
        raise ReplayStudyError("frozen source/reference identity drift")
    datasets: list[ReplayDataset] = []
    if tuple(dataset.dataset_id for dataset in cohort.datasets) != DATASET_ORDER:
        raise ReplayStudyError("dataset-major source order drift")
    for order, dataset in enumerate(cohort.datasets, start=1):
        if dataset.input_data.input_identity != EXPECTED_FULL_INPUT_IDS[dataset.dataset_id]:
            raise ReplayStudyError(f"full input identity drift: {dataset.dataset_id}")
        datasets.append(
            ReplayDataset(
                dataset_id=dataset.dataset_id,
                asset=dataset.asset,
                timeframe=dataset.timeframe,
                full_input=dataset.input_data,
                dataset_source_identity=dataset.dataset_source_identity,
                request_order=order,
            )
        )
    after = {
        "phase9c1": _reference_inventory(
            source_root, PHASE9C1_INVENTORY_SHA256, label="Phase 9C.1 source"
        ),
        "phase9d": _reference_inventory(
            PHASE9D_ROOT, PHASE9D_INVENTORY_SHA256, label="Phase 9D source"
        ),
        "phase10a": _reference_inventory(
            PHASE10A_ROOT, PHASE10A_INVENTORY_SHA256, label="Phase 10A source"
        ),
    }
    if before != after:
        raise ReplayStudyError("frozen source/reference changed during verification")
    source_audit = {
        "schema_version": SOURCE_AUDIT_SCHEMA,
        "source_roots": {
            "phase9c1": {
                "commit": PHASE9C1_COMMIT,
                "cohort_contract_id": PHASE9C1_COHORT_CONTRACT_ID,
                "cohort_source_identity": PHASE9C1_COHORT_SOURCE_IDENTITY,
                "decision_id": PHASE9C1_DECISION_ID,
                "manifest_id": PHASE9C1_MANIFEST_ID,
                "inventory_sha256": PHASE9C1_INVENTORY_SHA256,
                "member_count": len(before["phase9c1"]),
            },
            "phase9d": {
                "commit": PHASE9D_COMMIT,
                "decision_id": PHASE9D_DECISION_ID,
                "manifest_id": PHASE9D_MANIFEST_ID,
                "inventory_sha256": PHASE9D_INVENTORY_SHA256,
                "member_count": len(before["phase9d"]),
            },
            "phase10a": {
                "commit": PHASE10A_COMMIT,
                "decision_id": PHASE10A_DECISION_ID,
                "manifest_id": PHASE10A_MANIFEST_ID,
                "inventory_sha256": PHASE10A_INVENTORY_SHA256,
                "member_count": len(before["phase10a"]),
            },
        },
        "pre_run_inventories": {key: list(value) for key, value in before.items()},
        "post_run_inventories": {key: list(value) for key, value in after.items()},
        "source_immutability_verified": True,
        "network_request_count": 0,
    }
    return FrozenReferences(tuple(datasets), source_audit)


def _prefix_input(dataset: ReplayDataset, checkpoint: CheckpointSpec) -> ProviderInput:
    cutoff_ns = int(checkpoint.observed_at.timestamp() * NANOSECONDS)
    indices = [
        index
        for index, timestamp in enumerate(dataset.full_input.timestamps)
        if timestamp < cutoff_ns
    ]
    expected_rows = checkpoint.expected_rows[dataset.timeframe]
    if len(indices) != expected_rows:
        raise ReplayScopeBlocked(
            f"prefix row count mismatch: {dataset.dataset_id} checkpoint {checkpoint.index}"
        )
    if not indices:
        raise ReplayScopeBlocked("causal prefix is empty")
    interval_ns = INTERVAL_SECONDS[dataset.timeframe] * NANOSECONDS
    expected_last = cutoff_ns - interval_ns
    if dataset.full_input.timestamps[indices[-1]] != expected_last:
        raise ReplayScopeBlocked("causal prefix final timestamp mismatch")
    values = dataset.full_input
    return ProviderInput(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        observed_at=checkpoint.observed_at,
        confirmed_through=checkpoint.observed_at,
        timestamps=tuple(values.timestamps[index] for index in indices),
        open=tuple(values.open[index] for index in indices),
        high=tuple(values.high[index] for index in indices),
        low=tuple(values.low[index] for index in indices),
        close=tuple(values.close[index] for index in indices),
        volume=tuple(values.volume[index] for index in indices),
    )


def _frame_for_input(input_data: ProviderInput) -> ConfirmedOHLCVFrame:
    index = pd.to_datetime(input_data.timestamps, unit="ns", utc=True)
    frame = pd.DataFrame(
        {
            "open": input_data.open,
            "high": input_data.high,
            "low": input_data.low,
            "close": input_data.close,
            "volume": input_data.volume,
        },
        index=index,
    )
    result = ConfirmedOHLCVFrame.from_frame(
        frame,
        asset=input_data.asset,
        timeframe=input_data.timeframe,
        observed_at=input_data.observed_at,
        confirmed_through=input_data.confirmed_through,
    )
    return result


def _provider_result_id(result: ProviderResult) -> str:
    return phase9c2._provider_result_id(result)


def _execute_provider(
    prefix: ProviderInput,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    provider: ProviderCall,
) -> ProviderResult:
    result = provider(
        _frame_for_input(prefix), config=config, provider_config=provider_config
    )
    if not isinstance(result, ProviderResult):
        raise ReplayScopeBlocked("provider returned an invalid typed result")
    if result.status is not ProviderStatus.SUCCESS or result.reason is not None:
        raise ReplayScopeBlocked(
            "BLOCKED_PROVIDER_SCOPE: "
            f"status={result.status.value} reason="
            f"{getattr(result.reason, 'value', result.reason)}"
        )
    if not result.candidates or len(result.candidates) > 10_000:
        raise ReplayScopeBlocked("BLOCKED_PROVIDER_SCOPE: invalid candidate count")
    if (
        result.request.input_data.to_dict() != prefix.to_dict()
        or result.request.config.semantic_hash != config.semantic_hash
        or result.request.provider_config.semantic_hash != provider_config.semantic_hash
        or result.request.asset != prefix.asset
        or result.request.timeframe != prefix.timeframe
        or len(result.candidates) != len(result.evidence)
    ):
        raise ReplayScopeBlocked("BLOCKED_PROVIDER_SCOPE: request or evidence binding mismatch")
    return result


def _validate_tracking_step(
    current: TrendlineTrackingSnapshot,
    *,
    previous: TrendlineTrackingSnapshot | None,
    selection: CandidateSelectionSnapshot,
    checkpoint: CheckpointSpec,
) -> None:
    if current.status.value != "updated" or current.source_selection_status is not SelectionStatus.SELECTED:
        raise ReplayScopeBlocked("tracking source is not updated/selected")
    if current.observed_at != checkpoint.observed_at:
        raise ReplayScopeBlocked("tracking observation boundary mismatch")
    current_ids = {family.family_id for family in current.active_families}
    if len(current_ids) != len(current.active_families):
        raise ReplayScopeBlocked("active family IDs are not unique")
    if len(current.active_families) != len(selection.selected_candidates):
        raise ReplayScopeBlocked("tracking/selection active count mismatch")
    if previous is None:
        if (
            current.previous_tracking_snapshot_id is not None
            or current.diagnostics.birth_count != len(current.active_families)
            or current.diagnostics.continuation_count != 0
            or current.diagnostics.source_removed_count != 0
        ):
            raise ReplayScopeBlocked("initial replay birth gate failed")
        return
    previous_ids = {family.family_id for family in previous.active_families}
    if current.previous_tracking_snapshot_id != previous.snapshot_id:
        raise ReplayScopeBlocked("tracking previous snapshot binding mismatch")
    if not previous_ids.issubset(current_ids):
        raise ReplayScopeBlocked("active family set is not monotonic")
    if (
        current.diagnostics.continuation_count != len(previous_ids)
        or current.diagnostics.birth_count != len(current_ids - previous_ids)
        or current.diagnostics.source_removed_count != 0
        or current.removed_family_ids != previous.removed_family_ids
    ):
        raise ReplayScopeBlocked("replay transition arithmetic failed")
    previous_by_id = {family.family_id: family for family in previous.active_families}
    current_by_id = {family.family_id: family for family in current.active_families}
    for family_id, old in previous_by_id.items():
        new = current_by_id[family_id]
        if (
            new.version != old.version + 1
            or new.observation_count != old.observation_count + 1
            or new.first_seen_at != old.first_seen_at
            or new.last_seen_at != checkpoint.observed_at
            or new.current_candidate.candidate_id == old.current_candidate.candidate_id
        ):
            raise ReplayScopeBlocked("continuation lineage advancement failed")
    transition_types = Counter(item.transition_type for item in current.transitions)
    if (
        transition_types[FamilyTrackingTransitionType.BIRTH]
        != current.diagnostics.birth_count
        or transition_types[FamilyTrackingTransitionType.CONTINUE]
        != current.diagnostics.continuation_count
        or transition_types[FamilyTrackingTransitionType.SOURCE_REMOVED]
        != 0
    ):
        raise ReplayScopeBlocked("transition type counts failed")


def _replay_dataset(
    dataset: ReplayDataset,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
    provider: ProviderCall,
) -> tuple[ReplayRecord, ...]:
    previous: TrendlineTrackingSnapshot | None = None
    records: list[ReplayRecord] = []
    for checkpoint in CHECKPOINTS:
        prefix = _prefix_input(dataset, checkpoint)
        result = _execute_provider(
            prefix,
            config=config,
            provider_config=provider_config,
            provider=provider,
        )
        discovery = result.to_snapshot()
        selection = select_trendline_candidates(discovery, policy=selection_policy)
        tracking = track_trendline_families(
            selection, previous=previous, policy=tracking_policy
        )
        _validate_tracking_step(
            tracking,
            previous=previous,
            selection=selection,
            checkpoint=checkpoint,
        )
        records.append(
            ReplayRecord(
                dataset_id=dataset.dataset_id,
                checkpoint=checkpoint,
                prefix_input=prefix,
                provider_result=result,
                discovery_snapshot=discovery,
                selection_snapshot=selection,
                tracking_snapshot=tracking,
            )
        )
        previous = tracking
    return tuple(records)


def _replay_all(
    datasets: Sequence[ReplayDataset],
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
    provider: ProviderCall,
) -> tuple[ReplayRecord, ...]:
    if tuple(dataset.dataset_id for dataset in datasets) != DATASET_ORDER:
        raise ReplayScopeBlocked("replay dataset order mismatch")
    records: list[ReplayRecord] = []
    for dataset in datasets:
        records.extend(
            _replay_dataset(
                dataset,
                config=config,
                provider_config=provider_config,
                selection_policy=selection_policy,
                tracking_policy=tracking_policy,
                provider=provider,
            )
        )
    if len(records) != 48:
        raise ReplayScopeBlocked("provider execution count is not exactly 48")
    return tuple(records)


def _checkpoint_path(root: Path, record: ReplayRecord) -> Path:
    return root / "datasets" / record.dataset_id / (
        f"checkpoint_{record.checkpoint.index:02d}_"
        f"{record.checkpoint.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )


def _checkpoint_payload(record: ReplayRecord) -> dict[str, Any]:
    prefix = record.prefix_input
    arrays = prefix.timestamps
    return {
        "schema_version": CHECKPOINT_SCHEMA,
        "dataset_id": record.dataset_id,
        "checkpoint_index": record.checkpoint.index,
        "observed_at": _iso(record.checkpoint.observed_at),
        "prefix_row_count": prefix.row_count,
        "prefix_first_timestamp": _iso(
            datetime.fromtimestamp(arrays[0] / NANOSECONDS, tz=UTC)
        ),
        "prefix_last_timestamp": _iso(
            datetime.fromtimestamp(arrays[-1] / NANOSECONDS, tz=UTC)
        ),
        "full_source_input_identity": EXPECTED_FULL_INPUT_IDS[record.dataset_id],
        "prefix_input_identity": prefix.input_identity,
        "foundation_config_identity": FOUNDATION_CONFIG_ID,
        "provider_config_identity": PROVIDER_CONFIG_ID,
        "combined_config_identity": COMBINED_CONFIG_ID,
        "provider_contract_identity": PROVIDER_CONTRACT_ID,
        "selection_policy_identity": SELECTION_POLICY_ID,
        "tracking_policy_identity": TRACKING_POLICY_ID,
        "provider_result_id": _provider_result_id(record.provider_result),
        "provider_result": record.provider_result.to_dict(),
        "discovery_snapshot_id": record.discovery_snapshot.snapshot_id,
        "selection_snapshot": record.selection_snapshot.to_dict(),
        "tracking_snapshot": record.tracking_snapshot.to_dict(),
    }


def _execution_audit(records: Sequence[ReplayRecord]) -> dict[str, Any]:
    execution_records = []
    for execution_order, record in enumerate(records, start=1):
        execution_records.append(
            {
                "execution_order": execution_order,
                "dataset_id": record.dataset_id,
                "checkpoint_index": record.checkpoint.index,
                "observed_at": _iso(record.checkpoint.observed_at),
                "prefix_input_identity": record.prefix_input.input_identity,
                "request_identity": record.provider_result.request.request_identity,
                "provider_result_id": _provider_result_id(record.provider_result),
                "status": record.provider_result.status.value,
                "reason": None,
                "candidate_count": len(record.provider_result.candidates),
                "provider_execution_count": 1,
                "network_request_count": 0,
                "retry_count": 0,
                "fallback_count": 0,
                "configuration_variant": 0,
            }
        )
    return {
        "schema_version": EXECUTION_AUDIT_SCHEMA,
        "provider_execution_count": len(execution_records),
        "network_request_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "configuration_variant_count": 0,
        "parallel_execution_count": 0,
        "execution_order": execution_records,
    }


def _checkpoint_summary_rows(records: Sequence[ReplayRecord]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "dataset_id": record.dataset_id,
            "checkpoint_index": record.checkpoint.index,
            "observed_at": _iso(record.checkpoint.observed_at),
            "prefix_row_count": record.prefix_input.row_count,
            "prefix_input_identity": record.prefix_input.input_identity,
            "provider_result_id": _provider_result_id(record.provider_result),
            "discovery_snapshot_id": record.discovery_snapshot.snapshot_id,
            "selection_snapshot_id": record.selection_snapshot.snapshot_id,
            "tracking_snapshot_id": record.tracking_snapshot.snapshot_id,
            "candidate_count": len(record.provider_result.candidates),
            "selected_candidate_count": len(record.selection_snapshot.selected_candidates),
            "active_family_count": len(record.tracking_snapshot.active_families),
            "birth_count": record.tracking_snapshot.diagnostics.birth_count,
            "continuation_count": record.tracking_snapshot.diagnostics.continuation_count,
            "source_removed_count": record.tracking_snapshot.diagnostics.source_removed_count,
            "cumulative_removed_count": record.tracking_snapshot.diagnostics.cumulative_removed_count,
        }
        for record in records
    )


def _dataset_summary_rows(records: Sequence[ReplayRecord]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for dataset_id in DATASET_ORDER:
        current = tuple(record for record in records if record.dataset_id == dataset_id)
        final = current[-1]
        versions = Counter(
            str(family.version) for family in final.tracking_snapshot.active_families
        )
        turnover = sum(
            transition.transition_type is FamilyTrackingTransitionType.CONTINUE
            for record in current
            for transition in record.tracking_snapshot.transitions
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "checkpoint_count": len(current),
                "initial_active_family_count": len(current[0].tracking_snapshot.active_families),
                "final_active_family_count": len(final.tracking_snapshot.active_families),
                "total_birth_count": sum(
                    record.tracking_snapshot.diagnostics.birth_count for record in current
                ),
                "total_continuation_count": sum(
                    record.tracking_snapshot.diagnostics.continuation_count
                    for record in current
                ),
                "total_source_removed_count": sum(
                    record.tracking_snapshot.diagnostics.source_removed_count
                    for record in current
                ),
                "candidate_id_turnover_count": turnover,
                "active_family_minimum": min(
                    len(record.tracking_snapshot.active_families) for record in current
                ),
                "active_family_median": statistics.median(
                    len(record.tracking_snapshot.active_families) for record in current
                ),
                "active_family_maximum": max(
                    len(record.tracking_snapshot.active_families) for record in current
                ),
                "final_family_version_distribution": json.dumps(
                    dict(sorted(versions.items(), key=lambda item: int(item[0]))),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    return tuple(rows)


def _final_family_ids(records: Sequence[ReplayRecord]) -> dict[str, tuple[str, ...]]:
    return {
        dataset_id: tuple(
            family.family_id
            for family in next(
                record.tracking_snapshot
                for record in reversed(records)
                if record.dataset_id == dataset_id
            ).active_families
        )
        for dataset_id in DATASET_ORDER
    }


def _phase10a_family_ids() -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for dataset_id in DATASET_ORDER:
        payload = phase10a._load_json(
            PHASE10A_ROOT / "datasets" / dataset_id / "tracking_snapshot.json"
        )
        try:
            snapshot = TrendlineTrackingSnapshot.from_dict(payload["tracking_snapshot"])
        except (KeyError, ContractValidationError) as exc:
            raise ReplayStudyError(f"invalid Phase 10A family reference: {dataset_id}") from exc
        result[dataset_id] = tuple(family.family_id for family in snapshot.active_families)
    return result


def _parity(
    records: Sequence[ReplayRecord],
) -> tuple[bool, bool]:
    final_by_dataset = {
        dataset_id: next(
            record for record in reversed(records) if record.dataset_id == dataset_id
        )
        for dataset_id in DATASET_ORDER
    }
    selection_parity = all(
        _provider_result_id(final_by_dataset[dataset_id].provider_result)
        == EXPECTED_PROVIDER_RESULT_IDS[dataset_id]
        and final_by_dataset[dataset_id].selection_snapshot.snapshot_id
        == EXPECTED_SELECTION_SNAPSHOT_IDS[dataset_id]
        for dataset_id in DATASET_ORDER
    )
    expected_families = _phase10a_family_ids()
    family_parity = all(
        tuple(family.family_id for family in final_by_dataset[dataset_id].tracking_snapshot.active_families)
        == expected_families[dataset_id]
        for dataset_id in DATASET_ORDER
    )
    return selection_parity, family_parity


def _decision(
    records: Sequence[ReplayRecord],
    *,
    source_audit: Mapping[str, Any],
    execution_audit: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_rows = _dataset_summary_rows(records)
    selection_parity, family_parity = _parity(records)
    final_by_dataset = {
        dataset_id: next(
            record for record in reversed(records) if record.dataset_id == dataset_id
        )
        for dataset_id in DATASET_ORDER
    }
    births_by_checkpoint = [
        {
            "checkpoint_index": checkpoint.index,
            "birth_count": sum(
                record.tracking_snapshot.diagnostics.birth_count
                for record in records
                if record.checkpoint.index == checkpoint.index
            ),
            "continuation_count": sum(
                record.tracking_snapshot.diagnostics.continuation_count
                for record in records
                if record.checkpoint.index == checkpoint.index
            ),
            "source_removed_count": sum(
                record.tracking_snapshot.diagnostics.source_removed_count
                for record in records
                if record.checkpoint.index == checkpoint.index
            ),
        }
        for checkpoint in CHECKPOINTS
    ]
    active_counts = [len(record.tracking_snapshot.active_families) for record in records]
    total_births = sum(row["total_birth_count"] for row in dataset_rows)
    total_continuations = sum(row["total_continuation_count"] for row in dataset_rows)
    final_family_count = sum(
        len(final_by_dataset[dataset_id].tracking_snapshot.active_families)
        for dataset_id in DATASET_ORDER
    )
    payload: dict[str, Any] = {
        "schema_version": DECISION_SCHEMA,
        "study_status": "EXACT_TEMPORAL_REPLAY_VERIFIED",
        "checkpoint_contract_id": CHECKPOINT_CONTRACT_ID,
        "dataset_count": len(DATASET_ORDER),
        "checkpoints_per_dataset": len(CHECKPOINTS),
        "checkpoint_count": len(records),
        "phase10b_provider_executions": execution_audit["provider_execution_count"],
        "network_request_count": execution_audit["network_request_count"],
        "retry_count": execution_audit["retry_count"],
        "fallback_count": execution_audit["fallback_count"],
        "configuration_variant_count": execution_audit["configuration_variant_count"],
        "provider_success_count": sum(
            record.provider_result.status is ProviderStatus.SUCCESS for record in records
        ),
        "source_unavailable_count": sum(
            record.tracking_snapshot.status.value != "updated" for record in records
        ),
        "source_removed_transition_count": sum(
            record.tracking_snapshot.diagnostics.source_removed_count
            for record in records
        ),
        "final_active_family_count": final_family_count,
        "total_birth_count": total_births,
        "total_continuation_count": total_continuations,
        "candidate_id_turnover_count": total_continuations,
        "active_family_count_summary": {
            "minimum": min(active_counts),
            "median": statistics.median(active_counts),
            "maximum": max(active_counts),
        },
        "birth_count_by_checkpoint": births_by_checkpoint,
        "final_phase9d_selection_parity": selection_parity,
        "final_phase10a_family_parity": family_parity,
        "datasets": [
            {
                "dataset_id": row["dataset_id"],
                "active_tracked_family_count": row["final_active_family_count"],
                "birth_count": row["total_birth_count"],
                "continuation_count": row["total_continuation_count"],
                "source_removed_count": row["total_source_removed_count"],
                "candidate_id_turnover_count": row["candidate_id_turnover_count"],
                "final_family_version_distribution": row[
                    "final_family_version_distribution"
                ],
                "final_provider_result_id": _provider_result_id(
                    final_by_dataset[row["dataset_id"]].provider_result
                ),
                "final_selection_snapshot_id": final_by_dataset[
                    row["dataset_id"]
                ].selection_snapshot.snapshot_id,
                "final_tracking_snapshot_id": final_by_dataset[
                    row["dataset_id"]
                ].tracking_snapshot.snapshot_id,
            }
            for row in dataset_rows
        ],
        "identities": {
            "foundation_config_identity": FOUNDATION_CONFIG_ID,
            "provider_config_identity": PROVIDER_CONFIG_ID,
            "combined_config_identity": COMBINED_CONFIG_ID,
            "provider_contract_identity": PROVIDER_CONTRACT_ID,
            "selection_policy_identity": SELECTION_POLICY_ID,
            "tracking_policy_identity": TRACKING_POLICY_ID,
        },
        "source": {
            "phase9c1_inventory_sha256": source_audit["source_roots"]["phase9c1"]["inventory_sha256"],
            "phase9d_inventory_sha256": source_audit["source_roots"]["phase9d"]["inventory_sha256"],
            "phase10a_inventory_sha256": source_audit["source_roots"]["phase10a"]["inventory_sha256"],
            "phase9c1_decision_id": PHASE9C1_DECISION_ID,
            "phase9d_decision_id": PHASE9D_DECISION_ID,
            "phase10a_decision_id": PHASE10A_DECISION_ID,
        },
        "boundaries": {
            "NETWORK_REQUESTS": "NOT_AUTHORIZED",
            "PROVIDER_CONFIGURATION_VARIANTS": "NOT_AUTHORIZED",
            "APPROXIMATE_MATCHING": "NOT_AUTHORIZED",
            "ATR_OR_DISTANCE_MATCHING": "NOT_AUTHORIZED",
            "INTERACTIONS": "NOT_AUTHORIZED",
            "EVENTS": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
            "VIEWER_CHANGE": "NOT_AUTHORIZED",
            "RUNTIME_TRACKING_CHANGE": "NOT_AUTHORIZED",
        },
        "limitation": "This replay provides causal exact-lineage evidence, not profitability, predictive, interaction, event, MTF or runtime evidence.",
    }
    payload["decision_id"] = deterministic_hash(DECISION_NAMESPACE, payload)
    return payload


def _member_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in _inventory(root)
        if item["path"] != "manifest.json"
    )


def _manifest(
    root: Path,
    *,
    decision: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> dict[str, Any]:
    members = list(_member_inventory(root))
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "checkpoint_contract_id": CHECKPOINT_CONTRACT_ID,
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": members,
        "source_inventories": {
            key: value["inventory_sha256"]
            for key, value in source_audit["source_roots"].items()
        },
    }
    if len(members) != 54:
        raise ReplayStudyError(f"manifest must bind 54 members, got {len(members)}")
    payload["manifest_id"] = deterministic_hash(MANIFEST_NAMESPACE, payload)
    return payload


def _study_contract(
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    return {
        "schema_version": STUDY_SCHEMA,
        "checkpoint_contract": _checkpoint_contract(),
        "source": {
            "phase9c1_commit": PHASE9C1_COMMIT,
            "phase9c1_cohort_contract_id": PHASE9C1_COHORT_CONTRACT_ID,
            "phase9c1_cohort_source_identity": PHASE9C1_COHORT_SOURCE_IDENTITY,
            "phase9c1_decision_id": PHASE9C1_DECISION_ID,
            "phase9c1_manifest_id": PHASE9C1_MANIFEST_ID,
            "phase9c1_inventory_sha256": PHASE9C1_INVENTORY_SHA256,
            "phase9d_commit": PHASE9D_COMMIT,
            "phase9d_decision_id": PHASE9D_DECISION_ID,
            "phase9d_manifest_id": PHASE9D_MANIFEST_ID,
            "phase9d_inventory_sha256": PHASE9D_INVENTORY_SHA256,
            "phase10a_commit": PHASE10A_COMMIT,
            "phase10a_decision_id": PHASE10A_DECISION_ID,
            "phase10a_manifest_id": PHASE10A_MANIFEST_ID,
            "phase10a_inventory_sha256": PHASE10A_INVENTORY_SHA256,
        },
        "identities": {
            "foundation_config_identity": config.semantic_hash,
            "provider_config_identity": provider_config.semantic_hash,
            "combined_config_identity": COMBINED_CONFIG_ID,
            "provider_contract_identity": provider_config.provider_contract_identity,
            "selection_policy_identity": selection_policy.policy_identity,
            "tracking_policy_identity": tracking_policy.policy_identity,
        },
        "provider_configuration": provider_config.to_dict(),
        "selection_policy": selection_policy.to_dict(),
        "tracking_policy": tracking_policy.to_dict(),
        "execution": {
            "dataset_count": 6,
            "checkpoints_per_dataset": 8,
            "provider_execution_count": 48,
            "network_request_count": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "configuration_variant_count": 0,
            "parallel_execution_count": 0,
        },
        "boundaries": {
            "APPROXIMATE_MATCHING": "NOT_AUTHORIZED",
            "ATR_OR_DISTANCE_MATCHING": "NOT_AUTHORIZED",
            "CONFIDENCE_OR_RANKING": "NOT_AUTHORIZED",
            "INTERACTIONS": "NOT_AUTHORIZED",
            "EVENTS": "NOT_AUTHORIZED",
            "ROLE_REVERSAL": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
            "VIEWER_CHANGE": "NOT_AUTHORIZED",
            "STORAGE": "NOT_AUTHORIZED",
        },
    }


def _payloads(
    root: Path,
    *,
    records: Sequence[ReplayRecord],
    source_audit: Mapping[str, Any],
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    contract = _study_contract(config, provider_config, selection_policy, tracking_policy)
    execution = _execution_audit(records)
    checkpoint_rows = _checkpoint_summary_rows(records)
    dataset_rows = _dataset_summary_rows(records)
    decision = _decision(records, source_audit=source_audit, execution_audit=execution)
    payloads: dict[str, bytes] = {
        "study_contract.json": _canonical_bytes(contract),
        "source_audit.json": _canonical_bytes(dict(source_audit)),
        "provider_execution_audit.json": _canonical_bytes(execution),
        "checkpoint_summary.csv": _csv_bytes(checkpoint_rows),
        "dataset_summary.csv": _csv_bytes(dataset_rows),
        "decision.json": _canonical_bytes(decision),
    }
    for record in records:
        relative = _checkpoint_path(root, record).relative_to(root).as_posix()
        payloads[relative] = _canonical_bytes(_checkpoint_payload(record))
    return payloads, decision, contract


def _write_payloads(root: Path, payloads: Mapping[str, bytes]) -> None:
    for relative, data in sorted(payloads.items()):
        _write_atomic(root / relative, data)


def _assert_decision_gates(
    records: Sequence[ReplayRecord], decision: Mapping[str, Any]
) -> None:
    if decision["study_status"] != "EXACT_TEMPORAL_REPLAY_VERIFIED":
        raise ReplayScopeBlocked("decision status is not verified")
    if (
        decision["dataset_count"] != 6
        or decision["checkpoints_per_dataset"] != 8
        or decision["checkpoint_count"] != 48
        or decision["phase10b_provider_executions"] != 48
        or decision["network_request_count"] != 0
        or decision["retry_count"] != 0
        or decision["fallback_count"] != 0
        or decision["configuration_variant_count"] != 0
        or decision["provider_success_count"] != 48
        or decision["source_unavailable_count"] != 0
        or decision["source_removed_transition_count"] != 0
        or decision["final_active_family_count"] != 1_619
        or decision["total_birth_count"] != 1_619
        or not decision["final_phase9d_selection_parity"]
        or not decision["final_phase10a_family_parity"]
    ):
        raise ReplayScopeBlocked("aggregate replay gate failed")


def _verify_checkpoint_payload(
    payload: Mapping[str, Any],
    *,
    dataset: ReplayDataset,
    checkpoint: CheckpointSpec,
    previous: TrendlineTrackingSnapshot | None,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> ReplayRecord:
    expected_keys = {
        "schema_version",
        "dataset_id",
        "checkpoint_index",
        "observed_at",
        "prefix_row_count",
        "prefix_first_timestamp",
        "prefix_last_timestamp",
        "full_source_input_identity",
        "prefix_input_identity",
        "foundation_config_identity",
        "provider_config_identity",
        "combined_config_identity",
        "provider_contract_identity",
        "selection_policy_identity",
        "tracking_policy_identity",
        "provider_result_id",
        "provider_result",
        "discovery_snapshot_id",
        "selection_snapshot",
        "tracking_snapshot",
    }
    if set(payload) != expected_keys:
        raise ReplayStudyError(f"checkpoint payload keys mismatch: {dataset.dataset_id}")
    prefix = _prefix_input(dataset, checkpoint)
    if (
        payload["schema_version"] != CHECKPOINT_SCHEMA
        or payload["dataset_id"] != dataset.dataset_id
        or payload["checkpoint_index"] != checkpoint.index
        or payload["observed_at"] != _iso(checkpoint.observed_at)
        or payload["prefix_row_count"] != prefix.row_count
        or payload["prefix_first_timestamp"]
        != _iso(datetime.fromtimestamp(prefix.timestamps[0] / NANOSECONDS, tz=UTC))
        or payload["prefix_last_timestamp"]
        != _iso(datetime.fromtimestamp(prefix.timestamps[-1] / NANOSECONDS, tz=UTC))
        or payload["full_source_input_identity"] != dataset.full_input.input_identity
        or payload["prefix_input_identity"] != prefix.input_identity
        or payload["foundation_config_identity"] != config.semantic_hash
        or payload["provider_config_identity"] != provider_config.semantic_hash
        or payload["combined_config_identity"] != COMBINED_CONFIG_ID
        or payload["provider_contract_identity"] != PROVIDER_CONTRACT_ID
        or payload["selection_policy_identity"] != selection_policy.policy_identity
        or payload["tracking_policy_identity"] != tracking_policy.policy_identity
    ):
        raise ReplayStudyError(f"checkpoint causal/config binding mismatch: {dataset.dataset_id}")
    try:
        result = phase9c2._typed_result(payload["provider_result"])
    except Exception as exc:
        raise ReplayStudyError(f"invalid persisted provider result: {dataset.dataset_id}") from exc
    if (
        result.status is not ProviderStatus.SUCCESS
        or result.reason is not None
        or result.request.input_data.to_dict() != prefix.to_dict()
        or result.request.config.semantic_hash != config.semantic_hash
        or result.request.provider_config.semantic_hash != provider_config.semantic_hash
        or _provider_result_id(result) != payload["provider_result_id"]
    ):
        raise ReplayStudyError(f"persisted provider result binding mismatch: {dataset.dataset_id}")
    discovery = result.to_snapshot()
    if discovery.snapshot_id != payload["discovery_snapshot_id"]:
        raise ReplayStudyError(f"discovery snapshot mismatch: {dataset.dataset_id}")
    try:
        selection = CandidateSelectionSnapshot.from_dict(payload["selection_snapshot"])
        tracking = TrendlineTrackingSnapshot.from_dict(payload["tracking_snapshot"])
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise ReplayStudyError(f"invalid persisted selection/tracking: {dataset.dataset_id}") from exc
    expected_selection = select_trendline_candidates(discovery, policy=selection_policy)
    if selection.to_dict() != expected_selection.to_dict():
        raise ReplayStudyError(f"selection replay mismatch: {dataset.dataset_id}")
    expected_tracking = track_trendline_families(
        selection, previous=previous, policy=tracking_policy
    )
    if tracking.to_dict() != expected_tracking.to_dict():
        raise ReplayStudyError(f"tracking replay mismatch: {dataset.dataset_id}")
    _validate_tracking_step(
        tracking, previous=previous, selection=selection, checkpoint=checkpoint
    )
    record = ReplayRecord(
        dataset_id=dataset.dataset_id,
        checkpoint=checkpoint,
        prefix_input=prefix,
        provider_result=result,
        discovery_snapshot=discovery,
        selection_snapshot=selection,
        tracking_snapshot=tracking,
    )
    if canonical_json(payload) != canonical_json(_checkpoint_payload(record)):
        raise ReplayStudyError(f"checkpoint semantic round-trip mismatch: {dataset.dataset_id}")
    return record


def _load_and_replay_artifacts(
    root: Path,
    *,
    datasets: Sequence[ReplayDataset],
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> tuple[ReplayRecord, ...]:
    records: list[ReplayRecord] = []
    by_dataset = {dataset.dataset_id: dataset for dataset in datasets}
    for dataset_id in DATASET_ORDER:
        previous: TrendlineTrackingSnapshot | None = None
        dataset = by_dataset[dataset_id]
        for checkpoint in CHECKPOINTS:
            path = root / "datasets" / dataset_id / (
                f"checkpoint_{checkpoint.index:02d}_"
                f"{checkpoint.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
            )
            payload = _load_json(path)
            record = _verify_checkpoint_payload(
                payload,
                dataset=dataset,
                checkpoint=checkpoint,
                previous=previous,
                config=config,
                provider_config=provider_config,
                selection_policy=selection_policy,
                tracking_policy=tracking_policy,
            )
            records.append(record)
            previous = record.tracking_snapshot
    return tuple(records)


def _verify_manifest(
    root: Path,
    *,
    decision: Mapping[str, Any],
    source_audit: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = _load_json(root / "manifest.json")
    expected_without_id = {
        "schema_version": MANIFEST_SCHEMA,
        "checkpoint_contract_id": CHECKPOINT_CONTRACT_ID,
        "decision_id": decision["decision_id"],
        "member_count": manifest.get("member_count"),
        "members": manifest.get("members"),
        "source_inventories": {
            key: value["inventory_sha256"]
            for key, value in source_audit["source_roots"].items()
        },
    }
    if manifest != {
        **expected_without_id,
        "manifest_id": manifest.get("manifest_id"),
    }:
        raise ReplayStudyError("manifest semantic mismatch")
    if manifest["member_count"] != 54:
        raise ReplayStudyError("manifest member count mismatch")
    if manifest["members"] != list(_member_inventory(root)):
        raise ReplayStudyError("manifest member inventory mismatch")
    if manifest["manifest_id"] != deterministic_hash(MANIFEST_NAMESPACE, expected_without_id):
        raise ReplayStudyError("manifest identity mismatch")
    return manifest


def _verify_bundle(
    output_root: Path,
    *,
    references: FrozenReferences,
) -> dict[str, Any]:
    config, provider_config, selection_policy, tracking_policy = _fixed_configuration()
    contract = _load_json(output_root / "study_contract.json")
    expected_contract = _study_contract(
        config, provider_config, selection_policy, tracking_policy
    )
    if contract != expected_contract:
        raise ReplayStudyError("study contract semantic mismatch")
    source_audit = _load_json(output_root / "source_audit.json")
    if source_audit != dict(references.source_audit):
        raise ReplayStudyError("source audit semantic mismatch")
    execution = _load_json(output_root / "provider_execution_audit.json")
    records = _load_and_replay_artifacts(
        output_root,
        datasets=references.datasets,
        config=config,
        provider_config=provider_config,
        selection_policy=selection_policy,
        tracking_policy=tracking_policy,
    )
    expected_execution = _execution_audit(records)
    if execution != expected_execution:
        raise ReplayStudyError("provider execution audit mismatch")
    expected_checkpoint_csv = _csv_bytes(_checkpoint_summary_rows(records))
    expected_dataset_csv = _csv_bytes(_dataset_summary_rows(records))
    if (output_root / "checkpoint_summary.csv").read_bytes() != expected_checkpoint_csv:
        raise ReplayStudyError("checkpoint summary mismatch")
    if (output_root / "dataset_summary.csv").read_bytes() != expected_dataset_csv:
        raise ReplayStudyError("dataset summary mismatch")
    decision = _load_json(output_root / "decision.json")
    expected_decision = _decision(
        records, source_audit=source_audit, execution_audit=execution
    )
    if decision != expected_decision:
        raise ReplayStudyError("decision semantic mismatch")
    _assert_decision_gates(records, decision)
    manifest = _verify_manifest(
        output_root, decision=decision, source_audit=source_audit
    )
    inventory = _inventory(output_root)
    if len(inventory) != 55 or len(_member_inventory(output_root)) != 54:
        raise ReplayStudyError("replay bundle must contain 55 files and 54 members")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": _inventory_sha256(inventory),
        "checkpoint_contract_id": CHECKPOINT_CONTRACT_ID,
        "provider_execution_count": execution["provider_execution_count"],
        "network_request_count": execution["network_request_count"],
        "records": records,
    }


def _load_superseded_records(
    root: Path,
    *,
    references: FrozenReferences,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> tuple[ReplayRecord, ...]:
    """Load old checkpoint rows while ignoring only stale top-level identity."""

    if _inventory_sha256(_inventory(root)) != SUPERSEDED_OUTPUT_INVENTORY_SHA256:
        raise ReplayStudyError("superseded replay inventory drift")
    source_audit = _load_json(root / "source_audit.json")
    if source_audit != dict(references.source_audit):
        raise ReplayStudyError("superseded source audit drift")
    records = _load_and_replay_artifacts(
        root,
        datasets=references.datasets,
        config=config,
        provider_config=provider_config,
        selection_policy=selection_policy,
        tracking_policy=tracking_policy,
    )
    execution = _load_json(root / "provider_execution_audit.json")
    if execution != _execution_audit(records):
        raise ReplayStudyError("superseded provider execution audit drift")
    if (root / "checkpoint_summary.csv").read_bytes() != _csv_bytes(
        _checkpoint_summary_rows(records)
    ):
        raise ReplayStudyError("superseded checkpoint summary drift")
    if (root / "dataset_summary.csv").read_bytes() != _csv_bytes(
        _dataset_summary_rows(records)
    ):
        raise ReplayStudyError("superseded dataset summary drift")
    decision = _load_json(root / "decision.json")
    if (
        decision.get("decision_id") != SUPERSEDED_DECISION_ID
        or decision.get("checkpoint_contract_id") != SUPERSEDED_CHECKPOINT_CONTRACT_ID
    ):
        raise ReplayStudyError("superseded decision identity drift")
    manifest = _load_json(root / "manifest.json")
    manifest_payload = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    if (
        manifest.get("decision_id") != SUPERSEDED_DECISION_ID
        or manifest.get("member_count") != 54
        or manifest.get("members") != list(_member_inventory(root))
        or manifest.get("manifest_id")
        != deterministic_hash(MANIFEST_NAMESPACE, manifest_payload)
    ):
        raise ReplayStudyError("superseded manifest identity drift")
    return records


def republish_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    superseded_root: str | Path = SUPERSEDED_OUTPUT_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Republish top-level provenance offline from persisted checkpoint rows."""

    output_path = Path(output_root)
    if output_path.exists():
        raise FileExistsError(f"refusing existing output root: {output_path}")
    references = _load_frozen_references(Path(source_root))
    config, provider_config, selection_policy, tracking_policy = _fixed_configuration()
    records = _load_superseded_records(
        Path(superseded_root),
        references=references,
        config=config,
        provider_config=provider_config,
        selection_policy=selection_policy,
        tracking_policy=tracking_policy,
    )
    source_audit = _build_source_audit_after(Path(source_root), references.source_audit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.remediation-",
            dir=output_path.parent,
        )
    )
    try:
        payloads, decision, _ = _payloads(
            staging,
            records=records,
            source_audit=source_audit,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
        )
        _assert_decision_gates(records, decision)
        _write_payloads(staging, payloads)
        manifest = _manifest(staging, decision=decision, source_audit=source_audit)
        _write_json(staging / "manifest.json", manifest)
        _verify_bundle(staging, references=references)
        os.replace(staging, output_path)
        staging = None
        verified = _verify_bundle(
            output_path,
            references=_load_frozen_references(Path(source_root)),
        )
        return {
            key: value
            for key, value in verified.items()
            if key != "records"
        } | {
            "remediation_provider_execution_count": 0,
            "remediation_network_request_count": 0,
        }
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _build_source_audit_after(
    source_root: Path, before: Mapping[str, Any]
) -> Mapping[str, Any]:
    after = _load_frozen_references(source_root).source_audit
    if after != before:
        raise ReplayStudyError("frozen source/reference changed before publication")
    return after


def build_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    execute_provider_replay: bool = False,
    environment: Mapping[str, str] | None = None,
    provider: ProviderCall = discover_trendlines,
) -> dict[str, Any]:
    """Execute exactly one guarded 48-call replay and publish atomically."""

    output_path = Path(output_root)
    if output_path.exists():
        raise FileExistsError(f"refusing existing output root: {output_path}")
    if not execute_provider_replay:
        raise ReplayStudyError("provider replay requires --execute-provider-replay")
    env = os.environ if environment is None else environment
    if env.get(NETWORK_ENV) != "1":
        raise ReplayStudyError(f"provider replay requires {NETWORK_ENV}=1")
    references = _load_frozen_references(Path(source_root))
    config, provider_config, selection_policy, tracking_policy = _fixed_configuration()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records: tuple[ReplayRecord, ...] = ()
    staging: Path | None = Path(
        tempfile.mkdtemp(
            prefix=f".{output_path.name}.staging-",
            dir=output_path.parent,
        )
    )
    try:
        records = _replay_all(
            references.datasets,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
            provider=provider,
        )
        execution = _execution_audit(records)
        if execution["provider_execution_count"] != 48:
            raise ReplayScopeBlocked("provider execution count is not exactly 48")
        source_audit = _build_source_audit_after(
            Path(source_root), references.source_audit
        )
        payloads, decision, _ = _payloads(
            staging,
            records=records,
            source_audit=source_audit,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
        )
        _assert_decision_gates(records, decision)
        _write_payloads(staging, payloads)
        manifest = _manifest(staging, decision=decision, source_audit=source_audit)
        _write_json(staging / "manifest.json", manifest)
        _verify_bundle(staging, references=references)
        if output_path.exists():
            raise FileExistsError(f"refusing existing output root: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, output_path)
        staging = None
        verified = _verify_bundle(
            output_path,
            references=_load_frozen_references(Path(source_root)),
        )
        return {
            key: value
            for key, value in verified.items()
            if key != "records"
        }
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_study_bundle(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Verify persisted replay artifacts without executing any provider."""

    output_path = Path(output_root)
    if not output_path.is_dir():
        raise ReplayStudyError(f"replay output root is missing: {output_path}")
    references = _load_frozen_references(Path(source_root))
    verified = _verify_bundle(output_path, references=references)
    after = _load_frozen_references(Path(source_root))
    if after.source_audit != references.source_audit:
        raise ReplayStudyError("frozen source/reference changed during offline verification")
    return {key: value for key, value in verified.items() if key != "records"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--superseded-root", type=Path, default=SUPERSEDED_OUTPUT_ROOT)
    parser.add_argument("--execute-provider-replay", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--remediate-checkpoint-identity", action="store_true")
    args = parser.parse_args(argv)
    if sum(
        (
            args.execute_provider_replay,
            args.verify,
            args.remediate_checkpoint_identity,
        )
    ) > 1:
        parser.error(
            "--execute-provider-replay, --verify and "
            "--remediate-checkpoint-identity are mutually exclusive"
        )
    try:
        if args.verify:
            result = verify_study_bundle(
                source_root=args.source_root, output_root=args.output_root
            )
        elif args.remediate_checkpoint_identity:
            result = republish_study(
                source_root=args.source_root,
                superseded_root=args.superseded_root,
                output_root=args.output_root,
            )
        else:
            result = build_study(
                source_root=args.source_root,
                output_root=args.output_root,
                execute_provider_replay=args.execute_provider_replay,
            )
    except (
        ContractValidationError,
        FileExistsError,
        OSError,
        ReplayStudyError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
