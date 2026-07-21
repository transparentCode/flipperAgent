from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendline_v2.domain import (
    AbstentionReason,
    AnchorRef,
    CandidateEvidence,
    DiscoverySnapshot,
    DiscoveryStatus,
    LineCandidate,
    LineGeometry,
    LineRole,
)
from libs.models.trendline_v2.domain.identity import provider_identity
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc


def _candidate(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    observed_at: datetime | None = None,
) -> LineCandidate:
    first = datetime(2024, 1, 1, tzinfo=UTC)
    second = datetime(2024, 1, 2, tzinfo=UTC)
    observed = observed_at or datetime(2024, 1, 3, tzinfo=UTC)
    anchors = (
        AnchorRef("low-1", first, first + timedelta(hours=1), 100.0),
        AnchorRef("low-2", second, second + timedelta(hours=1), 110.0),
    )
    # Geometry is deliberately independent from supporting anchor prices/times.
    geometry = LineGeometry(
        first - timedelta(hours=6),
        second + timedelta(hours=6),
        50.0,
        150.0,
    )
    evidence = CandidateEvidence(2, 2, 86_400.0)
    return LineCandidate.create(
        asset=asset,
        timeframe=timeframe,
        role=LineRole.SUPPORT,
        geometry=geometry,
        anchors=anchors,
        evidence=evidence,
        observed_at=observed,
        provider_name="fixture",
        provider_version="1",
    )


def test_timestamp_space_geometry_projects_exactly_and_is_immutable() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 1, tzinfo=UTC)
    geometry = LineGeometry(start, end, 100.0, 112.0)

    assert geometry.value_at(start + timedelta(minutes=30)) == pytest.approx(106.0)
    with pytest.raises(FrozenInstanceError):
        geometry.start_price = 101.0  # type: ignore[misc]


def test_candidate_identity_serialization_and_causal_anchors_are_stable() -> None:
    candidate = _candidate()
    restored = LineCandidate.from_dict(candidate.to_dict())

    assert restored == candidate
    assert restored.candidate_id == candidate.expected_candidate_id
    assert candidate.anchors[-1].confirmation_time <= candidate.observed_at


def test_candidate_rejects_future_confirmation_and_duplicate_anchor_ids() -> None:
    candidate = _candidate()
    before_confirmation = candidate.anchors[1].confirmation_time - timedelta(minutes=1)
    with pytest.raises(ContractValidationError, match="unconfirmed"):
        LineCandidate.create(
            asset=candidate.asset,
            timeframe=candidate.timeframe,
            role=candidate.role,
            geometry=candidate.geometry,
            anchors=candidate.anchors,
            evidence=candidate.evidence,
            observed_at=before_confirmation,
            provider_name=candidate.provider_name,
            provider_version=candidate.provider_version,
        )
    duplicate = AnchorRef(
        "low-1",
        candidate.anchors[1].pivot_time,
        candidate.anchors[1].confirmation_time,
        110.0,
    )
    with pytest.raises(ContractValidationError, match="anchor IDs"):
        LineCandidate.create(
            asset=candidate.asset,
            timeframe=candidate.timeframe,
            role=LineRole.SUPPORT,
            geometry=candidate.geometry,
            anchors=(candidate.anchors[0], duplicate),
            evidence=candidate.evidence,
            observed_at=candidate.observed_at,
            provider_name="fixture",
            provider_version="1",
        )


def test_candidate_identity_is_market_scoped() -> None:
    btc = _candidate(asset="BTCUSDT")
    eth = _candidate(asset="ETHUSDT")
    one_hour = _candidate(timeframe="1h")
    assert len({btc.candidate_id, eth.candidate_id, one_hour.candidate_id}) == 3


def test_snapshot_requires_canonical_order_explicit_abstention_and_market_binding() -> None:
    candidate = _candidate()
    snapshot = DiscoverySnapshot(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=candidate.observed_at,
        input_identity="a" * 64,
        config_identity="b" * 64,
        provider_identity=provider_identity("fixture", "1"),
        status=DiscoveryStatus.VALID,
        candidates=(candidate,),
    )
    restored = DiscoverySnapshot.from_dict(snapshot.to_dict())
    assert restored.snapshot_id == snapshot.snapshot_id

    with pytest.raises(ContractValidationError, match="market identity"):
        DiscoverySnapshot(
            asset="ETHUSDT",
            timeframe="4h",
            observed_at=candidate.observed_at,
            input_identity="a" * 64,
            config_identity="b" * 64,
            provider_identity=provider_identity("fixture", "1"),
            status=DiscoveryStatus.VALID,
            candidates=(candidate,),
        )

    abstained = DiscoverySnapshot(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=candidate.observed_at,
        input_identity="a" * 64,
        config_identity="b" * 64,
        provider_identity="c" * 64,
        status=DiscoveryStatus.ABSTAINED,
        candidates=(),
        reason=AbstentionReason.INSUFFICIENT_DATA,
    )
    assert abstained.to_dict()["reason"] == "insufficient_data"
    with pytest.raises(ContractValidationError):
        DiscoverySnapshot.from_dict({**snapshot.to_dict(), "snapshot_id": "0" * 64})


def test_evidence_rejects_provider_specific_fields() -> None:
    with pytest.raises(ContractValidationError):
        CandidateEvidence.from_dict(
            {
                "anchor_count": 2,
                "distinct_anchor_timestamps": 2,
                "anchor_span_seconds": 1.0,
                "residual_error": 0.0,
            }
        )
