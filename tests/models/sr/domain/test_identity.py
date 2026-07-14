from __future__ import annotations

from datetime import datetime, timezone, tzinfo

import pytest

from libs.models.sr import (
    CandidateLevel,
    ContractValidationError,
    SREvent,
    SREventType,
    SRSnapshot,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
    canonical_json,
    hash_candidate_level,
    hash_event,
    hash_snapshot,
    hash_zone_definition,
    require_utc,
)


def _key() -> SRStateKey:
    return SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")


def _geometry(center: float = 100.0, half_width: float = 5.0) -> ZoneGeometry:
    return ZoneGeometry(center=center, half_width=half_width)


def _config_hash() -> str:
    return "a" * 64


def _candidate(*, half_width: float = 5.0) -> CandidateLevel:
    return CandidateLevel(
        state_key=_key(),
        side=ZoneSide.SUPPORT,
        geometry=_geometry(half_width=half_width),
        source="test-source",
        formed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=1.5,
    )


def _definition() -> ZoneDefinition:
    return ZoneDefinition(
        state_key=_key(),
        side=ZoneSide.RESISTANCE,
        geometry=_geometry(center=200.0),
        source="test-source",
        created_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=2.0,
        config_hash=_config_hash(),
    )


def _event(zone_id: str = "a" * 64) -> SREvent:
    return SREvent(
        zone_id=zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        price=100.0,
        bar_id="bar-1",
    )


def test_candidate_id_is_sha256() -> None:
    c = _candidate()
    assert len(c.candidate_id) == 64
    assert int(c.candidate_id, 16) >= 0


def test_candidate_identity_is_content_based() -> None:
    a = _candidate()
    b = _candidate()
    assert a.candidate_id == b.candidate_id
    assert hash_candidate_level(a) == hash_candidate_level(b)


def test_timestamp_with_none_offset_is_rejected() -> None:
    class NoneOffsetTZ(tzinfo):
        def utcoffset(self, dt: datetime | None):
            return None

    with pytest.raises(ContractValidationError):
        require_utc(
            datetime(2026, 7, 14, 12, 0, tzinfo=NoneOffsetTZ())
        )


def test_signed_zero_has_one_canonical_identity() -> None:
    assert canonical_json(0.0) == canonical_json(-0.0)
    positive = _candidate(half_width=0.0)
    negative = _candidate(half_width=-0.0)
    assert positive.candidate_id == negative.candidate_id
    assert hash_candidate_level(positive) == hash_candidate_level(negative)


def test_candidate_hash_changes_when_content_changes() -> None:
    a = _candidate()
    b = CandidateLevel(
        state_key=a.state_key,
        side=a.side,
        geometry=_geometry(center=150.0),
        source=a.source,
        formed_at=a.formed_at,
        available_at=a.available_at,
        atr_at_creation=a.atr_at_creation,
    )
    assert hash_candidate_level(a) != hash_candidate_level(b)


def test_zone_definition_identity_is_content_based() -> None:
    a = _definition()
    b = _definition()
    assert a.zone_id == b.zone_id
    assert hash_zone_definition(a) == hash_zone_definition(b)


def test_zone_definition_hash_changes_with_geometry() -> None:
    a = _definition()
    b = ZoneDefinition(
        state_key=a.state_key,
        side=a.side,
        geometry=_geometry(center=201.0),
        source=a.source,
        created_at=a.created_at,
        available_at=a.available_at,
        atr_at_creation=a.atr_at_creation,
        config_hash=a.config_hash,
    )
    assert hash_zone_definition(a) != hash_zone_definition(b)


def test_event_identity_is_content_based() -> None:
    a = _event()
    b = _event()
    assert a.event_id == b.event_id
    assert hash_event(a) == hash_event(b)


def test_snapshot_identity_excludes_snapshot_id() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )
    record = ZoneRecord(definition=definition, runtime=runtime)
    event = _event(zone_id=definition.zone_id)
    a = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        zones=(record,),
        events=(event,),
    )
    b = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        zones=(record,),
        events=(event,),
    )
    assert a.snapshot_id == b.snapshot_id
    assert hash_snapshot(a) == hash_snapshot(b)


def test_snapshot_hash_changes_with_zones() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )
    record = ZoneRecord(definition=definition, runtime=runtime)
    a = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        zones=(record,),
        events=(),
    )
    b = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        zones=(),
        events=(),
    )
    assert hash_snapshot(a) != hash_snapshot(b)


def test_equal_content_produces_equal_hashes() -> None:
    a = _candidate()
    b = _candidate()
    assert hash_candidate_level(a) == hash_candidate_level(b)
    assert a.candidate_id == b.candidate_id
