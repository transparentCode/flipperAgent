"""Read-only Phase 11R.4 causal structural-reachability diagnostic.

This module deliberately does not import or execute the Phase 11R.3B runner.
It verifies the frozen R3B bundle, derives origin-time features once per
selection row, and keeps matched-control populations fully namespaced.
Canonical execution remains guarded and is not invoked by this task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


TEMPORAL_V2_ROOT = Path(
    "/tmp/trendline_v2_phase11r3b_joint_structural_compression_temporal_v2/20260522_20260701"
)
RAW_SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r4_causal_structural_reachability/20260522_20260701"
)
EXECUTION_GUARD = "TRENDLINE_V2_ALLOW_PHASE11R4_STUDY"

TEMPORAL_V2_DECISION_ID = (
    "66240c90f6d7b4c8575caebd1b248dbaa8084819c99504e19c210a0ec0b331ec"
)
TEMPORAL_V2_VALIDATION_LOCK_ID = (
    "27febb38504b51609b3bf70f7f879ce056f16ec2612bf727d33e236ee80ed276"
)
TEMPORAL_V2_MANIFEST_ID = (
    "69ec5869678d136dc366039424ca2912b2940d907524f55ed43b1958e0bccc3e"
)
TEMPORAL_V2_INVENTORY = (
    "658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c"
)
TEMPORAL_V2_CONTRACT_ID = (
    "e99ae58325df06923c83e0732d3a07c77446a32a5aa913d65411518ea4742a52"
)
RAW_AGGREGATE_INVENTORY = (
    "2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27"
)
TEMPORAL_V2_CONTRACT_NAMESPACE = (
    "trendline_v2_phase11r3b_joint_structural_compression_temporal_v2_contract"
)
TEMPORAL_V2_SOURCE_AUDIT_NAMESPACE = "trendline_v2_phase11r3b_source_audit"
TEMPORAL_V2_DECISION_NAMESPACE = "trendline_v2_phase11r3b_decision"
TEMPORAL_V2_LOCK_NAMESPACE = "trendline_v2_phase11r3b_validation_lock"
TEMPORAL_V2_MANIFEST_NAMESPACE = "trendline_v2_phase11r3b_manifest"
PHASE11R1_INVENTORY = (
    "17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50"
)
PHASE11R2_INVENTORY = (
    "382df2e22cb508d3982eb7e6d9566849dc65eb7316a8ce8c64b9c44d2d6713e4"
)
PHASE11R3A_INVENTORY = (
    "6335ec5dd2e67bc94f51ae5a1e0c0e265db743ad1aeccb0094ce4507466d2ff0"
)
TEMPORAL_V2_SOURCE_AUDIT_ID = (
    "f5f3eccc2b8399529a56c4fd8e1c973874f9ef768fc488f3d550e9bb289fe336"
)

TEMPORAL_V2_CONTRACT_JSON_SHA256 = (
    "e900f47774045f96d1d14658fa3972cda70a42ded2ea95b34aaaf79839da2ed4"
)
TEMPORAL_V2_CONTRACT_JSON_BYTE_LENGTH = 26223

TEMPORAL_V2_MEMBER_SPECS: tuple[tuple[str, str, int], ...] = (
    ("coherence_summary.csv", "caf431211c79020a199c27d78e3a2aab99e3e74dabdcd568e5d3bf62e2950470", 256323),
    ("compression_summary.csv", "2a55d5613650aad98ffbee992f9a48ce8a505e7d78718bde988583f32f43dcce", 719),
    ("datasets/btcusdt_1h/candidate_outcomes.json", "62c5f250140a4ca035e0a4c835cc1c31b9230e0454377cc81573298ad6c535f3", 4303191),
    ("datasets/btcusdt_1h/checkpoint_selection.json", "eb1327dadb8c8d732bdbb58a63fe1e2cf699c2caa6edc016de8f6b21dd907b28", 6239824),
    ("datasets/btcusdt_1h/policy_metrics.json", "6a2dd2e96000cecd28368cf96dec4ebe12f021af7b094fd8e32e6333a22aa96a", 33199),
    ("datasets/btcusdt_1h/structural_context.json", "b00c7510c2b5f6e04992eaf69ce0e606d761f91d4ca17ed6aeaa6c303d60a850", 73023),
    ("datasets/btcusdt_4h/candidate_outcomes.json", "a972f3b853ff5795fa8c9588a15f70f5b55cce567ff802c7c8f62d339a3bbcef", 6200502),
    ("datasets/btcusdt_4h/checkpoint_selection.json", "8649d3cf1f1ca9dc87f105ed0ad0504b85236de14196833889c967c1d2c3dc4f", 9288628),
    ("datasets/btcusdt_4h/policy_metrics.json", "8e23d3ce0cc2d8876f9859a66701a344237339d9d1c23084a18c8942e3de8c44", 34527),
    ("datasets/btcusdt_4h/structural_context.json", "c463b17548d1df48cf56a163b05048afceb8a1edc2cba62e1d4dcc80a9010c9c", 58592),
    ("datasets/ethusdt_1h/candidate_outcomes.json", "20e250a7ba1759893dabbdd87f32acc0cf5f89ccac1f7136a4a4b55a65296829", 4956519),
    ("datasets/ethusdt_1h/checkpoint_selection.json", "5c4cc348ce79f8621aa44fbaaa19370c8481af48df6b3ffdfd3aaf2873037a23", 6906653),
    ("datasets/ethusdt_1h/policy_metrics.json", "2a92759daf541cb74298ad3512be4f100253a17485ce95d05e9e6487244ba37d", 35338),
    ("datasets/ethusdt_1h/structural_context.json", "2acb38dbc2137773fbfd6380e5fc08893ed4fbd3614a25a1b388c4d2084fe063", 97375),
    ("datasets/ethusdt_4h/candidate_outcomes.json", "488dd4adde08d283fc061ad144e07a3cada1e36a6f8dec255ed954f8a86a54b8", 6235738),
    ("datasets/ethusdt_4h/checkpoint_selection.json", "cb559aa46d1c37dd42b4272e4e0faf7075c8ab36d07c86ebba28422363698526", 9216986),
    ("datasets/ethusdt_4h/policy_metrics.json", "89afedb8d76626e32bd513458b830eca90173eaec73b50410b088ac7f1fb550a", 34772),
    ("datasets/ethusdt_4h/structural_context.json", "8aa9558b489bb05fb66090ab432d19deb443993b20fcac83e11bad90bb3a921f", 65917),
    ("decision.json", "f47e045effd7b7eadba5c23bf6effed1784330b67b916a19fbc973c99ccb2aa5", 5415376),
    ("outcome_summary.csv", "722927e01d330fe32e39704b645e9452944a8d0fd124a0cc6b67625e8f8cb205", 3053),
    ("source_audit.json", "70e98db1b3fbe419f8237026273d827ee2d728cbab745d0bbff85555dc19fe1e", 3222),
    ("stability_summary.csv", "e6b5c7fc983e6645194b3861f6a5265af623a344320a219d2968104f51199cd6", 1078),
    ("study_contract.json", "d68cfd82c23f67bd2b0c34854ffe066a3459e48b2ac0c2abbd320c2689d74d35", 26534),
    ("validation_lock.json", "50c572cd5036331a052352b9b4e27f119bd1435a8626377709decb25631c9d61", 5562),
)
TEMPORAL_V2_EXPECTED_MEMBER_PATHS = tuple(item[0] for item in TEMPORAL_V2_MEMBER_SPECS)

DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
ROLES = ("support", "resistance")
HORIZONS_HOURS = (24, 48, 96)
BUDGETS = (1, 2, 3)
CONTENDERS = (
    "joint_incumbent_near_v1",
    "joint_incumbent_tenure_v1",
    "joint_incumbent_evidence_v1",
)
CONTROLS = (
    "joint_hash_order_control_v1",
    "joint_nearest_projection_control_v1",
)
POLICIES = CONTENDERS + CONTROLS
TIMEFRAME_SECONDS = {"1h": 3_600, "4h": 14_400}
PRIMARY_DISTANCE_THRESHOLD_ATR = 8.0
PRIMARY_HORIZON_HOURS = 96

RAW_MEMBERS: dict[str, tuple[str, int]] = {
    "datasets/btcusdt_1h/provider_result.json": (
        "39589107f6512af36bf69987a3580668851e3781d4990fd1d7d4ac6f912ff012",
        5_615_167,
    ),
    "datasets/btcusdt_4h/provider_result.json": (
        "0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3",
        877_457,
    ),
    "datasets/ethusdt_1h/provider_result.json": (
        "547b1818f2df0e1b95190355120960f55ca8379808fa94ce8f3f2ad0b3c5ab35",
        5_509_927,
    ),
    "datasets/ethusdt_4h/provider_result.json": (
        "2b3ccd8316d3119cbf3459d1eb98034124a90e0b20cad661955b1b1bf627087a",
        938_059,
    ),
}


class ReachabilityError(ValueError):
    """Expected contract, source, or diagnostic validation failure."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _canonical_json(value: Any) -> str:
    return _canonical_bytes(value).decode("utf-8").rstrip("\n")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(namespace: str, value: Any) -> str:
    payload = f"{namespace}:".encode("utf-8") + _canonical_json(value).encode("utf-8")
    return _sha256_bytes(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReachabilityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise ReachabilityError(f"non-finite JSON constant: {value}")


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReachabilityError(f"cannot read JSON: {path}") from exc


def _read_canonical_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ReachabilityError(f"invalid canonical JSON: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise ReachabilityError(f"non-canonical JSON artifact: {path}")
    return value


def _artifact_inventory(root: Path, *, include_manifest: bool = True) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise ReachabilityError(f"artifact root missing: {root}")
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReachabilityError(f"artifact symlink is not allowed: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if include_manifest or relative != "manifest.json":
                inventory.append(
                    {
                        "path": relative,
                        "byte_length": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
    return tuple(inventory)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ReachabilityError(f"{field} is not numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ReachabilityError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise ReachabilityError(f"{field} is not finite")
    return result


def _timestamp_ns(value: str | int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ReachabilityError("timestamp must be ISO string or integer nanoseconds")
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReachabilityError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ReachabilityError("timestamp must be timezone-aware")
    parsed = parsed.astimezone(UTC)
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def _iso_timestamp(timestamp_ns: int) -> str:
    seconds, nanos = divmod(timestamp_ns, 1_000_000_000)
    parsed = datetime.fromtimestamp(seconds, tz=UTC)
    if nanos:
        return parsed.replace(microsecond=nanos // 1_000).isoformat().replace(
            "+00:00", "Z"
        )
    return parsed.isoformat().replace("+00:00", "Z")


def _safe_relative_path(path: str) -> bool:
    candidate = Path(path)
    return (
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and "" not in candidate.parts
    )


@dataclass(frozen=True)
class RawDataset:
    dataset_id: str
    asset: str
    timeframe: str
    timestamps: tuple[int, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    input_identity: str

    @property
    def interval_ns(self) -> int:
        return TIMEFRAME_SECONDS[self.timeframe] * 1_000_000_000

    def atr_series(self) -> tuple[float, ...]:
        true_ranges: list[float] = []
        previous_close: float | None = None
        for high, low, close in zip(self.high, self.low, self.close):
            current = high - low
            if previous_close is not None:
                current = max(current, abs(high - previous_close), abs(low - previous_close))
            true_ranges.append(current)
            previous_close = close
        if not true_ranges:
            return ()
        atr = [true_ranges[0]]
        for true_range in true_ranges[1:]:
            atr.append((13.0 * atr[-1] + true_range) / 14.0)
        return tuple(atr)

    def origin_index(self, origin_time_ns: int) -> int | None:
        candidates = [
            index
            for index, timestamp in enumerate(self.timestamps)
            if timestamp < origin_time_ns and timestamp + self.interval_ns <= origin_time_ns
        ]
        return None if not candidates else candidates[-1]


@dataclass(frozen=True)
class VerifiedSources:
    temporal_root: Path
    raw_root: Path
    raw_datasets: dict[str, RawDataset]
    temporal_snapshot: dict[str, Any]
    raw_snapshot: dict[str, Any]


def _validate_ohlcv_arrays(input_data: Mapping[str, Any], dataset_id: str) -> RawDataset:
    required = (
        "asset",
        "timeframe",
        "timestamps",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "input_identity",
    )
    missing = [key for key in required if key not in input_data]
    if missing:
        raise ReachabilityError(f"raw input missing fields: {missing}")
    timeframe = input_data["timeframe"]
    if timeframe not in TIMEFRAME_SECONDS:
        raise ReachabilityError(f"unsupported timeframe: {timeframe}")
    arrays = {
        key: input_data[key]
        for key in ("timestamps", "open", "high", "low", "close", "volume")
    }
    if any(not isinstance(value, list) for value in arrays.values()):
        raise ReachabilityError("raw OHLCV arrays must be lists")
    lengths = {len(value) for value in arrays.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise ReachabilityError("raw OHLCV arrays have inconsistent length")
    timestamps = tuple(_timestamp_ns(value) for value in arrays["timestamps"])
    if tuple(sorted(set(timestamps))) != timestamps:
        raise ReachabilityError("raw timestamps are not strictly increasing")
    numeric: dict[str, tuple[float, ...]] = {}
    for key in ("open", "high", "low", "close", "volume"):
        numeric[key] = tuple(_finite(value, f"{dataset_id}.{key}") for value in arrays[key])
    for index, (open_, high, low, close, volume) in enumerate(
        zip(numeric["open"], numeric["high"], numeric["low"], numeric["close"], numeric["volume"])
    ):
        if high < low or high < open_ or high < close or low > open_ or low > close:
            raise ReachabilityError(f"invalid OHLC relationship at {dataset_id}:{index}")
        if volume < 0:
            raise ReachabilityError(f"negative volume at {dataset_id}:{index}")
    return RawDataset(
        dataset_id=dataset_id,
        asset=str(input_data["asset"]),
        timeframe=str(timeframe),
        timestamps=timestamps,
        open=numeric["open"],
        high=numeric["high"],
        low=numeric["low"],
        close=numeric["close"],
        volume=numeric["volume"],
        input_identity=str(input_data["input_identity"]),
    )


def verify_raw_source_root(
    root: Path = RAW_SOURCE_ROOT,
    *,
    expected_members: Mapping[str, tuple[str, int]] = RAW_MEMBERS,
) -> tuple[dict[str, RawDataset], dict[str, Any]]:
    """Verify exact raw membership, bytes, and causal OHLCV semantics."""
    if not root.is_dir():
        raise ReachabilityError(f"raw source root missing: {root}")
    datasets: dict[str, RawDataset] = {}
    members: list[dict[str, Any]] = []
    for relative, (expected_sha, expected_size) in sorted(expected_members.items()):
        path = root / relative
        if not _safe_relative_path(relative):
            raise ReachabilityError("unsafe raw source path")
        if not path.is_file():
            raise ReachabilityError(f"allowed raw source member missing: {relative}")
        actual_size = path.stat().st_size
        actual_sha = _sha256_file(path)
        if actual_size != expected_size or actual_sha != expected_sha:
            raise ReachabilityError(f"raw source byte drift: {relative}")
        payload = _read_json(path)
        if not isinstance(payload, Mapping):
            raise ReachabilityError(f"raw source payload is not an object: {relative}")
        if payload.get("network_request_count") != 0:
            raise ReachabilityError("raw source records network access")
        if not isinstance(payload.get("provider_execution_count"), int):
            raise ReachabilityError("raw source provider execution metadata missing")
        provider_result = payload.get("provider_result")
        if not isinstance(provider_result, Mapping):
            raise ReachabilityError("raw source provider result missing")
        input_data = provider_result.get("request", {}).get("input_data")
        if not isinstance(input_data, Mapping):
            raise ReachabilityError("raw source input data missing")
        dataset_id = str(payload.get("dataset_id"))
        dataset = _validate_ohlcv_arrays(input_data, dataset_id)
        if dataset_id not in DATASETS:
            raise ReachabilityError(f"unexpected raw dataset: {dataset_id}")
        datasets[dataset_id] = dataset
        members.append({"path": relative, "bytes": actual_size, "sha256": actual_sha})
    if tuple(sorted(datasets)) != DATASETS:
        raise ReachabilityError("raw source dataset set mismatch")
    return datasets, {
        "root": str(root),
        "aggregate_inventory": RAW_AGGREGATE_INVENTORY
        if expected_members is RAW_MEMBERS
        else None,
        "members": members,
    }


def read_allowed_raw_member(root: Path, relative: str) -> bytes:
    """Read only frozen provider-input members; reject every other path."""
    if relative not in RAW_MEMBERS:
        raise ReachabilityError(f"raw member access prohibited: {relative}")
    path = root / relative
    if not path.is_file():
        raise ReachabilityError(f"allowed raw source member missing: {relative}")
    return path.read_bytes()


def _manifest_members(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    members = manifest.get("members")
    if not isinstance(members, list) or not members:
        raise ReachabilityError("temporal manifest members missing")
    normalized: list[Mapping[str, Any]] = []
    paths: list[str] = []
    for member in members:
        if not isinstance(member, Mapping):
            raise ReachabilityError("invalid temporal manifest member")
        path = member.get("path")
        if not isinstance(path, str) or not _safe_relative_path(path):
            raise ReachabilityError("unsafe temporal manifest path")
        paths.append(path)
        normalized.append(member)
    if paths != sorted(set(paths)):
        raise ReachabilityError("temporal manifest paths are not canonical")
    return normalized


def _expected_temporal_manifest_payload() -> dict[str, Any]:
    members = [
        {"path": path, "sha256": sha256, "byte_length": byte_length}
        for path, sha256, byte_length in TEMPORAL_V2_MEMBER_SPECS
    ]
    return {
        "decision_id": TEMPORAL_V2_DECISION_ID,
        "member_count": len(members),
        "members": members,
        "output_inventory_sha256": TEMPORAL_V2_INVENTORY,
        "schema_version": "trendline_v2_phase11r3b_temporal_v2_manifest_v1",
        "source_audit_id": TEMPORAL_V2_SOURCE_AUDIT_ID,
        "study_contract_id": TEMPORAL_V2_CONTRACT_ID,
        "validation_lock_id": TEMPORAL_V2_VALIDATION_LOCK_ID,
    }


def verify_temporal_v2_root(
    root: Path = TEMPORAL_V2_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify exact frozen temporal-v2 bytes and content-derived identities."""
    expected_manifest_payload = _expected_temporal_manifest_payload()
    manifest = _read_canonical_json(root / "manifest.json")
    actual_manifest_payload = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    if actual_manifest_payload != expected_manifest_payload:
        raise ReachabilityError("temporal manifest content or identity mismatch")
    if manifest.get("manifest_id") != TEMPORAL_V2_MANIFEST_ID:
        raise ReachabilityError("temporal manifest identity mismatch")
    if _identity_hash(TEMPORAL_V2_MANIFEST_NAMESPACE, actual_manifest_payload) != TEMPORAL_V2_MANIFEST_ID:
        raise ReachabilityError("temporal manifest identity is not content-derived")
    actual_inventory = _artifact_inventory(root, include_manifest=False)
    expected_inventory = tuple(expected_manifest_payload["members"])
    if actual_inventory != expected_inventory:
        raise ReachabilityError("temporal member bytes or inventory mismatch")
    if _inventory_sha256(actual_inventory) != TEMPORAL_V2_INVENTORY:
        raise ReachabilityError("temporal inventory is not content-derived")

    contract = _read_canonical_json(root / "study_contract.json")
    contract_payload = contract.get("payload")
    if not isinstance(contract_payload, Mapping):
        raise ReachabilityError("temporal contract payload missing")
    contract_json = _canonical_json(contract_payload).encode("utf-8")
    if (
        contract.get("contract_id") != TEMPORAL_V2_CONTRACT_ID
        or contract.get("contract_json_byte_length") != TEMPORAL_V2_CONTRACT_JSON_BYTE_LENGTH
        or contract.get("contract_json_sha256") != TEMPORAL_V2_CONTRACT_JSON_SHA256
        or len(contract_json) != TEMPORAL_V2_CONTRACT_JSON_BYTE_LENGTH
        or _sha256_bytes(contract_json) != TEMPORAL_V2_CONTRACT_JSON_SHA256
        or _identity_hash(TEMPORAL_V2_CONTRACT_NAMESPACE, contract_payload) != TEMPORAL_V2_CONTRACT_ID
    ):
        raise ReachabilityError("temporal contract identity mismatch")

    decision = _read_canonical_json(root / "decision.json")
    decision_payload = {key: value for key, value in decision.items() if key != "decision_id"}
    if (
        decision.get("decision_id") != TEMPORAL_V2_DECISION_ID
        or _identity_hash(TEMPORAL_V2_DECISION_NAMESPACE, decision_payload) != TEMPORAL_V2_DECISION_ID
        or decision.get("finalist") is not None
        or decision.get("unresolved_evidence_count") != 0
        or decision.get("unresolved_reconciliation_count") != 0
        or "validation_lock_id" in decision
    ):
        raise ReachabilityError("temporal decision identity or boundary mismatch")

    lock = _read_canonical_json(root / "validation_lock.json")
    lock_payload = {key: value for key, value in lock.items() if key != "validation_lock_id"}
    if (
        lock.get("validation_lock_id") != TEMPORAL_V2_VALIDATION_LOCK_ID
        or _identity_hash(TEMPORAL_V2_LOCK_NAMESPACE, lock_payload) != TEMPORAL_V2_VALIDATION_LOCK_ID
        or lock.get("final_decision_id") != TEMPORAL_V2_DECISION_ID
        or lock.get("holdout_access_count") != 0
        or lock.get("temporal_access_count") != 0
    ):
        raise ReachabilityError("temporal validation-lock identity or boundary mismatch")

    source_audit = _read_canonical_json(root / "source_audit.json")
    source_audit_payload = {
        key: value for key, value in source_audit.items() if key != "source_audit_id"
    }
    forbidden_counts = (
        "holdout_accesses",
        "temporal_accesses",
        "network_requests",
        "provider_executions",
        "raw_sui_accesses",
        "legacy_executions",
    )
    if (
        source_audit.get("source_audit_id") != TEMPORAL_V2_SOURCE_AUDIT_ID
        or _identity_hash(TEMPORAL_V2_SOURCE_AUDIT_NAMESPACE, source_audit_payload) != TEMPORAL_V2_SOURCE_AUDIT_ID
        or source_audit.get("source_before") != source_audit.get("source_after")
        or source_audit.get("temporal_window_contract_id") != TEMPORAL_V2_CONTRACT_ID
        or source_audit.get("allowed_raw_paths") != list(RAW_MEMBERS)
        or source_audit.get("protected_inventories") != {
            "allowed_btc_eth_raw": RAW_AGGREGATE_INVENTORY,
            "phase11r1": PHASE11R1_INVENTORY,
            "phase11r2": PHASE11R2_INVENTORY,
        }
        or any(source_audit.get(field) != 0 for field in forbidden_counts)
    ):
        raise ReachabilityError("temporal source-audit identity or boundary mismatch")
    if (
        source_audit.get("phase11r3a", {}).get("inventory_sha256") != PHASE11R3A_INVENTORY
        or source_audit.get("phase11r3a", {}).get("manifest_id") != "74a5e78b119cc18a8c982a4e75a953a545780b10dbe7798464a8a9abdd1a146d"
    ):
        raise ReachabilityError("temporal source lineage mismatch")
    return {
        "root": str(root),
        "contract_id": TEMPORAL_V2_CONTRACT_ID,
        "decision_id": TEMPORAL_V2_DECISION_ID,
        "validation_lock_id": TEMPORAL_V2_VALIDATION_LOCK_ID,
        "manifest_id": TEMPORAL_V2_MANIFEST_ID,
        "inventory": TEMPORAL_V2_INVENTORY,
        "members": [
            {"path": path, "bytes": byte_length, "sha256": sha256}
            for path, sha256, byte_length in TEMPORAL_V2_MEMBER_SPECS
        ],
    }, {
        "contract": contract,
        "decision": decision,
        "validation_lock": lock,
        "source_audit": source_audit,
    }


def verify_sources(
    temporal_root: Path = TEMPORAL_V2_ROOT,
    raw_root: Path = RAW_SOURCE_ROOT,
) -> VerifiedSources:
    temporal_snapshot, temporal_payloads = verify_temporal_v2_root(temporal_root)
    raw_datasets, raw_snapshot = verify_raw_source_root(raw_root)
    return VerifiedSources(
        temporal_root=temporal_root,
        raw_root=raw_root,
        raw_datasets=raw_datasets,
        temporal_snapshot=temporal_snapshot,
        raw_snapshot=raw_snapshot,
    )


def _population_namespace(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["contender_policy_id"],
        row["budget_per_role"],
        row["derivation_type"],
        row["control_policy_id_or_null"],
        row["dataset_id"],
    )


def _row_population_namespace(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Read the full population identity carried by a derived row."""
    namespace = row.get("population_namespace")
    if isinstance(namespace, (list, tuple)) and len(namespace) == 5:
        return tuple(namespace)
    return _population_namespace(row)


def _namespace_cell_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    namespace = _row_population_namespace(row)
    return (*namespace, row["checkpoint_index"], row["semantic_role_at_selection"])


def _namespace_sort_key(namespace: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value) for value in namespace)


def _outcome_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["contender_policy_id"],
        row["budget_per_role"],
        row["derivation_type"],
        row.get("control_policy_id_or_null"),
        row["dataset_id"],
        row["checkpoint_index"],
        row["semantic_role_at_selection"],
        row["lineage_id"],
        row["horizon_hours"],
    )


def _feature_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["contender_policy_id"],
        row["budget_per_role"],
        row["derivation_type"],
        row.get("control_policy_id_or_null"),
        row["dataset_id"],
        row["checkpoint_index"],
        row["semantic_role_at_selection"],
        row["lineage_id"],
        row["selection_id"],
    )


def _safe_feature_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Build comparison-local identity without hiding malformed test rows."""
    return tuple(
        row.get(field)
        for field in (
            "contender_policy_id",
            "budget_per_role",
            "derivation_type",
            "control_policy_id_or_null",
            "dataset_id",
            "checkpoint_index",
            "semantic_role_at_selection",
            "lineage_id",
            "selection_id",
        )
    )


def _safe_outcome_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return _safe_feature_key(row) + (row.get("horizon_hours"),)


def _history_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["contender_policy_id"],
        row["budget_per_role"],
        row["derivation_type"],
        row.get("control_policy_id_or_null"),
        row["dataset_id"],
        row["lineage_id"],
    )


def _line_value(geometry: Mapping[str, Any], timestamp_ns: int) -> float:
    start_ns = _timestamp_ns(geometry["start_time"])
    end_ns = _timestamp_ns(geometry["end_time"])
    if end_ns <= start_ns:
        raise ReachabilityError("line geometry endpoints are unordered")
    start_price = _finite(geometry["start_price"], "geometry.start_price")
    end_price = _finite(geometry["end_price"], "geometry.end_price")
    return start_price + (timestamp_ns - start_ns) / (end_ns - start_ns) * (end_price - start_price)


def _selection_namespace(selection: Mapping[str, Any]) -> dict[str, Any] | None:
    policy = selection.get("policy_id")
    if policy in CONTENDERS:
        return {
            "contender_policy_id": policy,
            "derivation_type": "contender",
            "control_policy_id_or_null": None,
        }
    if policy in CONTROLS and selection.get("matched_contender_policy_id") in CONTENDERS:
        return {
            "contender_policy_id": selection["matched_contender_policy_id"],
            "derivation_type": "matched_control",
            "control_policy_id_or_null": policy,
        }
    return None


def iter_primary_selection_rows(
    dataset_id: str,
    selection_payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    records = selection_payload.get("records")
    if not isinstance(records, list):
        raise ReachabilityError(f"selection records missing: {dataset_id}")
    for selection in records:
        namespace = _selection_namespace(selection)
        if namespace is None or selection.get("budget_per_role") not in BUDGETS:
            continue
        selection_dataset = selection.get("dataset_id")
        if selection_dataset != dataset_id:
            errors.append("selection dataset mismatch")
            continue
        for role in ROLES:
            selected_rows = selection.get("selected_rows", {}).get(role, [])
            if not isinstance(selected_rows, list):
                errors.append("selected role rows are not a list")
                continue
            for selected in selected_rows:
                if not isinstance(selected, Mapping):
                    errors.append("selected row is not an object")
                    continue
                row = dict(selected)
                row.update(namespace)
                row.update(
                    {
                        "budget_per_role": selection["budget_per_role"],
                        "dataset_id": dataset_id,
                        "selection_id": selection.get("selection_id"),
                        "semantic_role_at_selection": role,
                        "policy_id": selection.get("policy_id"),
                        "matched_contender_policy_id": selection.get("matched_contender_policy_id"),
                        "derivation_type": namespace["derivation_type"],
                        "control_policy_id_or_null": namespace["control_policy_id_or_null"],
                    }
                )
                if not isinstance(row.get("selection_id"), str):
                    errors.append("selection identity missing")
                if row.get("semantic_role") != role:
                    errors.append("selected role mismatch")
                rows.append(row)
    return rows, errors


def _origin_values(dataset: RawDataset, origin_ns: int) -> tuple[int, float, float]:
    index = dataset.origin_index(origin_ns)
    if index is None:
        raise ReachabilityError("no causal origin bar")
    atr = dataset.atr_series()[index]
    if atr <= 0:
        raise ReachabilityError("origin ATR is not positive")
    return index, dataset.close[index], atr


def build_feature_rows(
    rows: Sequence[Mapping[str, Any]],
    datasets: Mapping[str, RawDataset],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build one causal feature row per selection identity, before horizons."""
    features: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for raw in rows:
        key = _feature_key(raw)
        if key in seen_keys:
            errors.append("duplicate causal feature key")
            continue
        seen_keys.add(key)
        feature = {field: raw.get(field) for field in (
            "contender_policy_id",
            "budget_per_role",
            "derivation_type",
            "control_policy_id_or_null",
            "dataset_id",
            "checkpoint_index",
            "semantic_role_at_selection",
            "lineage_id",
            "selection_id",
            "checkpoint_observed_at",
            "fixed_geometry",
            "role_transfer",
            "state",
        )}
        feature["population_namespace"] = list(_population_namespace(raw))
        feature["causal_feature_observation_key"] = list(key)
        try:
            dataset = datasets[raw["dataset_id"]]
            origin_ns = _timestamp_ns(raw["checkpoint_observed_at"])
            _, origin_close, origin_atr = _origin_values(dataset, origin_ns)
            geometry = raw["fixed_geometry"]
            line_origin = _line_value(geometry, origin_ns)
            initial_distance = abs(origin_close - line_origin) / origin_atr
            start_ns = _timestamp_ns(geometry["start_time"])
            end_ns = _timestamp_ns(geometry["end_time"])
            slope_price = (float(geometry["end_price"]) - float(geometry["start_price"])) / ((end_ns - start_ns) / 3_600_000_000_000)
            feature.update(
                {
                    "origin_time": _iso_timestamp(origin_ns),
                    "origin_time_ns": origin_ns,
                    "origin_close": origin_close,
                    "origin_atr": origin_atr,
                    "line_value_at_origin": line_origin,
                    "initial_distance_atr": initial_distance,
                    "line_slope_price_per_hour": slope_price,
                    "line_slope_atr_per_hour": slope_price / origin_atr,
                    "geometry_projected_distance_atr_24h": abs(origin_close - _line_value(geometry, origin_ns + 24 * 3_600_000_000_000)) / origin_atr,
                    "geometry_projected_distance_atr_48h": abs(origin_close - _line_value(geometry, origin_ns + 48 * 3_600_000_000_000)) / origin_atr,
                    "geometry_projected_distance_atr_96h": abs(origin_close - _line_value(geometry, origin_ns + 96 * 3_600_000_000_000)) / origin_atr,
                    "geometry_evaluable": True,
                    "geometry_not_evaluable_reason": None,
                }
            )
        except (KeyError, TypeError, ReachabilityError) as exc:
            feature.update(
                {
                    "origin_time": raw.get("checkpoint_observed_at"),
                    "origin_time_ns": None,
                    "origin_close": None,
                    "origin_atr": None,
                    "line_value_at_origin": None,
                    "initial_distance_atr": None,
                    "line_slope_price_per_hour": None,
                    "line_slope_atr_per_hour": None,
                    "geometry_projected_distance_atr_24h": None,
                    "geometry_projected_distance_atr_48h": None,
                    "geometry_projected_distance_atr_96h": None,
                    "geometry_evaluable": False,
                    "geometry_not_evaluable_reason": str(exc),
                }
            )
        features.append(feature)

    history: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for feature in features:
        history.setdefault(_history_key(feature), []).append(feature)
    for sequence, sequence_rows in history.items():
        sequence_rows.sort(key=lambda item: item["checkpoint_index"])
        previous: dict[str, Any] | None = None
        for feature in sequence_rows:
            if previous is None or not feature["geometry_evaluable"] or not previous["geometry_evaluable"]:
                feature.update(
                    {
                        "previous_observation_key": None,
                        "previous_distance_atr": None,
                        "previous_elapsed_hours": None,
                        "prior_observed_distance_change_rate": None,
                        "prior_distance_not_evaluable_reason": "no_valid_previous_feature",
                    }
                )
            else:
                elapsed = (feature["origin_time_ns"] - previous["origin_time_ns"]) / 3_600_000_000_000
                if elapsed <= 0:
                    errors.append("non-positive feature history interval")
                    feature["prior_distance_not_evaluable_reason"] = "invalid_history_interval"
                    feature["previous_observation_key"] = None
                    feature["previous_distance_atr"] = None
                    feature["previous_elapsed_hours"] = None
                    feature["prior_observed_distance_change_rate"] = None
                else:
                    feature.update(
                        {
                            "previous_observation_key": previous["causal_feature_observation_key"],
                            "previous_distance_atr": previous["initial_distance_atr"],
                            "previous_elapsed_hours": elapsed,
                            "prior_observed_distance_change_rate": (feature["initial_distance_atr"] - previous["initial_distance_atr"]) / elapsed,
                            "prior_distance_not_evaluable_reason": None,
                        }
                    )
            if previous is not None and feature["checkpoint_index"] == previous["checkpoint_index"]:
                errors.append("duplicate feature history checkpoint")
            previous = feature
    return features, errors


def join_horizon_outcomes(
    features: Sequence[Mapping[str, Any]],
    outcome_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Join exactly three outcomes and reject relevant orphan records."""
    index: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    errors: list[str] = []
    for outcome in outcome_records:
        if not isinstance(outcome, Mapping):
            errors.append("relevant outcome is not an object")
            continue
        if outcome.get("derivation_type") not in ("contender", "matched_control"):
            continue
        try:
            key = _outcome_key(outcome)
        except (KeyError, TypeError):
            errors.append("relevant outcome key is malformed")
            continue
        if key in index:
            errors.append("duplicate outcome key")
            continue
        index[key] = outcome
    joined: list[dict[str, Any]] = []
    expected_keys: set[tuple[Any, ...]] = set()
    consumed_keys: set[tuple[Any, ...]] = set()
    for feature in features:
        for horizon in HORIZONS_HOURS:
            key = (
                feature["contender_policy_id"],
                feature["budget_per_role"],
                feature["derivation_type"],
                feature["control_policy_id_or_null"],
                feature["dataset_id"],
                feature["checkpoint_index"],
                feature["semantic_role_at_selection"],
                feature["lineage_id"],
                horizon,
            )
            if key in expected_keys:
                errors.append("duplicate feature outcome expectation")
                continue
            expected_keys.add(key)
            outcome = index.get(key)
            if outcome is None or outcome.get("selection_id") != feature["selection_id"]:
                errors.append("outcome does not bind to feature identity")
                continue
            consumed_keys.add(key)
            row = dict(feature)
            row["horizon_hours"] = horizon
            row["outcome"] = dict(outcome)
            joined.append(row)
    for key in index:
        if key not in expected_keys or key not in consumed_keys:
            errors.append("orphan outcome key")
    return joined, errors


def classify_stratum_cell(
    contender_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
    *,
    duplicate: bool = False,
    unresolved: bool = False,
) -> str:
    """Return terminal cell class using frozen fail-closed precedence."""
    if unresolved:
        return "unresolved"
    if duplicate:
        return "duplicate"
    if contender_rows and control_rows:
        return "paired"
    if contender_rows:
        return "contender_only"
    if control_rows:
        return "control_only"
    return "empty_both"


def matched_within_stratum(counts: Mapping[str, int], accounting_valid: bool = True) -> bool:
    return (
        counts.get("paired_cells", 0) >= 1
        and counts.get("contender_only_cells", 0) == 0
        and counts.get("control_only_cells", 0) == 0
        and counts.get("duplicate_cells", 0) == 0
        and counts.get("unresolved_cells", 0) == 0
        and accounting_valid
    )


def decision_from_comparisons(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    blocked: bool = False,
    source_errors: int = 0,
) -> tuple[str, str | None]:
    """Apply exact R4 integrity/support/decision precedence."""
    if blocked:
        return "R4_DIAGNOSTIC_BLOCKED", None
    if source_errors or any(
        int(item.get("duplicate_cells", 0)) > 0
        or int(item.get("unresolved_cells", 0)) > 0
        or item.get("namespace_valid") is False
        for item in comparisons
    ):
        return "R4_DIAGNOSTIC_INCOMPLETE", None
    if any(int(item.get("paired_cells", 0)) == 0 for item in comparisons):
        return "R4_DIAGNOSTIC_COMPLETE", "INSUFFICIENT_REACHABLE_SUPPORT"
    if any(
        int(item.get("contender_only_cells", 0)) > 0
        or int(item.get("control_only_cells", 0)) > 0
        for item in comparisons
    ):
        return "R4_DIAGNOSTIC_INCOMPLETE", None
    if not all(item.get("matched") is True for item in comparisons):
        return "R4_DIAGNOSTIC_INCOMPLETE", None
    if all(float(item.get("survival_delta_96h", 0.0)) >= 0.0 for item in comparisons):
        return "R4_DIAGNOSTIC_COMPLETE", "REACHABILITY_ELIGIBILITY_HYPOTHESIS_SUPPORTED"
    return "R4_DIAGNOSTIC_COMPLETE", "CLOSE_STRUCTURAL_COMPRESSION_BRANCH"


def _selection_cell_index(
    dataset_id: str,
    selection_payload: Mapping[str, Any],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], list[str]]:
    cells: dict[tuple[Any, ...], dict[str, Any]] = {}
    errors: list[str] = []
    records = selection_payload.get("records")
    if not isinstance(records, list):
        return {}, ["selection records missing"]
    for selection in records:
        namespace = _selection_namespace(selection)
        if namespace is None or selection.get("budget_per_role") not in BUDGETS:
            continue
        checkpoint = selection.get("checkpoint_index")
        key = (
            namespace["contender_policy_id"],
            selection["budget_per_role"],
            namespace["derivation_type"],
            namespace["control_policy_id_or_null"],
            dataset_id,
            checkpoint,
        )
        if key in cells:
            errors.append("duplicate source selection cell")
            cells[key]["duplicate"] = True
            cells[key].setdefault("reconciliation_errors", []).append(
                "duplicate_source_membership"
            )
            continue
        selected_rows = selection.get("selected_rows", {})
        cells[key] = {
            "selection_id": selection.get("selection_id"),
            "counts": {
                role: len(selected_rows.get(role, [])) for role in ROLES
            },
            "duplicate": False,
            "reconciliation_errors": [],
        }
    return cells, errors


def _mean_outcome(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [
        float(bool(row.get("outcome", {}).get(field)))
        for row in rows
        if row.get("outcome", {}).get("evaluable") is True
        and row.get("outcome", {}).get(field) is not None
    ]
    return None if not values else sum(values) / len(values)


def _primary_row(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("geometry_evaluable") is True
        and float(row.get("geometry_projected_distance_atr_96h", math.inf))
        <= PRIMARY_DISTANCE_THRESHOLD_ATR
    )


def _numeric_distribution(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "values": [], "min": None, "max": None, "mean": None}
    return {
        "count": len(ordered),
        "values": ordered,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def _distance_band(value: float | None) -> str:
    if value is None:
        return "not_evaluable"
    if value <= 4.0:
        return "<=4 ATR"
    if value <= 8.0:
        return ">4-8 ATR"
    if value <= 16.0:
        return ">8-16 ATR"
    return ">16 ATR"


def _feature_evidence_summary(
    features: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    groups: dict[tuple[tuple[Any, ...], str], list[Mapping[str, Any]]] = {}
    for row in features:
        groups.setdefault(
            (_row_population_namespace(row), str(row["semantic_role_at_selection"])),
            [],
        ).append(row)

    by_namespace_role: list[dict[str, Any]] = []
    for (namespace, role), selected in sorted(
        groups.items(), key=lambda item: (_namespace_sort_key(item[0][0]), item[0][1])
    ):
        dataset_id = str(namespace[-1])
        evaluable = [row for row in selected if row.get("geometry_evaluable") is True]
        reachable = [row for row in evaluable if _primary_row(row)]
        initial_values = [
            float(row["initial_distance_atr"])
            for row in selected
            if row.get("initial_distance_atr") is not None
        ]
        by_namespace_role.append(
            {
                "population_namespace": list(namespace),
                "dataset_id": dataset_id,
                "timeframe": dataset_id.rsplit("_", 1)[1],
                "role": role,
                "feature_row_count": len(selected),
                "geometry_evaluable_count": len(evaluable),
                "geometry_not_evaluable_count": len(selected) - len(evaluable),
                "primary_reachable_count": len(reachable),
                "primary_unreachable_count": len(evaluable) - len(reachable),
                "initial_distance_distribution": _numeric_distribution(initial_values),
                "initial_distance_bands": {
                    band: sum(
                        _distance_band(row.get("initial_distance_atr")) == band
                        for row in selected
                    )
                    for band in ("<=4 ATR", ">4-8 ATR", ">8-16 ATR", ">16 ATR", "not_evaluable")
                },
                "projected_distance_24h_distribution": _numeric_distribution(
                    [
                        float(row["geometry_projected_distance_atr_24h"])
                        for row in selected
                        if row.get("geometry_projected_distance_atr_24h") is not None
                    ]
                ),
                "projected_distance_48h_distribution": _numeric_distribution(
                    [
                        float(row["geometry_projected_distance_atr_48h"])
                        for row in selected
                        if row.get("geometry_projected_distance_atr_48h") is not None
                    ]
                ),
                "projected_distance_96h_distribution": _numeric_distribution(
                    [
                        float(row["geometry_projected_distance_atr_96h"])
                        for row in selected
                        if row.get("geometry_projected_distance_atr_96h") is not None
                    ]
                ),
            }
        )

    namespaces = sorted(
        {_row_population_namespace(row) for row in features},
        key=_namespace_sort_key,
    )
    balance: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for namespace in namespaces:
        namespace_rows = [
            row for row in features if _row_population_namespace(row) == namespace
        ]
        role_counts = {
            role: sum(row.get("semantic_role_at_selection") == role for row in namespace_rows)
            for role in ROLES
        }
        total = sum(role_counts.values())
        balance.append(
            {
                "population_namespace": list(namespace),
                "dataset_id": namespace[-1],
                "support_count": role_counts["support"],
                "resistance_count": role_counts["resistance"],
                "support_fraction": role_counts["support"] / total if total else None,
                "resistance_fraction": role_counts["resistance"] / total if total else None,
            }
        )
        checkpoint_roles: dict[int, set[str]] = {
            checkpoint: {
                str(row["semantic_role_at_selection"])
                for row in namespace_rows
                if row.get("checkpoint_index") == checkpoint
            }
            for checkpoint in range(1, 23)
        }
        coverage.append(
            {
                "population_namespace": list(namespace),
                "dataset_id": namespace[-1],
                "both_role_checkpoint_count": sum(
                    roles == set(ROLES) for roles in checkpoint_roles.values()
                ),
                "one_sided_checkpoint_count": sum(
                    bool(roles) and roles != set(ROLES)
                    for roles in checkpoint_roles.values()
                ),
                "empty_checkpoint_count": sum(
                    not roles for roles in checkpoint_roles.values()
                ),
                "checkpoint_denominator": 22,
            }
        )
    return {
        "by_population_namespace_role": by_namespace_role,
        # Historical key retained, but each row remains fully namespaced.
        "by_dataset_role": by_namespace_role,
        "support_resistance_balance": balance,
        "complementary_role_coverage": coverage,
    }


def _outcome_evidence_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[tuple[Any, ...], str, int], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(
            (
                _row_population_namespace(row),
                str(row["semantic_role_at_selection"]),
                int(row["horizon_hours"]),
            ),
            [],
        ).append(row)
    summary: list[dict[str, Any]] = []
    for (namespace, role, horizon), selected in sorted(
        groups.items(),
        key=lambda item: (_namespace_sort_key(item[0][0]), item[0][1], item[0][2]),
    ):
        dataset_id = str(namespace[-1])
        outcomes = [row.get("outcome", {}) for row in selected]
        result: dict[str, Any] = {
            "population_namespace": list(namespace),
            "dataset_id": dataset_id,
            "timeframe": dataset_id.rsplit("_", 1)[1],
            "role": role,
            "horizon_hours": horizon,
            "joined_row_count": len(selected),
        }
        for field, label in (
            ("survival", "survival"),
            ("zone_contact", "contact"),
            ("post_contact_reaction", "reaction"),
        ):
            values = [
                item.get(field)
                for item in outcomes
                if item.get("evaluable") is True and item.get(field) is not None
            ]
            result[f"{label}_denominator"] = len(values)
            result[f"{label}_count"] = sum(bool(value) for value in values)
            result[f"{label}_rate"] = (
                result[f"{label}_count"] / len(values) if values else None
            )
        contact_survival = [
            item
            for item in outcomes
            if item.get("evaluable") is True
            and item.get("zone_contact") is not None
            and item.get("survival") is not None
        ]
        result["contact_and_survival_denominator"] = len(contact_survival)
        result["contact_and_survival_count"] = sum(
            bool(item["zone_contact"]) and bool(item["survival"])
            for item in contact_survival
        )
        result["contact_and_survival_rate"] = (
            result["contact_and_survival_count"] / len(contact_survival)
            if contact_survival
            else None
        )
        result["evaluable_count"] = sum(item.get("evaluable") is True for item in outcomes)
        result["not_evaluable_count"] = len(outcomes) - result["evaluable_count"]
        summary.append(result)
    return summary


def _selection_evidence_summary(
    features: Sequence[Mapping[str, Any]],
    source_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[tuple[tuple[Any, ...], str], list[Mapping[str, Any]]] = {}
    for row in features:
        grouped.setdefault(
            (_row_population_namespace(row), str(row["semantic_role_at_selection"])),
            [],
        ).append(row)
    rows: list[dict[str, Any]] = []
    for (namespace, role), namespace_rows in sorted(
        grouped.items(), key=lambda item: (_namespace_sort_key(item[0][0]), item[0][1])
    ):
        unique_rows = {_safe_feature_key(row): row for row in namespace_rows}
        primary_rows = {
            key: row for key, row in unique_rows.items() if _primary_row(row)
        }
        dataset_id = str(namespace[-1])
        # Incumbent retention remains separate audit evidence. It is not the
        # R4 compression-retention numerator.
        retained_count = 0
        for record in source_evidence[dataset_id]["checkpoint_selection"].get("records", []):
            if not isinstance(record, Mapping):
                continue
            record_namespace = _selection_namespace(record)
            if record_namespace is None or record.get("budget_per_role") not in BUDGETS:
                continue
            record_key = (
                record_namespace["contender_policy_id"],
                record["budget_per_role"],
                record_namespace["derivation_type"],
                record_namespace["control_policy_id_or_null"],
                dataset_id,
            )
            if record_key == namespace:
                retained_count += len(record.get("retained_incumbent_ids", []))
        denominator = len(unique_rows)
        numerator = len(primary_rows)
        rows.append(
            {
                "population_namespace": list(namespace),
                "dataset_id": dataset_id,
                "timeframe": dataset_id.rsplit("_", 1)[1],
                "role": role,
                "candidate_feature_count": len(namespace_rows),
                "selected_line_count": denominator,
                "primary_96h_selected_line_count": numerator,
                "compression_retention_numerator": numerator,
                "compression_retention_denominator": denominator,
                "compression_retention_ratio": numerator / denominator if denominator else None,
                "incumbent_retained_line_count": retained_count,
            }
        )
    return {"by_population_namespace_role": rows, "by_dataset": rows}


def _structural_evidence_summary(
    source_evidence: Mapping[str, Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    actionable_states = {"STRICT_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR", "REVERSED_ACTIVE_NEAR"}
    structural_states = {"PERSISTED_DISTANT", "REVERSED_PERSISTED_DISTANT"}
    for dataset_id in DATASETS:
        structural = source_evidence[dataset_id]["structural_context"]
        outcomes = structural.get("outcome_records", [])
        outcome_summary: list[dict[str, Any]] = []
        for role in ROLES:
            for horizon in HORIZONS_HOURS:
                selected = [
                    row
                    for row in outcomes
                    if isinstance(row, Mapping)
                    and row.get("semantic_role_at_selection") == role
                    and row.get("horizon_hours") == horizon
                ]
                evaluable = [row for row in selected if row.get("evaluable") is True]
                outcome_summary.append(
                    {
                        "role": role,
                        "horizon_hours": horizon,
                        "structural_contact_denominator": len(evaluable),
                        "structural_contact_count": sum(bool(row.get("future_contact")) for row in evaluable),
                        "crossed_within_8_atr_count": sum(
                            bool(row.get("crossed_into_at_most_8_atr")) for row in evaluable
                        ),
                        "minimum_future_distance_distribution": _numeric_distribution(
                            [
                                float(row["minimum_future_distance_atr"])
                                for row in evaluable
                                if row.get("minimum_future_distance_atr") is not None
                            ]
                        ),
                        "distance_contraction_distribution": _numeric_distribution(
                            [
                                float(row["distance_contraction_atr"])
                                for row in evaluable
                                if row.get("distance_contraction_atr") is not None
                            ]
                        ),
                    }
                )
        actionable: set[tuple[str, int, str, str]] = {
            (
                str(row["dataset_id"]),
                int(row["checkpoint_index"]),
                str(row["semantic_role_at_selection"]),
                str(row["lineage_id"]),
            )
            for row in features
            if row.get("dataset_id") == dataset_id
            and row.get("derivation_type") == "contender"
            and row.get("state") in actionable_states
            and isinstance(row.get("lineage_id"), str)
        }
        structural_only: set[tuple[str, int, str, str]] = set()
        for record in structural.get("selection_records", []):
            if not isinstance(record, Mapping):
                continue
            for role in ROLES:
                for row in record.get("selected_rows", {}).get(role, []):
                    if not isinstance(row, Mapping) or not isinstance(row.get("lineage_id"), str):
                        continue
                    if row.get("state") in structural_states:
                        structural_only.add(
                            (
                                dataset_id,
                                int(record["checkpoint_index"]),
                                role,
                                row["lineage_id"],
                            )
                        )
        overlap = sorted(actionable & structural_only)
        result[dataset_id] = {
            "selection_record_count": len(structural.get("selection_records", [])),
            "outcome_record_count": len(outcomes),
            "outcome_summary": outcome_summary,
            "lineage_overlap_audit": {
                "actionable_lineage_count": len({identity[-1] for identity in actionable}),
                "structural_lineage_count": len({identity[-1] for identity in structural_only}),
                "overlap_lineage_count": len({identity[-1] for identity in overlap}),
                "overlap_lineage_ids": sorted({identity[-1] for identity in overlap}),
                "actionable_identity_count": len(actionable),
                "structural_identity_count": len(structural_only),
                "exact_identity_intersection_count": len(overlap),
                "actionable_identity_tuples": [list(identity) for identity in sorted(actionable)],
                "structural_identity_tuples": [list(identity) for identity in sorted(structural_only)],
                "exact_identity_intersection_tuples": [list(identity) for identity in overlap],
                "exact_identity_fields": ["dataset_id", "checkpoint_index", "semantic_role_at_selection", "lineage_id"],
            },
        }
    return result


def _derive_cell_reconciliation(
    raw_rows: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
    outcome_records: Sequence[Mapping[str, Any]],
) -> dict[tuple[Any, ...], set[str]]:
    """Attach every identity, geometry, and outcome error to one source cell."""
    errors: dict[tuple[Any, ...], set[str]] = {}

    def add(row: Mapping[str, Any], reason: str) -> None:
        try:
            errors.setdefault(_namespace_cell_key(row), set()).add(reason)
        except (KeyError, TypeError):
            # Malformed rows remain represented by dataset-level unresolved
            # evidence; no fabricated cell key is created.
            return

    seen_features: set[tuple[Any, ...]] = set()
    for row in raw_rows:
        try:
            key = _feature_key(row)
        except (KeyError, TypeError):
            continue
        if key in seen_features:
            add(row, "duplicate_feature_identity")
        seen_features.add(key)
    for row in features:
        if row.get("geometry_evaluable") is not True:
            add(row, "invalid_geometry_or_origin")

    outcome_index: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for outcome in outcome_records:
        if not isinstance(outcome, Mapping):
            continue
        if outcome.get("derivation_type") not in ("contender", "matched_control"):
            continue
        try:
            key = _outcome_key(outcome)
        except (KeyError, TypeError):
            continue
        if key in outcome_index:
            add(outcome, "duplicate_outcome_identity")
            continue
        outcome_index[key] = outcome

    expected: set[tuple[Any, ...]] = set()
    for feature in features:
        for horizon in HORIZONS_HOURS:
            key = (
                *_row_population_namespace(feature),
                feature["checkpoint_index"],
                feature["semantic_role_at_selection"],
                feature["lineage_id"],
                horizon,
            )
            expected.add(key)
            outcome = outcome_index.get(key)
            if outcome is None:
                add(feature, "missing_outcome")
            elif outcome.get("selection_id") != feature.get("selection_id"):
                add(feature, "outcome_identity_mismatch")
    for key, outcome in outcome_index.items():
        if key in expected:
            continue
        try:
            add(
                {
                    "population_namespace": list(key[:5]),
                    "dataset_id": key[4],
                    "checkpoint_index": key[5],
                    "semantic_role_at_selection": key[6],
                },
                "orphan_outcome",
            )
        except (IndexError, TypeError):
            continue
    return errors


def _build_pair_comparison(
    *,
    contender: str,
    budget: int,
    control: str,
    dataset_id: str,
    role: str,
    rows: Sequence[Mapping[str, Any]] = (),
    source_cells: Mapping[tuple[Any, ...], Mapping[str, Any]],
    source_errors: Sequence[str],
    feature_rows: Sequence[Mapping[str, Any]] | None = None,
    outcome_rows: Sequence[Mapping[str, Any]] | None = None,
    cell_reconciliation: Mapping[tuple[Any, ...], set[str]] | None = None,
) -> dict[str, Any]:
    feature_rows = rows if feature_rows is None else feature_rows
    outcome_rows = rows if outcome_rows is None else outcome_rows
    cell_reconciliation = cell_reconciliation or {}
    counts = {
        "eligible_cells": 0,
        "paired_cells": 0,
        "contender_only_cells": 0,
        "control_only_cells": 0,
        "empty_both_cells": 0,
        "duplicate_cells": 0,
        "unresolved_cells": len(source_errors),
    }
    deltas: list[float] = []
    cell_records: list[dict[str, Any]] = []
    expected_source_keys: set[tuple[Any, ...]] = set()
    for checkpoint in range(1, 23):
        source_key = (contender, budget, "contender", None, dataset_id, checkpoint)
        control_key = (contender, budget, "matched_control", control, dataset_id, checkpoint)
        expected_source_keys.update((source_key, control_key))
        contender_source = source_cells.get(source_key)
        control_source = source_cells.get(control_key)
        cell_errors: set[str] = set()
        for source in (contender_source, control_source):
            if source is not None:
                cell_errors.update(source.get("reconciliation_errors", []))
                if source.get("duplicate"):
                    cell_errors.add("duplicate_source_membership")
        for namespace in (
            (contender, budget, "contender", None, dataset_id),
            (contender, budget, "matched_control", control, dataset_id),
        ):
            cell_errors.update(
                cell_reconciliation.get((*namespace, checkpoint, role), set())
            )
        if contender_source is not None and control_source is not None:
            eligible = (
                contender_source["counts"].get(role, 0) > 0
                and control_source["counts"].get(role, 0) > 0
            )
            counts["eligible_cells"] += int(eligible)
            if contender_source["counts"].get(role) != control_source["counts"].get(role):
                cell_errors.add("source_count_mismatch")
        else:
            eligible = False
        if contender_source is None or control_source is None:
            cell_errors.add("missing_source_membership")
        contender_rows = [
            row
            for row in feature_rows
            if row["contender_policy_id"] == contender
            and row["budget_per_role"] == budget
            and row["derivation_type"] == "contender"
            and row["control_policy_id_or_null"] is None
            and row["dataset_id"] == dataset_id
            and row["checkpoint_index"] == checkpoint
            and row["semantic_role_at_selection"] == role
        ]
        control_rows = [
            row
            for row in feature_rows
            if row["contender_policy_id"] == contender
            and row["budget_per_role"] == budget
            and row["derivation_type"] == "matched_control"
            and row["control_policy_id_or_null"] == control
            and row["dataset_id"] == dataset_id
            and row["checkpoint_index"] == checkpoint
            and row["semantic_role_at_selection"] == role
        ]
        contender_feature_keys = [_safe_feature_key(row) for row in contender_rows]
        control_feature_keys = [_safe_feature_key(row) for row in control_rows]
        if len(set(contender_feature_keys)) != len(contender_feature_keys):
            cell_errors.add("duplicate_contender_identity")
        if len(set(control_feature_keys)) != len(control_feature_keys):
            cell_errors.add("duplicate_control_identity")
        contender_primary = [row for row in contender_rows if _primary_row(row)]
        control_primary = [row for row in control_rows if _primary_row(row)]
        contender_outcomes = [
            row
            for row in outcome_rows
            if row["contender_policy_id"] == contender
            and row["budget_per_role"] == budget
            and row["derivation_type"] == "contender"
            and row["control_policy_id_or_null"] is None
            and row["dataset_id"] == dataset_id
            and row["checkpoint_index"] == checkpoint
            and row["semantic_role_at_selection"] == role
            and row["horizon_hours"] == PRIMARY_HORIZON_HOURS
        ]
        control_outcomes = [
            row
            for row in outcome_rows
            if row["contender_policy_id"] == contender
            and row["budget_per_role"] == budget
            and row["derivation_type"] == "matched_control"
            and row["control_policy_id_or_null"] == control
            and row["dataset_id"] == dataset_id
            and row["checkpoint_index"] == checkpoint
            and row["semantic_role_at_selection"] == role
            and row["horizon_hours"] == PRIMARY_HORIZON_HOURS
        ]
        contender_primary_outcomes = [
            row for row in contender_outcomes if _primary_row(row)
        ]
        control_primary_outcomes = [
            row for row in control_outcomes if _primary_row(row)
        ]
        if len({_safe_outcome_key(row) for row in contender_outcomes}) != len(contender_outcomes):
            cell_errors.add("duplicate_contender_outcome_identity")
        if len({_safe_outcome_key(row) for row in control_outcomes}) != len(control_outcomes):
            cell_errors.add("duplicate_control_outcome_identity")
        contender_mean = _mean_outcome(contender_primary_outcomes, "survival")
        control_mean = _mean_outcome(control_primary_outcomes, "survival")
        if contender_primary and contender_mean is None:
            cell_errors.add("missing_outcome")
        if control_primary and control_mean is None:
            cell_errors.add("missing_outcome")
        duplicate = any(reason.startswith("duplicate_") for reason in cell_errors)
        unresolved = bool(cell_errors.intersection(
            {
                "missing_source_membership",
                "source_count_mismatch",
                "invalid_geometry_or_origin",
                "missing_outcome",
                "outcome_identity_mismatch",
                "orphan_outcome",
            }
        ))
        primary_class = classify_stratum_cell(contender_primary, control_primary)
        terminal_class = classify_stratum_cell(
            contender_primary,
            control_primary,
            duplicate=duplicate,
            unresolved=unresolved,
        )
        # Primary membership is causal and must not change when outcome rows
        # are removed. Integrity flags are reported alongside it.
        counts[f"{primary_class}_cells"] += 1
        if duplicate:
            counts["duplicate_cells"] += 1
        if unresolved:
            counts["unresolved_cells"] += 1
        cell_delta = None
        if terminal_class == "paired":
            if contender_mean is None or control_mean is None:
                counts["unresolved_cells"] += 1
            else:
                cell_delta = contender_mean - control_mean
                deltas.append(cell_delta)
        cell_records.append(
            {
                "checkpoint_index": checkpoint,
                "role": role,
                "status": "MATCHED_WITHIN_STRATUM" if terminal_class == "paired" else "DESCRIPTIVE_UNMATCHED",
                "primary_stratum_class": primary_class,
                "terminal_cell_class": terminal_class,
                "eligible": eligible,
                "contender_primary_count": len(contender_primary),
                "control_primary_count": len(control_primary),
                "contender_survival_mean": contender_mean,
                "control_survival_mean": control_mean,
                "survival_delta_96h": cell_delta,
                "denominator": {
                    "contender_rows": len(contender_primary),
                    "control_rows": len(control_primary),
                },
                "reconciliation_errors": sorted(cell_errors),
            }
        )
    # Source index may contain an unexpected valid cell outside fixed 22 checkpoints.
    if any(key not in expected_source_keys for key in source_cells):
        counts["unresolved_cells"] += 1
    matched = matched_within_stratum(
        counts,
        accounting_valid=counts["unresolved_cells"] == 0,
    )
    return {
        "population_namespace": [contender, budget, "matched_control", control, dataset_id],
        "role": role,
        "horizon_hours": PRIMARY_HORIZON_HOURS,
        **counts,
        "matched": matched,
        "status": "MATCHED_WITHIN_STRATUM" if matched else "DESCRIPTIVE_UNMATCHED",
        "survival_delta_96h": None if not deltas else sum(deltas) / len(deltas),
        "paired_cell_delta_count": len(deltas),
        "cells": cell_records,
    }


def _refresh_analysis_identity(analysis: dict[str, Any]) -> dict[str, Any]:
    source_binding = analysis["source_binding"]
    source_binding_payload = {
        key: value for key, value in source_binding.items() if key != "source_binding_id"
    }
    source_binding["source_binding_id"] = _identity_hash(
        "trendline_v2_phase11r4_source_binding", source_binding_payload
    )
    diagnostic_payload = {
        key: value for key, value in analysis.items() if key != "diagnostic_id"
    }
    analysis["diagnostic_id"] = _identity_hash(
        "trendline_v2_phase11r4_diagnostic", diagnostic_payload
    )
    return analysis


def build_analysis(verified: VerifiedSources) -> dict[str, Any]:
    """Derive complete deterministic diagnostic evidence from verified sources."""
    all_rows: list[dict[str, Any]] = []
    all_outcome_rows: list[dict[str, Any]] = []
    all_errors: list[str] = []
    source_cells_by_dataset: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    feature_rows_by_dataset: dict[str, list[dict[str, Any]]] = {}
    outcome_rows_by_dataset: dict[str, list[dict[str, Any]]] = {}
    cell_reconciliation_by_dataset: dict[str, dict[tuple[Any, ...], set[str]]] = {}
    source_evidence: dict[str, dict[str, Any]] = {}
    for dataset_id in DATASETS:
        dataset_root = verified.temporal_root / "datasets" / dataset_id
        selection_payload = _read_json(dataset_root / "checkpoint_selection.json")
        outcome_payload = _read_json(dataset_root / "candidate_outcomes.json")
        structural_payload = _read_json(dataset_root / "structural_context.json")
        metrics_payload = _read_json(dataset_root / "policy_metrics.json")
        dataset_errors: list[str] = []
        if not isinstance(selection_payload, Mapping):
            dataset_errors.append("selection payload is invalid")
            selection_payload = {}
        if not isinstance(outcome_payload, Mapping):
            dataset_errors.append("outcome payload is invalid")
            outcome_payload = {}
        if not isinstance(structural_payload, Mapping):
            dataset_errors.append("structural context payload is invalid")
            structural_payload = {}
        if not isinstance(metrics_payload, Mapping):
            dataset_errors.append("policy metrics payload is invalid")
            metrics_payload = {}
        if not isinstance(selection_payload.get("records"), list):
            dataset_errors.append("selection records are not a list")
        if not isinstance(structural_payload.get("selection_records"), list):
            dataset_errors.append("structural selection records are not a list")
        if not isinstance(structural_payload.get("outcome_records"), list):
            dataset_errors.append("structural outcome records are not a list")
        if not isinstance(metrics_payload.get("metrics"), Mapping):
            dataset_errors.append("policy metrics are not an object")
        source_evidence[dataset_id] = {
            "checkpoint_selection": dict(selection_payload),
            "candidate_outcomes": dict(outcome_payload),
            "structural_context": dict(structural_payload),
            "policy_metrics": dict(metrics_payload),
        }
        if isinstance(selection_payload.get("records"), list):
            source_cells, cell_errors = _selection_cell_index(dataset_id, selection_payload)
            rows, row_errors = iter_primary_selection_rows(dataset_id, selection_payload)
        else:
            source_cells, cell_errors = {}, []
            rows, row_errors = [], []
        source_cells_by_dataset[dataset_id] = source_cells
        dataset_errors.extend(cell_errors)
        dataset_errors.extend(row_errors)
        features, feature_errors = build_feature_rows(rows, verified.raw_datasets)
        dataset_errors.extend(feature_errors)
        outcome_records = outcome_payload.get("records", [])
        if not isinstance(outcome_records, list):
            dataset_errors.append("outcome records are not a list")
            outcome_records = []
        joined, outcome_errors = join_horizon_outcomes(features, outcome_records)
        dataset_errors.extend(outcome_errors)
        feature_rows_by_dataset[dataset_id] = features
        outcome_rows_by_dataset[dataset_id] = joined
        cell_reconciliation_by_dataset[dataset_id] = _derive_cell_reconciliation(
            rows,
            features,
            outcome_records,
        )
        all_errors.extend(dataset_errors)
        all_outcome_rows.extend(joined)
        all_rows.extend(features)

    comparisons: list[dict[str, Any]] = []
    for contender in CONTENDERS:
        for budget in BUDGETS:
            for control in CONTROLS:
                for dataset_id in DATASETS:
                    dataset_cells = {
                        key: value
                        for key, value in source_cells_by_dataset[dataset_id].items()
                        if key[0] == contender
                        and key[1] == budget
                        and key[2] in ("contender", "matched_control")
                        and (key[2] == "contender" or key[3] == control)
                    }
                    dataset_features = feature_rows_by_dataset[dataset_id]
                    dataset_outcomes = outcome_rows_by_dataset[dataset_id]
                    for role in ROLES:
                        comparisons.append(
                            _build_pair_comparison(
                                contender=contender,
                                budget=budget,
                                control=control,
                                dataset_id=dataset_id,
                                role=role,
                                feature_rows=dataset_features,
                                outcome_rows=dataset_outcomes,
                                source_cells=dataset_cells,
                                source_errors=(),
                                cell_reconciliation=cell_reconciliation_by_dataset[dataset_id],
                            )
                        )

    feature_summary = _feature_evidence_summary(all_rows)
    outcome_summary = _outcome_evidence_summary(all_outcome_rows)
    selection_summary = _selection_evidence_summary(all_rows, source_evidence)
    structural_summary = _structural_evidence_summary(source_evidence, all_rows)
    source_snapshot = {
        "temporal": verified.temporal_snapshot,
        "raw": verified.raw_snapshot,
    }
    analysis = {
        "schema_version": "trendline_v2_phase11r4_causal_structural_reachability_v1",
        "status": None,
        "diagnostic_decision": None,
        "primary_hypothesis": {
            "id": "H_R4_GEOMETRY_PROJECTED_96H_WITHIN_8_ATR_V1",
            "feature": "geometry_projected_distance_atr_96h",
            "criterion": "<= 8.0",
            "horizon_hours": PRIMARY_HORIZON_HOURS,
        },
        "source_binding": {
            "schema_version": "trendline_v2_phase11r4_source_binding_v1",
            "source_before": source_snapshot,
            "source_after": source_snapshot,
        },
        "feature_row_count": len(all_rows),
        "horizon_outcome_row_count": len(all_outcome_rows),
        "feature_rows": all_rows,
        "causal_feature_identities": [
            row["causal_feature_observation_key"] for row in all_rows
        ],
        "feature_evidence": feature_summary,
        "selection_evidence": selection_summary,
        "outcome_evidence": outcome_summary,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "r3b_reference_metrics": {
            dataset_id: source_evidence[dataset_id]["policy_metrics"].get("metrics", {})
            for dataset_id in DATASETS
        },
        "structural_context_summary": structural_summary,
        "source_evidence": source_evidence,
        "unresolved_evidence_count": len(all_errors),
        "unresolved_reconciliation_count": len(all_errors),
        "unresolved_errors": sorted(set(all_errors)),
        "execution": {
            "provider_calls": 0,
            "network_calls": 0,
            "raw_sui_accesses": 0,
            "holdout_accesses": 0,
            "phase10c2_temporal_accesses": 0,
            "legacy_executions": 0,
        },
    }
    status, decision = decision_from_comparisons(
        comparisons,
        source_errors=len(all_errors),
    )
    analysis["status"] = status
    analysis["diagnostic_decision"] = decision
    if analysis["status"] == "R4_DIAGNOSTIC_COMPLETE" and analysis["unresolved_evidence_count"]:
        raise ReachabilityError("complete R4 diagnostic has unresolved evidence")
    return _refresh_analysis_identity(analysis)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


R4_ARTIFACT_PATHS = (
    "manifest.json",
    "reachability_diagnostic.json",
    "source_binding.json",
)
R4_MANIFEST_SCHEMA = "trendline_v2_phase11r4_manifest_v1"
R4_MANIFEST_NAMESPACE = "trendline_v2_phase11r4_manifest"


def _prepare_analysis_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ReachabilityError("R4 diagnostic payload is not an object")
    prepared = json.loads(_canonical_json(payload))
    source_binding = prepared.get("source_binding")
    if not isinstance(source_binding, Mapping):
        raise ReachabilityError("R4 source binding is missing")
    source_binding = dict(source_binding)
    source_binding_payload = {
        key: value for key, value in source_binding.items() if key != "source_binding_id"
    }
    source_binding_id = _identity_hash(
        "trendline_v2_phase11r4_source_binding", source_binding_payload
    )
    if (
        source_binding.get("source_binding_id") is not None
        and source_binding.get("source_binding_id") != source_binding_id
    ):
        raise ReachabilityError("R4 source binding identity mismatch")
    source_binding["source_binding_id"] = source_binding_id
    prepared["source_binding"] = source_binding
    diagnostic_payload = {
        key: value for key, value in prepared.items() if key != "diagnostic_id"
    }
    diagnostic_id = _identity_hash(
        "trendline_v2_phase11r4_diagnostic", diagnostic_payload
    )
    if (
        prepared.get("diagnostic_id") is not None
        and prepared.get("diagnostic_id") != diagnostic_id
    ):
        raise ReachabilityError("R4 diagnostic identity mismatch")
    prepared["diagnostic_id"] = diagnostic_id
    if (
        prepared.get("status") == "R4_DIAGNOSTIC_COMPLETE"
        and int(prepared.get("unresolved_evidence_count", 0)) != 0
    ):
        raise ReachabilityError("complete R4 diagnostic has unresolved evidence")
    if (
        prepared.get("status") == "R4_DIAGNOSTIC_COMPLETE"
        and int(prepared.get("unresolved_reconciliation_count", 0)) != 0
    ):
        raise ReachabilityError("complete R4 diagnostic has unresolved reconciliation")
    return prepared


def _render_bundle(payload: Mapping[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    prepared = _prepare_analysis_payload(payload)
    diagnostic_bytes = _canonical_bytes(prepared)
    source_binding_bytes = _canonical_bytes(prepared["source_binding"])
    members = [
        {
            "path": "reachability_diagnostic.json",
            "byte_length": len(diagnostic_bytes),
            "sha256": _sha256_bytes(diagnostic_bytes),
        },
        {
            "path": "source_binding.json",
            "byte_length": len(source_binding_bytes),
            "sha256": _sha256_bytes(source_binding_bytes),
        },
    ]
    manifest_payload = {
        "diagnostic_id": prepared["diagnostic_id"],
        "member_count": len(members),
        "members": members,
        "output_inventory_sha256": _inventory_sha256(members),
        "schema_version": R4_MANIFEST_SCHEMA,
        "source_binding_id": prepared["source_binding"]["source_binding_id"],
    }
    manifest = {
        **manifest_payload,
        "manifest_id": _identity_hash(R4_MANIFEST_NAMESPACE, manifest_payload),
    }
    return {
        "reachability_diagnostic.json": diagnostic_bytes,
        "source_binding.json": source_binding_bytes,
        "manifest.json": _canonical_bytes(manifest),
    }, manifest


def _write_bundle_files(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    rendered, manifest = _render_bundle(payload)
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in rendered.items():
        _atomic_write(root / relative, content)
    return manifest


def publish_bundle(output_root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Publish a complete content-addressed R4 bundle atomically."""
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        manifest = _write_bundle_files(staging, payload)
        candidate = {
            str(path.relative_to(staging)): _sha256_file(path)
            for path in staging.rglob("*")
            if path.is_file()
        }
        if output_root.exists():
            existing = {
                str(path.relative_to(output_root)): _sha256_file(path)
                for path in output_root.rglob("*")
                if path.is_file()
            }
            if existing != candidate:
                raise ReachabilityError("refusing non-identical bundle overwrite")
            return manifest
        os.replace(staging, output_root)
        staging = None  # type: ignore[assignment]
        return manifest
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def verify_reachability_bundle(
    root: Path,
    *,
    source_backed: bool = True,
    expected_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify exact R4 bytes and rederive source-backed evidence."""
    actual_inventory = _artifact_inventory(root, include_manifest=True)
    if {item["path"] for item in actual_inventory} != set(R4_ARTIFACT_PATHS):
        raise ReachabilityError("R4 bundle paths are not exact")
    diagnostic = _read_canonical_json(root / "reachability_diagnostic.json")
    source_binding = _read_canonical_json(root / "source_binding.json")
    manifest = _read_canonical_json(root / "manifest.json")
    source_binding_payload = {
        key: value for key, value in source_binding.items() if key != "source_binding_id"
    }
    if source_binding.get("source_binding_id") != _identity_hash(
        "trendline_v2_phase11r4_source_binding", source_binding_payload
    ):
        raise ReachabilityError("R4 source binding identity mismatch")
    if diagnostic.get("source_binding") != source_binding:
        raise ReachabilityError("R4 diagnostic/source binding mismatch")
    diagnostic_payload = {
        key: value for key, value in diagnostic.items() if key != "diagnostic_id"
    }
    if diagnostic.get("diagnostic_id") != _identity_hash(
        "trendline_v2_phase11r4_diagnostic", diagnostic_payload
    ):
        raise ReachabilityError("R4 diagnostic identity mismatch")
    manifest_payload = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    if manifest.get("manifest_id") != _identity_hash(
        R4_MANIFEST_NAMESPACE, manifest_payload
    ):
        raise ReachabilityError("R4 manifest identity mismatch")
    actual_members = tuple(item for item in actual_inventory if item["path"] != "manifest.json")
    if tuple(manifest.get("members", [])) != actual_members:
        raise ReachabilityError("R4 manifest members do not match bytes")
    if manifest.get("member_count") != len(actual_members):
        raise ReachabilityError("R4 manifest member count mismatch")
    if manifest.get("output_inventory_sha256") != _inventory_sha256(actual_members):
        raise ReachabilityError("R4 output inventory mismatch")
    if (
        manifest.get("diagnostic_id") != diagnostic.get("diagnostic_id")
        or manifest.get("source_binding_id") != source_binding.get("source_binding_id")
    ):
        raise ReachabilityError("R4 manifest cross-binding mismatch")

    if source_backed:
        verified_before = verify_sources()
        expected_evidence = build_analysis(verified_before)
        verified_after = verify_sources()
        if (
            verified_before.temporal_snapshot != verified_after.temporal_snapshot
            or verified_before.raw_snapshot != verified_after.raw_snapshot
        ):
            raise ReachabilityError("source mutation during R4 bundle verification")
    elif expected_evidence is None:
        raise ReachabilityError("synthetic verification requires expected evidence")
    expected_rendered, expected_manifest = _render_bundle(expected_evidence)
    for relative, expected_bytes in expected_rendered.items():
        if (root / relative).read_bytes() != expected_bytes:
            raise ReachabilityError(f"source-derived R4 artifact mismatch: {relative}")
    if manifest != expected_manifest:
        raise ReachabilityError("source-derived R4 manifest mismatch")
    return {
        "status": diagnostic.get("status"),
        "diagnostic_id": diagnostic["diagnostic_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "member_count": manifest["member_count"],
        "unresolved_evidence_count": diagnostic.get("unresolved_evidence_count"),
    }


def execute_reachability_study(
    *,
    temporal_root: Path = TEMPORAL_V2_ROOT,
    raw_root: Path = RAW_SOURCE_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if os.environ.get(EXECUTION_GUARD) != "1":
        raise ReachabilityError(f"missing execution guard: {EXECUTION_GUARD}=1")
    if output_root.exists():
        raise ReachabilityError("R4 output already exists; refusing rerun")
    source_before = verify_sources(temporal_root, raw_root)
    analysis = build_analysis(source_before)
    source_after = verify_sources(temporal_root, raw_root)
    if (
        source_before.temporal_snapshot != source_after.temporal_snapshot
        or source_before.raw_snapshot != source_after.raw_snapshot
    ):
        raise ReachabilityError("source mutation detected between R4 snapshots")
    analysis["source_binding"]["source_after"] = {
        "temporal": source_after.temporal_snapshot,
        "raw": source_after.raw_snapshot,
    }
    analysis = _refresh_analysis_identity(analysis)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        _write_bundle_files(staging, analysis)
        verify_reachability_bundle(staging, source_backed=True)
        if output_root.exists():
            raise ReachabilityError("R4 output appeared during execution")
        os.replace(staging, output_root)
        staging = None  # type: ignore[assignment]
        return verify_reachability_bundle(output_root, source_backed=True)
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-reachability-study", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.execute_reachability_study:
        execute_reachability_study()
        return 0
    if args.verify:
        if OUTPUT_ROOT.exists():
            print(json.dumps(verify_reachability_bundle(OUTPUT_ROOT), sort_keys=True))
            return 0
        result = verify_sources()
        print(
            json.dumps(
                {
                    "status": "R4_SOURCE_BINDING_VERIFIED",
                    "temporal_inventory": result.temporal_snapshot["inventory"],
                    "raw_inventory": result.raw_snapshot["aggregate_inventory"],
                },
                sort_keys=True,
            )
        )
        return 0
    parser.error("select --verify or --execute-reachability-study")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
