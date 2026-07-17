from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.models.sr import (
    AssociationConfig,
    CandidateLevel,
    ContractValidationError,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.association import match_candidate


_T0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _key(symbol: str = "BTCUSDT") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe="1h")


def _config(merge_distance_atr: float = 0.5) -> AssociationConfig:
    return AssociationConfig(merge_distance_atr=merge_distance_atr)


def _candidate(
    *,
    center: float = 100.0,
    side: ZoneSide = ZoneSide.SUPPORT,
    atr: float = 2.0,
    state_key: SRStateKey | None = None,
) -> CandidateLevel:
    return CandidateLevel(
        state_key=state_key or _key(),
        side=side,
        geometry=ZoneGeometry(center=center, half_width=1.0),
        source="pivot_v1",
        formed_at=_T0,
        available_at=_T0,
        atr_at_creation=atr,
    )


def _zone(
    *,
    center: float = 100.0,
    side: ZoneSide = ZoneSide.SUPPORT,
    status: ZoneStatus = ZoneStatus.ACTIVE,
    state_key: SRStateKey | None = None,
) -> ZoneRecord:
    definition = ZoneDefinition(
        state_key=state_key or _key(),
        side=side,
        geometry=ZoneGeometry(center=center, half_width=1.0),
        source="pivot_v1",
        created_at=_T0,
        available_at=_T0,
        atr_at_creation=2.0,
        config_hash="a" * 64,
    )
    return ZoneRecord(
        definition=definition,
        runtime=ZoneRuntimeState(
            zone_id=definition.zone_id,
            status=status,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=0,
            last_interaction_at=None,
            updated_at=_T0,
        ),
    )


def test_same_side_candidate_matches_at_threshold_equality() -> None:
    candidate = _candidate(center=100.0, atr=2.0)
    zone = _zone(center=101.0)

    assert match_candidate(candidate, (zone,), _config(0.5)) is zone


def test_outside_threshold_and_opposite_side_do_not_match() -> None:
    candidate = _candidate(side=ZoneSide.SUPPORT)
    far_zone = _zone(center=102.1)
    opposite_zone = _zone(side=ZoneSide.RESISTANCE)

    assert match_candidate(candidate, (far_zone,), _config()) is None
    assert match_candidate(candidate, (opposite_zone,), _config()) is None


def test_nearest_same_side_zone_wins() -> None:
    candidate = _candidate(center=100.0, atr=10.0)
    farther = _zone(center=102.0)
    nearer = _zone(center=100.5)

    assert match_candidate(candidate, (farther, nearer), _config()) is nearer


def test_equal_distance_tie_uses_zone_id() -> None:
    candidate = _candidate(center=100.0, atr=10.0)
    left = _zone(center=99.0)
    right = _zone(center=101.0)

    expected = min(left, right, key=lambda zone: zone.definition.zone_id)
    assert match_candidate(candidate, (right, left), _config()) is expected


def test_terminal_matching_is_controlled_by_caller_pool() -> None:
    candidate = _candidate()
    terminal = _zone(status=ZoneStatus.BROKEN)

    assert match_candidate(candidate, (terminal,), _config()) is terminal
    assert match_candidate(candidate, (), _config()) is None


def test_ownership_mismatch_rejected() -> None:
    candidate = _candidate()
    zone = _zone(state_key=_key("ETHUSDT"))

    with pytest.raises(ContractValidationError, match="state_key"):
        match_candidate(candidate, (zone,), _config())


def test_derived_merge_threshold_overflow_rejected() -> None:
    with pytest.raises(ContractValidationError, match="merge threshold"):
        match_candidate(_candidate(atr=2.0), (), _config(1e308))


def test_derived_distance_overflow_rejected() -> None:
    candidate = _candidate(center=1e308)
    zone = _zone(center=2.0)
    object.__setattr__(zone.definition.geometry, "center", -1e308)

    with pytest.raises(ContractValidationError, match="distance"):
        match_candidate(candidate, (zone,), _config(1.0))


def test_matcher_does_not_mutate_inputs() -> None:
    candidate = _candidate()
    zone = _zone()
    before = (candidate, zone)

    match_candidate(candidate, (zone,), _config())

    assert (candidate, zone) == before


@pytest.mark.parametrize(
    "bad_candidate, bad_zones, bad_config, message",
    [
        (object(), (), _config(), "CandidateLevel"),
        (_candidate(), [ _zone() ], _config(), "exactly a tuple"),
        (_candidate(), (), object(), "AssociationConfig"),
    ],
)
def test_matcher_rejects_wrong_input_types(
    bad_candidate: object,
    bad_zones: object,
    bad_config: object,
    message: str,
) -> None:
    with pytest.raises(ContractValidationError, match=message):
        match_candidate(bad_candidate, bad_zones, bad_config)  # type: ignore[arg-type]
