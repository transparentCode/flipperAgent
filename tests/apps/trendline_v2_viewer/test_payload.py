from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from apps.trendline_v2_viewer import build_chart_payload, write_viewer_bundle
from apps.trendline_v2_viewer.payload import (
    BUNDLE_SCHEMA_VERSION,
    PAYLOAD_SCHEMA_VERSION,
    _bundle_identity,
    _canonical_json_bytes,
    _payload_identity,
    _sha256,
)
from apps.trendline_v2_viewer.server import validate_bundle
from libs.models.trendline_v2 import discover_trendlines
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ProviderDiagnostics,
    ProviderReason,
    ProviderStatus,
    ProviderResult,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
)
from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame


UTC = timezone.utc
BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _result(*, subsecond: bool = False):
    index = [BASE + timedelta(hours=index) for index in range(7)]
    if subsecond:
        index = [value + timedelta(microseconds=1) for value in index]
    data = pd.DataFrame(
        {
            "open": (6.0,) * 7,
            "high": (10.0, 12.0, 10.0, 11.0, 10.0, 13.0, 10.0),
            "low": (5.0, 1.0, 5.0, 2.0, 5.0, 3.0, 5.0),
            "close": (6.0,) * 7,
            "volume": (1.0,) * 7,
        },
        index=pd.DatetimeIndex(index),
    )
    boundary = BASE + timedelta(hours=6, microseconds=1 if subsecond else 0)
    frame = ConfirmedOHLCVFrame.from_frame(
        data,
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=boundary,
        confirmed_through=boundary,
    )
    config = resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )
    provider_config = ConfirmedExtremaPairConfig(
        lookback_duration_seconds=24 * 3_600.0,
        left_confirmation_bars=1,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        max_hypotheses=100,
        max_output_candidates=100,
    )
    return discover_trendlines(frame, config=config, provider_config=provider_config)


def _abstained_result():
    result = _result()
    config = replace(result.request.provider_config, max_hypotheses=1)
    return discover_trendlines(
        ConfirmedOHLCVFrame.from_frame(
            pd.DataFrame(
                {
                    "open": (6.0,) * 7,
                    "high": (10.0, 12.0, 10.0, 11.0, 10.0, 13.0, 10.0),
                    "low": (5.0, 1.0, 5.0, 2.0, 5.0, 3.0, 5.0),
                    "close": (6.0,) * 7,
                    "volume": (1.0,) * 7,
                },
                index=pd.DatetimeIndex([BASE + timedelta(hours=index) for index in range(7)]),
            ),
            asset="BTCUSDT",
            timeframe="4h",
            observed_at=BASE + timedelta(hours=6),
            confirmed_through=BASE + timedelta(hours=6),
        ),
        config=result.request.config,
        provider_config=config,
    )


def test_payload_is_deterministic_and_preserves_provider_evidence() -> None:
    result = _result()
    before = result.to_dict()
    first = build_chart_payload(result)
    second = build_chart_payload(result)

    assert first == second
    assert first["payload_id"] == second["payload_id"]
    assert first["snapshot_id"] == result.to_snapshot().snapshot_id
    assert [item["candidate_id"] for item in first["candidates"]] == [
        item.candidate_id for item in result.candidates
    ]
    assert [item["evidence"]["candidate_id"] for item in first["candidates"]] == [
        item.candidate_id for item in result.evidence
    ]
    assert first["candidates"][0]["evidence"] == result.evidence[0].to_dict()
    assert result.to_dict() == before
    assert result.detail is None


def test_payload_contains_complete_whole_second_candles_and_both_roles() -> None:
    payload = build_chart_payload(_result())
    assert set(payload["candles"][0]) == {"time", "open", "high", "low", "close", "volume"}
    assert {item["role"] for item in payload["candidates"]} == {"support", "resistance"}
    assert all(isinstance(item["time"], int) for item in payload["candles"])
    assert all(
        candidate["start_time"] == candidate["anchors"][0]["pivot_time"]
        and candidate["end_time"] == candidate["anchors"][1]["pivot_time"]
        for candidate in payload["candidates"]
    )


def test_operational_provider_detail_is_not_in_payload_or_identity() -> None:
    result = _result()
    with_detail = replace(result, detail="diagnostic detail must stay operational")
    assert build_chart_payload(result) == build_chart_payload(with_detail)
    assert "detail" not in build_chart_payload(with_detail)


def test_abstained_payload_keeps_candles_and_typed_reason_without_lines() -> None:
    result = _abstained_result()
    payload = build_chart_payload(result)
    assert payload["status"] == "abstained"
    assert payload["reason"] == "hypothesis_limit_exceeded"
    assert payload["candles"]
    assert payload["candidates"] == []


def test_failed_payload_keeps_candles_and_typed_reason_without_lines() -> None:
    result = _result()
    failed = ProviderResult(
        provider_name=result.provider_name,
        provider_version=result.provider_version,
        request=result.request,
        status=ProviderStatus.FAILED,
        candidates=(),
        evidence=(),
        diagnostics=ProviderDiagnostics(0, result.request.input_data.row_count),
        reason=ProviderReason.PROVIDER_FAILURE,
        detail="operational failure is not part of payload identity",
    )
    payload = build_chart_payload(failed)
    assert payload["status"] == "failed"
    assert payload["reason"] == "provider_failure"
    assert payload["candles"]
    assert payload["candidates"] == []


def test_subsecond_input_is_rejected_without_rounding() -> None:
    with pytest.raises(ContractValidationError, match="whole-second"):
        build_chart_payload(_result(subsecond=True))


def test_wrong_input_type_is_rejected() -> None:
    with pytest.raises(ContractValidationError, match="ProviderResult"):
        build_chart_payload({})  # type: ignore[arg-type]


def test_bundle_has_exact_members_and_refuses_unknown_nonempty_destination(tmp_path: Path) -> None:
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    assert {path.name for path in bundle.iterdir()} == {"manifest.json", "chart_payload.json"}
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert manifest["members"] == [
        {
            "name": "chart_payload.json",
            "sha256": hashlib.sha256(
                (bundle / "chart_payload.json").read_bytes()
            ).hexdigest(),
            "byte_length": (bundle / "chart_payload.json").stat().st_size,
        }
    ]
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        write_viewer_bundle(_result(), occupied)
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_bundle_writes_into_an_existing_empty_directory_and_rejects_symlink(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    write_viewer_bundle(_result(), empty)
    assert {item.name for item in empty.iterdir()} == {"manifest.json", "chart_payload.json"}

    symlink = tmp_path / "symlink"
    symlink.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        write_viewer_bundle(_result(), symlink)


def _rebind_bundle(bundle: Path, mutate) -> None:
    payload_path = bundle / "chart_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    mutate(payload)
    payload["payload_id"] = deterministic_hash(
        PAYLOAD_SCHEMA_VERSION,
        _payload_identity(payload),
    )
    payload_bytes = _canonical_json_bytes(payload)
    payload_path.write_bytes(payload_bytes)
    members = [
        {
            "name": "chart_payload.json",
            "sha256": _sha256(payload_bytes),
            "byte_length": len(payload_bytes),
        }
    ]
    manifest_without_id = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "payload_id": payload["payload_id"],
        "members": members,
    }
    manifest = {
        **manifest_without_id,
        "bundle_id": _bundle_identity(manifest_without_id),
    }
    (bundle / "manifest.json").write_bytes(_canonical_json_bytes(manifest))


def _tampered_bundle(tmp_path: Path, mutate) -> Path:
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    _rebind_bundle(bundle, mutate)
    return bundle


def _replace_first_evidence(payload: dict[str, object], **changes: object) -> None:
    candidate = payload["candidates"][0]
    evidence = ConfirmedExtremaPairEvidence.from_dict(candidate["evidence"])
    candidate["evidence"] = ConfirmedExtremaPairEvidence(
        candidate_id=evidence.candidate_id,
        extrema_kind=evidence.extrema_kind,
        anchor_source_positions=changes.get(
            "anchor_source_positions", evidence.anchor_source_positions
        ),
        confirmation_positions=changes.get(
            "confirmation_positions", evidence.confirmation_positions
        ),
        validated_intermediate_count=changes.get(
            "validated_intermediate_count", evidence.validated_intermediate_count
        ),
        body_violation_count=changes.get(
            "body_violation_count", evidence.body_violation_count
        ),
    ).to_dict()


def test_bundle_rejects_impossible_failed_no_candidates_after_rebinding(tmp_path: Path) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: payload.update(
            status="failed", reason="no_candidates", candidates=[]
        ),
    )
    with pytest.raises(ValueError, match="status/reason"):
        validate_bundle(bundle)


def test_bundle_rejects_impossible_abstained_provider_failure_after_rebinding(
    tmp_path: Path,
) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: payload.update(
            status="abstained", reason="provider_failure", candidates=[]
        ),
    )
    with pytest.raises(ValueError, match="status/reason"):
        validate_bundle(bundle)


def test_bundle_rejects_forged_evidence_id_after_rebinding(tmp_path: Path) -> None:
    def mutate(payload: dict[str, object]) -> None:
        payload["candidates"][0]["evidence"]["evidence_id"] = "f" * 64

    bundle = _tampered_bundle(tmp_path, mutate)
    with pytest.raises(ValueError, match="evidence content"):
        validate_bundle(bundle)


def test_bundle_rejects_unrelated_evidence_source_positions_after_rebinding(
    tmp_path: Path,
) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: _replace_first_evidence(
            payload,
            anchor_source_positions=(0, 3),
            confirmation_positions=(1, 4),
        ),
    )
    with pytest.raises(ValueError, match="source position"):
        validate_bundle(bundle)


def test_bundle_rejects_out_of_range_confirmation_positions_after_rebinding(
    tmp_path: Path,
) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: _replace_first_evidence(
            payload,
            confirmation_positions=(2, len(payload["candles"])),
        ),
    )
    with pytest.raises(ValueError, match="outside the candle array"):
        validate_bundle(bundle)


def test_bundle_rejects_source_price_mismatch_after_rebinding(tmp_path: Path) -> None:
    def mutate(payload: dict[str, object]) -> None:
        candidate = payload["candidates"][0]
        wrong_price = candidate["anchors"][0]["price"] + 0.25
        candidate["anchors"][0]["price"] = wrong_price
        candidate["start_price"] = wrong_price

    bundle = _tampered_bundle(tmp_path, mutate)
    with pytest.raises(ValueError, match="source position.*price"):
        validate_bundle(bundle)


def test_bundle_rejects_anchor_candle_timestamp_mismatch_after_rebinding(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, object]) -> None:
        wrong_time = payload["candles"][0]["time"]
        payload["candidates"][0]["anchors"][0]["pivot_time"] = wrong_time
        payload["candidates"][0]["start_time"] = wrong_time

    bundle = _tampered_bundle(tmp_path, mutate)
    with pytest.raises(ValueError, match="source position.*time"):
        validate_bundle(bundle)


def test_bundle_rejects_incorrect_intermediate_count_after_rebinding(tmp_path: Path) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: _replace_first_evidence(
            payload,
            validated_intermediate_count=0,
        ),
    )
    with pytest.raises(ValueError, match="intermediate count"):
        validate_bundle(bundle)


def test_bundle_rejects_nonzero_success_body_violations_after_rebinding(tmp_path: Path) -> None:
    bundle = _tampered_bundle(
        tmp_path,
        lambda payload: _replace_first_evidence(payload, body_violation_count=1),
    )
    with pytest.raises(ValueError, match="body violations"):
        validate_bundle(bundle)
