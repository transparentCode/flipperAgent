"""Replay Trendline V2 exact lineage across a rolling provider lookback.

This is a bounded research/evidence boundary.  The only executable model path
is the committed public discovery, selection and tracking API.  Verification
reconstructs the same typed values from persisted bytes and never calls a
provider.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
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
    ProviderDiagnostics,
    ProviderInput,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
)
from libs.models.trendline_v2.domain.candidates import AnchorRef, LineCandidate
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.snapshots import DiscoverySnapshot
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
from scripts import freeze_trendline_v2_long_horizon_source as phase10c1


UTC = timezone.utc
NANOSECONDS = 1_000_000_000
INTERVAL_SECONDS = 14_400

SOURCE_ROOT = Path("/tmp/trendline_v2_phase10c1_long_horizon_source/20250801_20260401")
OUTPUT_ROOT = Path("/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401")
NETWORK_ENV = "TRENDLINE_V2_ALLOW_PHASE10C2_PROVIDER_REPLAY"

ASSET = "BTCUSDT"
TIMEFRAME = "4h"
LOOKBACK_SECONDS = 10_540_800
EFFECTIVE_ROWS = 732
LEFT_CONFIRMATION_BARS = 1
REMOVAL_CAUSES = (
    "first_anchor_evicted",
    "first_anchor_left_context_evicted",
)

STUDY_SCHEMA = "trendline_v2_phase_10c2_lookback_eviction_replay_v1"
REPLAY_CONTRACT_SCHEMA = "trendline_v2_phase_10c2_lookback_eviction_replay_v1_contract"
REPLAY_CONTRACT_NAMESPACE = "trendline_v2_phase_10c2_eviction_replay_contract"
REPLAY_CONTRACT_EXPECTED_ID = (
    "166b156a471f06dcc2d4fbf09196df95"
    "c4648e4b60cac52d1d315f7e7794af96"
)
SUPERSEDED_REPLAY_CONTRACT_ID = (
    "fe93c86fc67638e81219e68100ce7dde7d629db7f528073a0581fd5eda986314"
)
CHECKPOINT_SCHEMA = f"{STUDY_SCHEMA}_checkpoint"
SOURCE_AUDIT_SCHEMA = f"{STUDY_SCHEMA}_source_audit"
EXECUTION_AUDIT_SCHEMA = f"{STUDY_SCHEMA}_provider_execution_audit"
SUMMARY_SCHEMA = f"{STUDY_SCHEMA}_checkpoint_summary"
REMOVAL_SCHEMA = f"{STUDY_SCHEMA}_removal_attribution"
DECISION_SCHEMA = f"{STUDY_SCHEMA}_decision"
MANIFEST_SCHEMA = f"{STUDY_SCHEMA}_manifest"
DECISION_NAMESPACE = f"{STUDY_SCHEMA}_decision"
MANIFEST_NAMESPACE = f"{STUDY_SCHEMA}_manifest"
RESULT_ID_NAMESPACE = "trendline_v2_phase_9c2_provider_result_v1"

SOURCE_CONTRACT_ID = "136215cc9d14b471eac40439dad143987e1738ae4b7365307bc87a2f0c752eae"
SOURCE_INPUT_ID = "6397fc215f0c9d2fc7c6cdf1fe44e60e5530d7fef2c040cce2731661a5657a4c"
SOURCE_DECISION_ID = "086d502cf29ea0d41bae42ecf776749540750bce81bfafd129407a65909eab1a"
SOURCE_MANIFEST_ID = "5b8876f61aef2adcc00a0f3c4f22c6ee8bad83bc9bd27fd7ccff58c1fc8ff9a9"
SOURCE_INVENTORY_SHA256 = (
    "872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f"
)
FOUNDATION_CONFIG_ID = (
    "02cdb171472b8ede327c2466c08ce295d72b16e34367047928757f80fd4f8396"
)
PROVIDER_CONFIG_ID = "2aea7331fad4032db1803f21faa2df42fb2142f365331edce0723db5c55a2e6c"
COMBINED_CONFIG_ID = "7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636"
PROVIDER_CONTRACT_ID = (
    "13828b02b649fc002681137bae82761d91283e8d1f19d3a3fbd719b8f1cf0e99"
)
SELECTION_POLICY_ID = "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
TRACKING_POLICY_ID = "82c026cadb53acd15f78e61e4773ff836574802dd0b82f130a80af32ee9353ce"


class ReplayError(RuntimeError):
    """Expected bounded replay or artifact verification failure."""


class ReplayScopeBlocked(ReplayError):
    """The fixed replay cannot be completed safely."""

    def __init__(
        self,
        failure_code: str,
        *,
        checkpoint_index: int | None = None,
        family_id: str | None = None,
        first_anchor_timestamp: datetime | None = None,
        first_anchor_required_history_start: datetime | None = None,
        previous_effective_window_start: datetime | None = None,
        current_effective_window_start: datetime | None = None,
    ) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.checkpoint_index = checkpoint_index
        self.family_id = family_id
        self.first_anchor_timestamp = first_anchor_timestamp
        self.first_anchor_required_history_start = first_anchor_required_history_start
        self.previous_effective_window_start = previous_effective_window_start
        self.current_effective_window_start = current_effective_window_start


@dataclass(slots=True)
class ReplayExecutionState:
    completed_provider_execution_count: int = 0
    current_checkpoint_index: int | None = None
    previous_effective_window_start: datetime | None = None
    current_effective_window_start: datetime | None = None
    network_request_count: int = 0
    retry_count: int = 0
    fallback_count: int = 0


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    index: int
    observed_at: datetime
    prefix_rows: int
    effective_window_start: datetime


CHECKPOINTS = (
    CheckpointSpec(
        1,
        datetime(2025, 12, 1, tzinfo=UTC),
        732,
        datetime(2025, 8, 1, tzinfo=UTC),
    ),
    CheckpointSpec(
        2,
        datetime(2026, 1, 1, tzinfo=UTC),
        918,
        datetime(2025, 9, 1, tzinfo=UTC),
    ),
    CheckpointSpec(
        3,
        datetime(2026, 2, 1, tzinfo=UTC),
        1_104,
        datetime(2025, 10, 2, tzinfo=UTC),
    ),
    CheckpointSpec(
        4,
        datetime(2026, 3, 1, tzinfo=UTC),
        1_272,
        datetime(2025, 10, 30, tzinfo=UTC),
    ),
    CheckpointSpec(
        5,
        datetime(2026, 4, 1, tzinfo=UTC),
        1_458,
        datetime(2025, 11, 30, tzinfo=UTC),
    ),
)


@dataclass(frozen=True, slots=True)
class EffectiveWindow:
    start: datetime
    end: datetime
    row_count: int
    first_timestamp: datetime
    last_timestamp: datetime


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    checkpoint: CheckpointSpec
    prefix_input: ProviderInput
    effective_window: EffectiveWindow
    provider_result: ProviderResult
    discovery_snapshot: DiscoverySnapshot
    selection_snapshot: CandidateSelectionSnapshot
    tracking_snapshot: TrendlineTrackingSnapshot
    removal_attribution: tuple[dict[str, Any], ...]


ProviderCall = Callable[..., ProviderResult]


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _blocked_diagnostic_payload(
    error: ReplayScopeBlocked,
    *,
    execution_state: ReplayExecutionState | None = None,
) -> dict[str, Any]:
    state = execution_state or ReplayExecutionState()

    def iso_or_none(value: datetime | None) -> str | None:
        return _iso(value) if value is not None else None

    return {
        "study_status": "BLOCKED_PHASE_10C2_REPLAY",
        "replay_contract_id": REPLAY_CONTRACT_ID,
        "completed_provider_execution_count": state.completed_provider_execution_count,
        "failed_checkpoint_index": error.checkpoint_index
        if error.checkpoint_index is not None
        else state.current_checkpoint_index,
        "failure_code": error.failure_code,
        "family_id": error.family_id,
        "first_anchor_timestamp": iso_or_none(error.first_anchor_timestamp),
        "first_anchor_required_history_start": iso_or_none(
            error.first_anchor_required_history_start
        ),
        "previous_effective_window_start": iso_or_none(
            error.previous_effective_window_start
            or state.previous_effective_window_start
        ),
        "current_effective_window_start": iso_or_none(
            error.current_effective_window_start
            or state.current_effective_window_start
        ),
        "network_request_count": state.network_request_count,
        "retry_count": state.retry_count,
        "fallback_count": state.fallback_count,
    }


def _emit_blocked_diagnostic(
    error: ReplayScopeBlocked,
    *,
    execution_state: ReplayExecutionState | None = None,
) -> None:
    if getattr(error, "_diagnostic_emitted", False):
        return
    print(
        canonical_json(
            _blocked_diagnostic_payload(error, execution_state=execution_state)
        ),
        file=sys.stderr,
    )
    error._diagnostic_emitted = True


def _epoch_ns(value: datetime) -> int:
    return int(value.timestamp()) * NANOSECONDS


def _parse_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ReplayError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayError(f"invalid {field_name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


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
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ReplayError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise ReplayError(f"non-canonical JSON artifact: {path}")
    return value


def _write_atomic(path: Path, value: bytes) -> None:
    if path.exists():
        raise ReplayError(f"refusing existing output file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: object) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise ReplayError(f"output root is missing: {root}")
    result: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ReplayError(f"output member is a symlink: {path}")
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


def _fixed_configuration() -> tuple[
    ResolvedTrendlineV2Config,
    ConfirmedExtremaPairConfig,
    LatestValidPredecessorPolicy,
    ExactSelectedStructureTrackingPolicy,
]:
    config = resolve_trendline_v2_config(
        {
            "model": {
                "name": "trendline_v2",
                "version": "foundation_v1",
                "schema_version": 1,
            }
        }
    )
    provider_config = ConfirmedExtremaPairConfig(
        lookback_duration_seconds=LOOKBACK_SECONDS,
        left_confirmation_bars=LEFT_CONFIRMATION_BARS,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        max_hypotheses=100_000,
        max_output_candidates=10_000,
    )
    if (
        provider_config.left_confirmation_bars != LEFT_CONFIRMATION_BARS
        or provider_config.provider_contract_identity != PROVIDER_CONTRACT_ID
    ):
        raise ReplayError("fixed provider left-context identity drift")
    selection_policy = LatestValidPredecessorPolicy()
    tracking_policy = ExactSelectedStructureTrackingPolicy()
    identities = (
        config.semantic_hash,
        provider_config.semantic_hash,
        deterministic_hash(
            "trendline_v2_combined_configuration",
            {
                "foundation_config_identity": config.semantic_hash,
                "provider_config_identity": provider_config.semantic_hash,
            },
        ),
        provider_config.provider_contract_identity,
        selection_policy.policy_identity,
        tracking_policy.policy_identity,
    )
    expected = (
        FOUNDATION_CONFIG_ID,
        PROVIDER_CONFIG_ID,
        COMBINED_CONFIG_ID,
        PROVIDER_CONTRACT_ID,
        SELECTION_POLICY_ID,
        TRACKING_POLICY_ID,
    )
    if identities != expected:
        raise ReplayError("fixed configuration identity drift")
    return config, provider_config, selection_policy, tracking_policy


def _replay_contract_payload(
    *,
    checkpoints: Sequence[CheckpointSpec] = CHECKPOINTS,
    source_input_identity: str = SOURCE_INPUT_ID,
) -> dict[str, Any]:
    return {
        "schema_version": REPLAY_CONTRACT_SCHEMA,
        "source_contract_id": SOURCE_CONTRACT_ID,
        "source_input_identity": source_input_identity,
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "causal_prefix_rule": "timestamp < checkpoint",
        "provider_history_rule": "effective_window_start <= timestamp <= confirmed_through",
        "lookback_duration_seconds": LOOKBACK_SECONDS,
        "effective_row_count": EFFECTIVE_ROWS,
        "checkpoints": [
            {
                "checkpoint_index": item.index,
                "observed_at": _iso(item.observed_at),
                "prefix_row_count": item.prefix_rows,
                "effective_window_start": _iso(item.effective_window_start),
            }
            for item in checkpoints
        ],
        "execution_order": [item.index for item in checkpoints],
        "foundation_config_identity": FOUNDATION_CONFIG_ID,
        "provider_config_identity": PROVIDER_CONFIG_ID,
        "combined_config_identity": COMBINED_CONFIG_ID,
        "provider_contract_identity": PROVIDER_CONTRACT_ID,
        "selection_policy_identity": SELECTION_POLICY_ID,
        "tracking_policy_identity": TRACKING_POLICY_ID,
        "anchor_eligibility_context": {
            "left_confirmation_bars": LEFT_CONFIRMATION_BARS,
            "interval_seconds": INTERVAL_SECONDS,
            "required_history_start_rule": (
                "first_anchor_pivot_time - "
                "left_confirmation_bars * interval_seconds"
            ),
        },
        "removal_attribution_rule": (
            "previous_effective_window_start <= "
            "first_anchor_required_history_start < "
            "current_effective_window_start"
        ),
        "removal_cause_values": list(REMOVAL_CAUSES),
        "unattributed_removal_rule": "reject",
        "removed_family_reappearance_rule": "reject",
    }


def replay_contract_id(payload: Mapping[str, Any]) -> str:
    return deterministic_hash(REPLAY_CONTRACT_NAMESPACE, payload)


def _derive_replay_contract_id() -> str:
    identity = replay_contract_id(_replay_contract_payload())
    if identity != REPLAY_CONTRACT_EXPECTED_ID:
        raise ReplayError("replay contract identity drift")
    return identity


REPLAY_CONTRACT_ID = _derive_replay_contract_id()


def _replay_contract() -> dict[str, Any]:
    payload = _replay_contract_payload()
    identity = _derive_replay_contract_id()
    if identity != replay_contract_id(payload):
        raise ReplayError("replay contract payload drift")
    return {**payload, "contract_id": identity}


def _verify_source() -> tuple[dict[str, Any], ProviderInput]:
    verification = phase10c1.verify_bundle(output_root=SOURCE_ROOT)
    expected = {
        "source_contract_id": SOURCE_CONTRACT_ID,
        "provider_input_identity": SOURCE_INPUT_ID,
        "decision_id": SOURCE_DECISION_ID,
        "manifest_id": SOURCE_MANIFEST_ID,
        "output_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "row_count": 1_458,
        "network_request_count": 0,
        "provider_execution_count": 0,
    }
    actual = {
        "source_contract_id": verification.get("source_contract_id"),
        "provider_input_identity": verification.get("provider_input_identity"),
        "decision_id": verification.get("decision_id"),
        "manifest_id": verification.get("manifest_id"),
        "output_inventory_sha256": verification.get("output_inventory_sha256"),
        "row_count": verification.get("row_count"),
        "network_request_count": verification.get("network_request_count"),
        "provider_execution_count": verification.get("provider_execution_count"),
    }
    if actual != expected:
        raise ReplayError("Phase 10C.1 source identity drift")
    input_payload = phase10c1._load_json(SOURCE_ROOT / "provider_input.json")
    full_input = phase10c1._provider_input_from_dict(input_payload)
    if (
        full_input.asset != ASSET
        or full_input.timeframe != TIMEFRAME
        or full_input.row_count != 1_458
        or full_input.input_identity != SOURCE_INPUT_ID
    ):
        raise ReplayError("Phase 10C.1 ProviderInput binding drift")
    return verification, full_input


def _prefix_input(
    full_input: ProviderInput, checkpoint: CheckpointSpec
) -> ProviderInput:
    cutoff_ns = _epoch_ns(checkpoint.observed_at)
    indices = [
        index
        for index, timestamp in enumerate(full_input.timestamps)
        if timestamp < cutoff_ns
    ]
    if len(indices) != checkpoint.prefix_rows:
        raise ReplayScopeBlocked(
            f"prefix row count mismatch at checkpoint {checkpoint.index}"
        )
    if (
        not indices
        or full_input.timestamps[indices[-1]]
        != cutoff_ns - INTERVAL_SECONDS * NANOSECONDS
    ):
        raise ReplayScopeBlocked("causal prefix final timestamp mismatch")
    return ProviderInput(
        asset=full_input.asset,
        timeframe=full_input.timeframe,
        observed_at=checkpoint.observed_at,
        confirmed_through=checkpoint.observed_at,
        timestamps=tuple(full_input.timestamps[index] for index in indices),
        open=tuple(full_input.open[index] for index in indices),
        high=tuple(full_input.high[index] for index in indices),
        low=tuple(full_input.low[index] for index in indices),
        close=tuple(full_input.close[index] for index in indices),
        volume=tuple(full_input.volume[index] for index in indices),
    )


def _effective_window(
    prefix: ProviderInput, checkpoint: CheckpointSpec
) -> EffectiveWindow:
    start_ns = _epoch_ns(checkpoint.effective_window_start)
    end_ns = _epoch_ns(checkpoint.observed_at)
    indices = [
        index
        for index, timestamp in enumerate(prefix.timestamps)
        if start_ns <= timestamp <= end_ns
    ]
    if len(indices) != EFFECTIVE_ROWS:
        raise ReplayScopeBlocked("effective window row count mismatch")
    first = prefix.timestamps[indices[0]]
    last = prefix.timestamps[indices[-1]]
    if first != start_ns or last != end_ns - INTERVAL_SECONDS * NANOSECONDS:
        raise ReplayScopeBlocked("effective window boundary mismatch")
    return EffectiveWindow(
        start=checkpoint.effective_window_start,
        end=checkpoint.observed_at,
        row_count=len(indices),
        first_timestamp=datetime.fromtimestamp(first / NANOSECONDS, tz=UTC),
        last_timestamp=datetime.fromtimestamp(last / NANOSECONDS, tz=UTC),
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
    return ConfirmedOHLCVFrame.from_frame(
        frame,
        asset=input_data.asset,
        timeframe=input_data.timeframe,
        observed_at=input_data.observed_at,
        confirmed_through=input_data.confirmed_through,
    )


def _provider_result_id(result: ProviderResult) -> str:
    return deterministic_hash(RESULT_ID_NAMESPACE, result.to_dict())


def _execute_provider(
    prefix: ProviderInput,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    provider: ProviderCall,
    execution_state: ReplayExecutionState | None = None,
) -> ProviderResult:
    result = provider(
        _frame_for_input(prefix), config=config, provider_config=provider_config
    )
    if execution_state is not None:
        execution_state.completed_provider_execution_count += 1
    if not isinstance(result, ProviderResult):
        raise ReplayScopeBlocked("provider returned an invalid typed result")
    if result.status is not ProviderStatus.SUCCESS or result.reason is not None:
        raise ReplayScopeBlocked(
            "BLOCKED_PROVIDER_SCOPE: "
            f"status={result.status.value} reason={getattr(result.reason, 'value', result.reason)}"
        )
    if not result.candidates or len(result.candidates) > 10_000:
        raise ReplayScopeBlocked("BLOCKED_PROVIDER_SCOPE: invalid candidate count")
    if (
        result.request.input_data.to_dict() != prefix.to_dict()
        or result.request.config.semantic_hash != config.semantic_hash
        or result.request.provider_config.semantic_hash != provider_config.semantic_hash
        or result.request.asset != ASSET
        or result.request.timeframe != TIMEFRAME
        or len(result.candidates) != len(result.evidence)
    ):
        raise ReplayScopeBlocked("BLOCKED_PROVIDER_SCOPE: request binding mismatch")
    return result


def _first_anchor_required_history_start(first_anchor: AnchorRef) -> datetime:
    return first_anchor.pivot_time - timedelta(
        seconds=LEFT_CONFIRMATION_BARS * INTERVAL_SECONDS
    )


def _validate_active_anchor_window(
    anchors: Sequence[AnchorRef],
    *,
    window: EffectiveWindow,
    checkpoint: CheckpointSpec,
) -> None:
    if len(anchors) != 2:
        raise ReplayScopeBlocked("active family does not have two anchors")
    first_anchor, second_anchor = anchors
    required_history_start = _first_anchor_required_history_start(first_anchor)
    if (
        first_anchor.pivot_time < window.start
        or required_history_start < window.start
        or not first_anchor.pivot_time < second_anchor.pivot_time
    ):
        raise ReplayScopeBlocked("active family anchor is outside rolling window")
    if second_anchor.pivot_time >= checkpoint.observed_at:
        raise ReplayScopeBlocked("active family anchor is not causal")
    if any(anchor.confirmation_time > checkpoint.observed_at for anchor in anchors):
        raise ReplayScopeBlocked("active family anchor is unconfirmed")


def _validate_active_window(
    tracking: TrendlineTrackingSnapshot,
    window: EffectiveWindow,
    checkpoint: CheckpointSpec,
) -> None:
    for family in tracking.active_families:
        _validate_active_anchor_window(
            family.current_candidate.anchors,
            window=window,
            checkpoint=checkpoint,
        )


def _removal_attribution(
    *,
    family_id: str,
    role: str,
    first_anchor: AnchorRef,
    second_anchor: AnchorRef,
    previous_observed_at: datetime,
    checkpoint: CheckpointSpec,
    previous_window: EffectiveWindow,
    current_window: EffectiveWindow,
    current_family_ids: set[str],
) -> dict[str, Any]:
    required_history_start = _first_anchor_required_history_start(first_anchor)
    if not (
        previous_window.start
        <= required_history_start
        < current_window.start
        and first_anchor.pivot_time < second_anchor.pivot_time
        and second_anchor.pivot_time < checkpoint.observed_at
        and first_anchor.confirmation_time <= previous_observed_at
        and second_anchor.confirmation_time <= previous_observed_at
        and family_id not in current_family_ids
    ):
        raise ReplayScopeBlocked(
            "UNATTRIBUTED_SOURCE_REMOVAL",
            checkpoint_index=checkpoint.index,
            family_id=family_id,
            first_anchor_timestamp=first_anchor.pivot_time,
            first_anchor_required_history_start=required_history_start,
            previous_effective_window_start=previous_window.start,
            current_effective_window_start=current_window.start,
        )

    left_context_end = current_window.start + timedelta(
        seconds=LEFT_CONFIRMATION_BARS * INTERVAL_SECONDS
    )
    if first_anchor.pivot_time < current_window.start:
        removal_cause = "first_anchor_evicted"
    elif current_window.start <= first_anchor.pivot_time < left_context_end:
        removal_cause = "first_anchor_left_context_evicted"
    else:
        raise ReplayScopeBlocked(
            "UNATTRIBUTED_SOURCE_REMOVAL",
            checkpoint_index=checkpoint.index,
            family_id=family_id,
            first_anchor_timestamp=first_anchor.pivot_time,
            first_anchor_required_history_start=required_history_start,
            previous_effective_window_start=previous_window.start,
            current_effective_window_start=current_window.start,
        )

    return {
        "family_id": family_id,
        "previous_checkpoint_index": checkpoint.index - 1,
        "checkpoint_index": checkpoint.index,
        "role": role,
        "first_anchor_id": first_anchor.anchor_id,
        "first_anchor_timestamp": _iso(first_anchor.pivot_time),
        "first_anchor_confirmation_time": _iso(first_anchor.confirmation_time),
        "first_anchor_required_history_start": _iso(required_history_start),
        "second_anchor_id": second_anchor.anchor_id,
        "second_anchor_timestamp": _iso(second_anchor.pivot_time),
        "second_anchor_confirmation_time": _iso(second_anchor.confirmation_time),
        "left_confirmation_bars": LEFT_CONFIRMATION_BARS,
        "interval_seconds": INTERVAL_SECONDS,
        "previous_effective_window_start": _iso(previous_window.start),
        "current_effective_window_start": _iso(current_window.start),
        "removal_cause": removal_cause,
        "attribution_rule": (
            "previous_effective_window_start <= "
            "first_anchor_required_history_start < "
            "current_effective_window_start"
        ),
        "attribution_status": "attributed_source_eviction",
    }


def _validate_unique_removal_attributions(
    attributions: Sequence[Mapping[str, Any]],
) -> None:
    family_ids = [item["family_id"] for item in attributions]
    if len(set(family_ids)) != len(family_ids):
        raise ReplayScopeBlocked("duplicate removal attribution")


def _validate_tracking_step(
    current: TrendlineTrackingSnapshot,
    *,
    previous: TrendlineTrackingSnapshot | None,
    selection: CandidateSelectionSnapshot,
    checkpoint: CheckpointSpec,
    window: EffectiveWindow,
    previous_window: EffectiveWindow | None,
) -> tuple[dict[str, Any], ...]:
    if (
        current.status.value != "updated"
        or current.source_selection_status is not SelectionStatus.SELECTED
    ):
        raise ReplayScopeBlocked("tracking source is not updated/selected")
    if current.observed_at != checkpoint.observed_at:
        raise ReplayScopeBlocked("tracking observation boundary mismatch")
    current_ids = {family.family_id for family in current.active_families}
    if len(current_ids) != len(current.active_families):
        raise ReplayScopeBlocked("active family IDs are not unique")
    if len(current.active_families) != len(selection.selected_candidates):
        raise ReplayScopeBlocked("tracking/selection active count mismatch")
    _validate_active_window(current, window, checkpoint)
    if previous is None:
        if (
            current.previous_tracking_snapshot_id is not None
            or current.diagnostics.birth_count != len(current_ids)
            or current.diagnostics.continuation_count != 0
            or current.diagnostics.source_removed_count != 0
            or current.removed_family_ids
            or any(
                item.transition_type is not FamilyTrackingTransitionType.BIRTH
                for item in current.transitions
            )
        ):
            raise ReplayScopeBlocked("initial replay birth gate failed")
        return ()
    if (
        previous_window is None
        or current.previous_tracking_snapshot_id != previous.snapshot_id
    ):
        raise ReplayScopeBlocked("tracking previous snapshot/window binding mismatch")
    previous_ids = {family.family_id for family in previous.active_families}
    continued = previous_ids & current_ids
    born = current_ids - previous_ids
    removed_now = previous_ids - current_ids
    if (
        current.diagnostics.continuation_count != len(continued)
        or current.diagnostics.birth_count != len(born)
        or current.diagnostics.source_removed_count != len(removed_now)
        or current.diagnostics.previous_active_count != len(previous_ids)
        or current.diagnostics.current_active_count != len(current_ids)
        or current.diagnostics.source_selected_candidate_count != len(current_ids)
        or current.diagnostics.cumulative_removed_count
        != len(current.removed_family_ids)
        or set(current.removed_family_ids)
        != set(previous.removed_family_ids) | removed_now
        or current_ids & set(current.removed_family_ids)
    ):
        raise ReplayScopeBlocked("exact tracking set arithmetic failed")
    transition_by_type = {
        transition_type: {
            item.family_id
            for item in current.transitions
            if item.transition_type is transition_type
        }
        for transition_type in FamilyTrackingTransitionType
    }
    if (
        transition_by_type[FamilyTrackingTransitionType.CONTINUE] != continued
        or transition_by_type[FamilyTrackingTransitionType.BIRTH] != born
        or transition_by_type[FamilyTrackingTransitionType.SOURCE_REMOVED]
        != removed_now
    ):
        raise ReplayScopeBlocked("tracking transition set arithmetic failed")
    previous_by_id = {family.family_id: family for family in previous.active_families}
    current_by_id = {family.family_id: family for family in current.active_families}
    for family_id in continued:
        old = previous_by_id[family_id]
        new = current_by_id[family_id]
        if (
            new.version != old.version + 1
            or new.observation_count != old.observation_count + 1
            or new.first_seen_at != old.first_seen_at
            or new.last_seen_at != checkpoint.observed_at
            or new.current_candidate.candidate_id == old.current_candidate.candidate_id
            or new.current_selection_snapshot_id != selection.snapshot_id
        ):
            raise ReplayScopeBlocked("continuation lineage advancement failed")
    attributions: list[dict[str, Any]] = []
    for family_id in sorted(removed_now):
        old = previous_by_id[family_id]
        first_anchor, second_anchor = old.current_candidate.anchors[:2]
        attributions.append(
            _removal_attribution(
                family_id=family_id,
                role=old.current_candidate.role.value,
                first_anchor=first_anchor,
                second_anchor=second_anchor,
                previous_observed_at=previous.observed_at,
                checkpoint=checkpoint,
                previous_window=previous_window,
                current_window=window,
                current_family_ids=current_ids,
            )
        )
    _validate_unique_removal_attributions(attributions)
    return tuple(attributions)


def _replay_records(
    full_input: ProviderInput,
    *,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
    provider: ProviderCall = discover_trendlines,
    execution_state: ReplayExecutionState | None = None,
) -> tuple[ReplayRecord, ...]:
    previous_tracking: TrendlineTrackingSnapshot | None = None
    previous_window: EffectiveWindow | None = None
    records: list[ReplayRecord] = []
    for checkpoint in CHECKPOINTS:
        if execution_state is not None:
            execution_state.current_checkpoint_index = checkpoint.index
        prefix = _prefix_input(full_input, checkpoint)
        window = _effective_window(prefix, checkpoint)
        if execution_state is not None:
            execution_state.previous_effective_window_start = previous_window.start if previous_window else None
            execution_state.current_effective_window_start = window.start
        result = _execute_provider(
            prefix,
            config=config,
            provider_config=provider_config,
            provider=provider,
            execution_state=execution_state,
        )
        discovery = result.to_snapshot()
        selection = select_trendline_candidates(discovery, policy=selection_policy)
        tracking = track_trendline_families(
            selection, previous=previous_tracking, policy=tracking_policy
        )
        attribution = _validate_tracking_step(
            tracking,
            previous=previous_tracking,
            selection=selection,
            checkpoint=checkpoint,
            window=window,
            previous_window=previous_window,
        )
        records.append(
            ReplayRecord(
                checkpoint=checkpoint,
                prefix_input=prefix,
                effective_window=window,
                provider_result=result,
                discovery_snapshot=discovery,
                selection_snapshot=selection,
                tracking_snapshot=tracking,
                removal_attribution=attribution,
            )
        )
        previous_tracking = tracking
        previous_window = window
    if len(records) != 5:
        raise ReplayScopeBlocked("provider execution count is not exactly five")
    return tuple(records)


def _checkpoint_payload(record: ReplayRecord) -> dict[str, Any]:
    prefix = record.prefix_input
    return {
        "schema_version": CHECKPOINT_SCHEMA,
        "checkpoint_index": record.checkpoint.index,
        "observed_at": _iso(record.checkpoint.observed_at),
        "full_source_input_identity": SOURCE_INPUT_ID,
        "prefix_row_count": prefix.row_count,
        "prefix_input_identity": prefix.input_identity,
        "prefix_first_timestamp": _iso(
            datetime.fromtimestamp(prefix.timestamps[0] / NANOSECONDS, tz=UTC)
        ),
        "prefix_last_timestamp": _iso(
            datetime.fromtimestamp(prefix.timestamps[-1] / NANOSECONDS, tz=UTC)
        ),
        "effective_window_start": _iso(record.effective_window.start),
        "effective_window_end": _iso(record.effective_window.end),
        "effective_window_row_count": record.effective_window.row_count,
        "effective_window_first_timestamp": _iso(
            record.effective_window.first_timestamp
        ),
        "effective_window_last_timestamp": _iso(record.effective_window.last_timestamp),
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
    executions = [
        {
            "execution_order": index,
            "checkpoint_index": record.checkpoint.index,
            "observed_at": _iso(record.checkpoint.observed_at),
            "prefix_input_identity": record.prefix_input.input_identity,
            "prefix_row_count": record.prefix_input.row_count,
            "effective_window_start": _iso(record.effective_window.start),
            "effective_window_row_count": record.effective_window.row_count,
            "request_identity": record.provider_result.request.request_identity,
            "provider_result_id": _provider_result_id(record.provider_result),
            "provider_status": record.provider_result.status.value,
            "provider_reason": None,
            "candidate_count": len(record.provider_result.candidates),
            "provider_execution_count": 1,
            "network_request_count": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "configuration_variant": None,
        }
        for index, record in enumerate(records, start=1)
    ]
    return {
        "schema_version": EXECUTION_AUDIT_SCHEMA,
        "provider_execution_count": 5,
        "network_request_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "configuration_variant_count": 0,
        "parallel_execution_count": 0,
        "executions": executions,
    }


def _checkpoint_summary(records: Sequence[ReplayRecord]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "checkpoint_index": record.checkpoint.index,
            "observed_at": _iso(record.checkpoint.observed_at),
            "prefix_row_count": record.prefix_input.row_count,
            "effective_window_start": _iso(record.effective_window.start),
            "effective_window_row_count": record.effective_window.row_count,
            "candidate_count": len(record.provider_result.candidates),
            "active_family_count": len(record.tracking_snapshot.active_families),
            "birth_count": record.tracking_snapshot.diagnostics.birth_count,
            "continuation_count": record.tracking_snapshot.diagnostics.continuation_count,
            "source_removed_count": record.tracking_snapshot.diagnostics.source_removed_count,
            "cumulative_removed_count": record.tracking_snapshot.diagnostics.cumulative_removed_count,
            "provider_result_id": _provider_result_id(record.provider_result),
            "discovery_snapshot_id": record.discovery_snapshot.snapshot_id,
            "selection_snapshot_id": record.selection_snapshot.snapshot_id,
            "tracking_snapshot_id": record.tracking_snapshot.snapshot_id,
        }
        for record in records
    )


def _summary_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    fields = (
        "checkpoint_index",
        "observed_at",
        "prefix_row_count",
        "effective_window_start",
        "effective_window_row_count",
        "candidate_count",
        "active_family_count",
        "birth_count",
        "continuation_count",
        "source_removed_count",
        "cumulative_removed_count",
        "provider_result_id",
        "discovery_snapshot_id",
        "selection_snapshot_id",
        "tracking_snapshot_id",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return stream.getvalue().encode("utf-8")


def _decision(
    records: Sequence[ReplayRecord],
    *,
    execution_audit: Mapping[str, Any],
) -> dict[str, Any]:
    removals = [item for record in records for item in record.removal_attribution]
    unique_removed = {item["family_id"] for item in removals}
    removal_cause_counts = {
        cause: sum(item["removal_cause"] == cause for item in removals)
        for cause in REMOVAL_CAUSES
    }
    total_continuations = sum(
        record.tracking_snapshot.diagnostics.continuation_count for record in records
    )
    total_removed = sum(
        record.tracking_snapshot.diagnostics.source_removed_count for record in records
    )
    final = records[-1].tracking_snapshot
    final_distribution: dict[str, int] = {}
    for family in final.active_families:
        key = str(family.version)
        final_distribution[key] = final_distribution.get(key, 0) + 1
    status = (
        "LOOKBACK_EVICTION_TRANSITIONS_VERIFIED"
        if total_removed > 0
        else "NO_SELECTED_FAMILY_EVICTION_OBSERVED"
    )
    payload: dict[str, Any] = {
        "schema_version": DECISION_SCHEMA,
        "study_status": status,
        "source_contract_id": SOURCE_CONTRACT_ID,
        "source_input_identity": SOURCE_INPUT_ID,
        "eviction_replay_contract_id": REPLAY_CONTRACT_ID,
        "checkpoint_count": len(records),
        "provider_success_count": sum(
            record.provider_result.status is ProviderStatus.SUCCESS
            for record in records
        ),
        "provider_execution_count": execution_audit["provider_execution_count"],
        "network_request_count": execution_audit["network_request_count"],
        "retry_count": execution_audit["retry_count"],
        "fallback_count": execution_audit["fallback_count"],
        "configuration_variant_count": execution_audit["configuration_variant_count"],
        "initial_active_family_count": len(
            records[0].tracking_snapshot.active_families
        ),
        "final_active_family_count": len(final.active_families),
        "total_birth_count": sum(
            record.tracking_snapshot.diagnostics.birth_count for record in records
        ),
        "total_continuation_count": total_continuations,
        "total_source_removed_count": total_removed,
        "unique_removed_family_count": len(unique_removed),
        "cumulative_removed_family_count": len(final.removed_family_ids),
        "candidate_id_turnover_count": total_continuations,
        "removal_checkpoint_count": sum(
            bool(record.removal_attribution) for record in records
        ),
        "attributed_removal_count": len(removals),
        "unattributed_removal_count": 0,
        "removal_cause_counts": removal_cause_counts,
        "removed_family_reappearance_count": 0,
        "active_family_count_by_checkpoint": [
            {
                "checkpoint_index": record.checkpoint.index,
                "active_family_count": len(record.tracking_snapshot.active_families),
            }
            for record in records
        ],
        "birth_count_by_checkpoint": [
            {
                "checkpoint_index": record.checkpoint.index,
                "birth_count": record.tracking_snapshot.diagnostics.birth_count,
            }
            for record in records
        ],
        "continuation_count_by_checkpoint": [
            {
                "checkpoint_index": record.checkpoint.index,
                "continuation_count": record.tracking_snapshot.diagnostics.continuation_count,
            }
            for record in records
        ],
        "source_removed_count_by_checkpoint": [
            {
                "checkpoint_index": record.checkpoint.index,
                "source_removed_count": record.tracking_snapshot.diagnostics.source_removed_count,
            }
            for record in records
        ],
        "cumulative_removed_count_by_checkpoint": [
            {
                "checkpoint_index": record.checkpoint.index,
                "cumulative_removed_count": record.tracking_snapshot.diagnostics.cumulative_removed_count,
            }
            for record in records
        ],
        "final_family_version_distribution": dict(sorted(final_distribution.items())),
        "limitation": "Exact source eviction evidence only; no market, profitability, predictive, interaction or runtime claim.",
    }
    payload["decision_id"] = deterministic_hash(DECISION_NAMESPACE, payload)
    return payload


def _source_audit(verification: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_AUDIT_SCHEMA,
        "source_root": str(SOURCE_ROOT),
        "phase10c1_commit": "c4fda38766ab46ad6118616e5757f78a98b9f836",
        "source_contract_id": SOURCE_CONTRACT_ID,
        "source_input_identity": SOURCE_INPUT_ID,
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "pre_verification": dict(verification),
        "post_verification": dict(verification),
        "source_immutability_verified": True,
        "network_request_count": 0,
        "provider_execution_count": 0,
    }


def _study_contract(
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    contract = _replay_contract()
    return {
        "schema_version": STUDY_SCHEMA,
        "replay_contract": contract,
        "source": {
            "phase10c1_commit": "c4fda38766ab46ad6118616e5757f78a98b9f836",
            "source_contract_id": SOURCE_CONTRACT_ID,
            "source_input_identity": SOURCE_INPUT_ID,
            "source_decision_id": SOURCE_DECISION_ID,
            "source_manifest_id": SOURCE_MANIFEST_ID,
            "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
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
            "checkpoint_count": 5,
            "provider_execution_count": 5,
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


def _removal_payload(records: Sequence[ReplayRecord]) -> dict[str, Any]:
    return {
        "schema_version": REMOVAL_SCHEMA,
        "attribution_rule": (
            "previous effective window start <= previous first anchor < current effective window start"
        ),
        "removed_reappearance_rule": "reject",
        "records": [item for record in records for item in record.removal_attribution],
    }


def _manifest(root: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    members = [item for item in _inventory(root) if item["path"] != "manifest.json"]
    if len(members) != 11:
        raise ReplayError(f"manifest must bind 11 members, got {len(members)}")
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "eviction_replay_contract_id": REPLAY_CONTRACT_ID,
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": members,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
    }
    payload["manifest_id"] = deterministic_hash(MANIFEST_NAMESPACE, payload)
    return payload


def _write_bundle(
    root: Path,
    *,
    records: Sequence[ReplayRecord],
    source_verification: Mapping[str, Any],
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    _write_json(
        root / "study_contract.json",
        _study_contract(config, provider_config, selection_policy, tracking_policy),
    )
    _write_json(root / "source_audit.json", _source_audit(source_verification))
    execution = _execution_audit(records)
    _write_json(root / "provider_execution_audit.json", execution)
    summary = _checkpoint_summary(records)
    _write_atomic(root / "checkpoint_summary.csv", _summary_csv(summary))
    _write_json(root / "removal_attribution.json", _removal_payload(records))
    decision = _decision(records, execution_audit=execution)
    _write_json(root / "decision.json", decision)
    for record in records:
        path = (
            root
            / "datasets"
            / "btcusdt_4h"
            / (
                f"checkpoint_{record.checkpoint.index:02d}_"
                f"{record.checkpoint.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
            )
        )
        _write_json(path, _checkpoint_payload(record))
    manifest = _manifest(root, decision)
    _write_json(root / "manifest.json", manifest)
    return {"decision": decision, "manifest": manifest, "summary": summary}


def _typed_provider_result(payload: Mapping[str, Any]) -> ProviderResult:
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
            observed_at=_parse_datetime(
                input_payload["observed_at"], field_name="observed_at"
            ),
            confirmed_through=_parse_datetime(
                input_payload["confirmed_through"], field_name="confirmed_through"
            ),
            timestamps=tuple(input_payload["timestamps"]),
            open=tuple(input_payload["open"]),
            high=tuple(input_payload["high"]),
            low=tuple(input_payload["low"]),
            close=tuple(input_payload["close"]),
            volume=tuple(input_payload["volume"]),
        )
        request = ProviderRequest(
            input_data=input_data, config=config, provider_config=provider_config
        )
        result = ProviderResult(
            provider_name=payload["provider_name"],
            provider_version=payload["provider_version"],
            request=request,
            status=payload["status"],
            candidates=tuple(
                LineCandidate.from_dict(item) for item in payload["candidates"]
            ),
            evidence=tuple(
                ConfirmedExtremaPairEvidence.from_dict(item)
                for item in payload["evidence"]
            ),
            diagnostics=ProviderDiagnostics(**dict(payload["diagnostics"])),
            reason=payload["reason"],
            detail=payload["detail"],
        )
    except (
        ContractValidationError,
        KeyError,
        TypeError,
        ValueError,
        ReplayError,
    ) as exc:
        raise ReplayError("provider result typed validation failed") from exc
    if canonical_json(result.to_dict()) != canonical_json(dict(payload)):
        raise ReplayError("provider result semantic round-trip mismatch")
    return result


def _record_from_payload(
    payload: Mapping[str, Any],
    *,
    full_input: ProviderInput,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    selection_policy: LatestValidPredecessorPolicy,
    tracking_policy: ExactSelectedStructureTrackingPolicy,
    previous: TrendlineTrackingSnapshot | None,
    previous_window: EffectiveWindow | None,
) -> ReplayRecord:
    try:
        checkpoint = next(
            item
            for item in CHECKPOINTS
            if item.index == payload["checkpoint_index"]
            and _iso(item.observed_at) == payload["observed_at"]
        )
    except (KeyError, StopIteration) as exc:
        raise ReplayError("checkpoint identity mismatch") from exc
    prefix = _prefix_input(full_input, checkpoint)
    window = _effective_window(prefix, checkpoint)
    if (
        payload.get("prefix_row_count") != prefix.row_count
        or payload.get("prefix_input_identity") != prefix.input_identity
        or payload.get("full_source_input_identity") != SOURCE_INPUT_ID
        or payload.get("effective_window_start") != _iso(window.start)
        or payload.get("effective_window_end") != _iso(window.end)
        or payload.get("effective_window_row_count") != EFFECTIVE_ROWS
        or payload.get("effective_window_first_timestamp")
        != _iso(window.first_timestamp)
        or payload.get("effective_window_last_timestamp") != _iso(window.last_timestamp)
    ):
        raise ReplayError("checkpoint prefix/window binding mismatch")
    result = _typed_provider_result(payload["provider_result"])
    expected_result_id = _provider_result_id(result)
    if payload.get("provider_result_id") != expected_result_id:
        raise ReplayError("provider result identity mismatch")
    _execute_provider_result_binding(result, prefix, config, provider_config)
    discovery = result.to_snapshot()
    if payload.get("discovery_snapshot_id") != discovery.snapshot_id:
        raise ReplayError("discovery snapshot identity mismatch")
    selection = select_trendline_candidates(discovery, policy=selection_policy)
    if payload.get("selection_snapshot") != selection.to_dict():
        raise ReplayError("selection snapshot replay mismatch")
    tracking = track_trendline_families(
        selection, previous=previous, policy=tracking_policy
    )
    if payload.get("tracking_snapshot") != tracking.to_dict():
        raise ReplayError("tracking snapshot replay mismatch")
    attribution = _validate_tracking_step(
        tracking,
        previous=previous,
        selection=selection,
        checkpoint=checkpoint,
        window=window,
        previous_window=previous_window,
    )
    return ReplayRecord(
        checkpoint=checkpoint,
        prefix_input=prefix,
        effective_window=window,
        provider_result=result,
        discovery_snapshot=discovery,
        selection_snapshot=selection,
        tracking_snapshot=tracking,
        removal_attribution=attribution,
    )


def _execute_provider_result_binding(
    result: ProviderResult,
    prefix: ProviderInput,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
) -> None:
    if (
        result.status is not ProviderStatus.SUCCESS
        or result.reason is not None
        or result.request.input_data.to_dict() != prefix.to_dict()
        or result.request.config.semantic_hash != config.semantic_hash
        or result.request.provider_config.semantic_hash != provider_config.semantic_hash
        or result.request.asset != ASSET
        or result.request.timeframe != TIMEFRAME
    ):
        raise ReplayError("persisted provider result binding mismatch")


def _verify_manifest(root: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _load_json(root / "manifest.json")
    members = tuple(
        item for item in _inventory(root) if item["path"] != "manifest.json"
    )
    if len(members) != 11 or manifest.get("member_count") != 11:
        raise ReplayError("manifest member count mismatch")
    expected = {**manifest}
    manifest_id = expected.pop("manifest_id", None)
    if manifest_id != deterministic_hash(MANIFEST_NAMESPACE, expected):
        raise ReplayError("manifest identity mismatch")
    if manifest.get("members") != list(members):
        raise ReplayError("manifest members do not match output bytes")
    if manifest.get("decision_id") != decision.get("decision_id"):
        raise ReplayError("manifest decision binding mismatch")
    if manifest.get("eviction_replay_contract_id") != REPLAY_CONTRACT_ID:
        raise ReplayError("manifest contract binding mismatch")
    return manifest


def verify_bundle(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    config, provider_config, selection_policy, tracking_policy = _fixed_configuration()
    source_verification, full_input = _verify_source()
    contract = _load_json(root / "study_contract.json")
    expected_contract = _study_contract(
        config, provider_config, selection_policy, tracking_policy
    )
    if contract != expected_contract:
        raise ReplayError("study contract mismatch")
    if contract["replay_contract"]["contract_id"] != REPLAY_CONTRACT_ID:
        raise ReplayError("replay contract ID mismatch")
    source_audit = _load_json(root / "source_audit.json")
    expected_source_audit = _source_audit(source_verification)
    if source_audit != expected_source_audit:
        raise ReplayError("source audit mismatch")
    previous: TrendlineTrackingSnapshot | None = None
    previous_window: EffectiveWindow | None = None
    records: list[ReplayRecord] = []
    for checkpoint in CHECKPOINTS:
        path = (
            root
            / "datasets"
            / "btcusdt_4h"
            / (
                f"checkpoint_{checkpoint.index:02d}_"
                f"{checkpoint.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
            )
        )
        payload = _load_json(path)
        record = _record_from_payload(
            payload,
            full_input=full_input,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
            previous=previous,
            previous_window=previous_window,
        )
        records.append(record)
        previous = record.tracking_snapshot
        previous_window = record.effective_window
    execution = _execution_audit(records)
    if _load_json(root / "provider_execution_audit.json") != execution:
        raise ReplayError("provider execution audit mismatch")
    summary = _checkpoint_summary(records)
    summary_path = root / "checkpoint_summary.csv"
    if summary_path.read_bytes() != _summary_csv(summary):
        raise ReplayError("checkpoint summary mismatch")
    removal = _load_json(root / "removal_attribution.json")
    if removal != _removal_payload(records):
        raise ReplayError("removal attribution mismatch")
    decision = _load_json(root / "decision.json")
    expected_decision = _decision(records, execution_audit=execution)
    if decision != expected_decision:
        raise ReplayError("decision replay mismatch")
    _verify_manifest(root, decision)
    inventory = _inventory(root)
    if len(inventory) != 12:
        raise ReplayError("output bundle must contain exactly 12 files")
    post_verification, post_input = _verify_source()
    if (
        post_verification != source_verification
        or post_input.input_identity != full_input.input_identity
    ):
        raise ReplayError("source changed during offline verification")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": _load_json(root / "manifest.json")["manifest_id"],
        "output_inventory_sha256": _inventory_sha256(inventory),
        "provider_execution_count": 0,
        "network_request_count": 0,
        "checkpoint_count": len(records),
    }


def execute_replay(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists():
        raise ReplayError(f"refusing existing output root: {root}")
    if os.environ.get(NETWORK_ENV) != "1":
        raise ReplayError(f"real replay requires {NETWORK_ENV}=1")
    execution_state = ReplayExecutionState()
    staging: Path | None = None
    try:
        source_verification, full_input = _verify_source()
        config, provider_config, selection_policy, tracking_policy = (
            _fixed_configuration()
        )
        contract = _replay_contract()
        if contract["contract_id"] != REPLAY_CONTRACT_ID:
            raise ReplayError("replay contract identity drift")
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{root.name}.",
                dir=root.parent,
            )
        )
        records = _replay_records(
            full_input,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
            provider=discover_trendlines,
            execution_state=execution_state,
        )
        post_verification, post_input = _verify_source()
        if (
            post_verification != source_verification
            or post_input.input_identity != full_input.input_identity
        ):
            raise ReplayError("source changed during provider replay")
        result = _write_bundle(
            staging,
            records=records,
            source_verification=source_verification,
            config=config,
            provider_config=provider_config,
            selection_policy=selection_policy,
            tracking_policy=tracking_policy,
        )
        verify_bundle(output_root=staging)
        if root.exists():
            raise ReplayError(f"refusing existing output root: {root}")
        os.replace(staging, root)
        staging = None
        verified = verify_bundle(output_root=root)
        return {**result, "verified": verified}
    except ReplayScopeBlocked as exc:
        _emit_blocked_diagnostic(exc, execution_state=execution_state)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--execute-eviction-replay", action="store_true")
    modes.add_argument("--verify", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.execute_eviction_replay:
            result = execute_replay(output_root=args.output_root)
        else:
            result = verify_bundle(output_root=args.output_root)
    except ReplayScopeBlocked as exc:
        _emit_blocked_diagnostic(exc)
        raise
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
