from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, SnapshotVersionError, deserialize_snapshot, serialize_snapshot


def test_repository_isolates_asset_timeframe_snapshots(snapshot) -> None:
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(snapshot)
    assert repository.latest_snapshot("BTCUSDT", "4h") == snapshot
    assert repository.latest_snapshot("BTCUSDT", "1h") is None
    assert repository.latest_snapshot("ETHUSDT", "4h") is None


def test_repository_rejects_previous_snapshot_mismatch_and_version_regression(snapshot) -> None:
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(snapshot)
    wrong_parent = replace(snapshot, snapshot_id="snapshot-2", timestamp=snapshot.timestamp + timedelta(hours=4), previous_snapshot_id="wrong")
    with pytest.raises(SnapshotVersionError, match="previous_snapshot_id"):
        repository.save_snapshot(wrong_parent)
    regression = replace(snapshot, snapshot_id="snapshot-2", timestamp=snapshot.timestamp + timedelta(hours=4), previous_snapshot_id=snapshot.snapshot_id)
    with pytest.raises(SnapshotVersionError, match="version must advance"):
        repository.save_snapshot(regression)


def test_repository_rejects_non_birth_family_version_in_first_snapshot(snapshot) -> None:
    repository = InMemoryTrendlineFamilyRepository()

    # Simulate a corrupt persisted object that bypassed contract construction.
    object.__setattr__(snapshot.active_families[0], "version", 2)

    with pytest.raises(SnapshotVersionError, match="must start at version one"):
        repository.save_snapshot(snapshot)


def test_repository_snapshot_serialization_round_trip_and_malformed_payload(snapshot) -> None:
    assert deserialize_snapshot(serialize_snapshot(snapshot)).to_dict() == snapshot.to_dict()
    with pytest.raises(ContractValidationError):
        deserialize_snapshot("{")
    with pytest.raises(ContractValidationError):
        deserialize_snapshot("[]")
    with pytest.raises(ContractValidationError):
        deserialize_snapshot('{"snapshot_id":"missing-fields"}')
