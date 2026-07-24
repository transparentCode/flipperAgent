from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.interaction import (
    CandleDirection,
    ConfirmedInteractionBar,
    ExactLineBarObservation,
    ExactLineObservationPolicy,
    INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE,
    InteractionObservationDiagnostics,
    LinePriceRelation,
    OBSERVATION_IDENTITY_NAMESPACE,
    TrendlineInteractionSnapshot,
)
from libs.models.trendline_v2.tracking import (
    ExactSelectedStructureTrackingPolicy,
    TrendlineTrackingSnapshot,
    track_selected_trendlines,
)

from test_tracking_contracts import BASE, _initial_snapshot, _selection, _unavailable


NEW_INPUT_ID = deterministic_hash("test_interaction_input", {"value": 2})


def _bar(
    *,
    timestamp=None,
    available_at=None,
    source_input_identity: str = NEW_INPUT_ID,
    open: float = 101.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 103.0,
    volume: float = 4.0,
) -> ConfirmedInteractionBar:
    return ConfirmedInteractionBar.create(
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=timestamp or BASE + timedelta(hours=4),
        available_at=available_at or BASE + timedelta(hours=8),
        source_input_identity=source_input_identity,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _observation(
    *,
    bar: ConfirmedInteractionBar | None = None,
    line: float = 100.0,
    tracking: TrendlineTrackingSnapshot | None = None,
    source_selection_snapshot_id: str | None = None,
    source_candidate_id: str | None = None,
    geometry_id: str | None = None,
) -> ExactLineBarObservation:
    tracking = tracking or _initial_snapshot()
    family = tracking.active_families[0]
    candidate = family.current_candidate
    return ExactLineBarObservation.create(
        family_id=family.family_id,
        family_version=family.version,
        role=family.current_candidate.role,
        source_tracking_snapshot_id=tracking.snapshot_id,
        source_selection_snapshot_id=(
            source_selection_snapshot_id or family.current_selection_snapshot_id
        ),
        source_candidate_id=source_candidate_id or candidate.candidate_id,
        geometry_id=geometry_id or candidate.geometry.geometry_id,
        bar=bar or _bar(),
        exact_line_price=line,
    )


def _snapshot(
    *,
    bar: ConfirmedInteractionBar | None = None,
    observations: tuple[ExactLineBarObservation, ...] | None = None,
    diagnostics: InteractionObservationDiagnostics | None = None,
    tracking: TrendlineTrackingSnapshot | None = None,
) -> TrendlineInteractionSnapshot:
    tracking = tracking or _initial_snapshot()
    bar = bar or _bar()
    if observations is None:
        observations = tuple(
            _observation(
                bar=bar,
                tracking=tracking,
                line=family.current_candidate.geometry.value_at(bar.timestamp),
            )
            for family in tracking.active_families
        )
    source_ids = tuple(item.family_id for item in observations)
    diagnostics = diagnostics or InteractionObservationDiagnostics(
        source_active_family_count=len(source_ids),
        observation_count=len(observations),
        support_observation_count=sum(
            item.role.value == "support" for item in observations
        ),
        resistance_observation_count=sum(
            item.role.value == "resistance" for item in observations
        ),
        wick_intersection_count=sum(
            item.wick_intersects_line for item in observations
        ),
        body_intersection_count=sum(
            item.body_intersects_line for item in observations
        ),
    )
    return TrendlineInteractionSnapshot.create(
        source_tracking=tracking,
        observation_policy_identity=ExactLineObservationPolicy().policy_identity,
        bar=bar,
        observations=observations,
        diagnostics=diagnostics,
    )


def _empty_tracking() -> TrendlineTrackingSnapshot:
    return track_selected_trendlines(
        _unavailable(observed_at=BASE, input_identity=NEW_INPUT_ID),
        previous=None,
        policy=ExactSelectedStructureTrackingPolicy(),
    )


def _structural_snapshot(
    *,
    tracking: TrendlineTrackingSnapshot,
    bar: ConfirmedInteractionBar,
    observations: tuple[ExactLineBarObservation, ...],
    source_tracking: TrendlineTrackingSnapshot | None = None,
    source_active_family_ids: tuple[str, ...] | None = None,
) -> TrendlineInteractionSnapshot:
    source = source_tracking or tracking
    source_ids = (
        tuple(item.family_id for item in observations)
        if source_active_family_ids is None
        else source_active_family_ids
    )
    diagnostics = InteractionObservationDiagnostics(
        source_active_family_count=len(source_ids),
        observation_count=len(observations),
        support_observation_count=sum(
            item.role.value == "support" for item in observations
        ),
        resistance_observation_count=sum(
            item.role.value == "resistance" for item in observations
        ),
        wick_intersection_count=sum(
            item.wick_intersects_line for item in observations
        ),
        body_intersection_count=sum(
            item.body_intersects_line for item in observations
        ),
    )
    payload = {
        "asset": source.asset,
        "timeframe": source.timeframe,
        "observed_at": bar.available_at,
        "source_tracking_snapshot_id": source.snapshot_id,
        "source_tracking_observed_at": source.observed_at,
        "tracking_input_identity": source.input_identity,
        "bar_source_input_identity": bar.source_input_identity,
        "observation_policy_identity": ExactLineObservationPolicy().policy_identity,
        "source_active_family_ids": list(source_ids),
        "bar": bar.to_dict(),
        "observations": [item.to_dict() for item in observations],
        "diagnostics": diagnostics.to_dict(),
    }
    return TrendlineInteractionSnapshot(
        snapshot_id=deterministic_hash(
            INTERACTION_SNAPSHOT_IDENTITY_NAMESPACE, payload
        ),
        asset=source.asset,
        timeframe=source.timeframe,
        observed_at=bar.available_at,
        source_tracking_snapshot_id=source.snapshot_id,
        source_tracking_observed_at=source.observed_at,
        tracking_input_identity=source.input_identity,
        bar_source_input_identity=bar.source_input_identity,
        observation_policy_identity=ExactLineObservationPolicy().policy_identity,
        source_active_family_ids=source_ids,
        bar=bar,
        observations=observations,
        diagnostics=diagnostics,
    )


def _rebind_observation(
    observation: ExactLineBarObservation,
    **changes: object,
) -> ExactLineBarObservation:
    payload = observation.to_dict()
    payload.update(changes)
    identity_payload = {
        key: value for key, value in payload.items() if key != "observation_id"
    }
    payload["observation_id"] = deterministic_hash(
        OBSERVATION_IDENTITY_NAMESPACE, identity_payload
    )
    return ExactLineBarObservation.from_dict(payload)


def test_policy_identity_payload_and_round_trip_are_exact() -> None:
    policy = ExactLineObservationPolicy()
    assert policy.policy_identity == (
        "17a4f5e27483722091881349d775fe17adc018829efc6645d26a223c474bcdb4"
    )
    assert ExactLineObservationPolicy.from_dict(policy.to_dict()) == policy


@pytest.mark.parametrize("field", tuple(ExactLineObservationPolicy().to_dict()))
def test_policy_mutation_fails_closed(field: str) -> None:
    policy = ExactLineObservationPolicy()
    with pytest.raises(ContractValidationError):
        replace(policy, **{field: "changed"})


def test_policy_payload_is_strict() -> None:
    payload = ExactLineObservationPolicy().to_dict()
    payload["extra"] = "reject"
    with pytest.raises(ContractValidationError):
        ExactLineObservationPolicy.from_dict(payload)


def test_confirmed_bar_round_trip_and_deterministic_identity() -> None:
    bar = _bar()
    assert ConfirmedInteractionBar.from_dict(bar.to_dict()) == bar
    assert _bar().bar_id == bar.bar_id
    assert _bar(close=104.0).bar_id != bar.bar_id


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": BASE + timedelta(hours=8)},
        {"available_at": BASE + timedelta(hours=4)},
        {"high": 98.0},
        {"open": 106.0},
        {"close": 98.0},
        {"volume": -1.0},
        {"open": float("nan")},
    ],
)
def test_confirmed_bar_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        _bar(**changes)


def test_confirmed_bar_rejects_forged_id_and_missing_source_identity() -> None:
    bar = _bar()
    with pytest.raises(ContractValidationError):
        replace(bar, bar_id="f" * 64)
    payload = bar.to_dict()
    payload["source_input_identity"] = ""
    with pytest.raises(ContractValidationError):
        ConfirmedInteractionBar.from_dict(payload)


def test_observation_round_trip_and_exact_formula_contract() -> None:
    observation = _observation()
    assert ExactLineBarObservation.from_dict(observation.to_dict()) == observation
    assert observation.close_relation is LinePriceRelation.ABOVE
    assert observation.candle_direction is CandleDirection.UP
    assert observation.wick_intersects_line is True
    assert observation.body_intersects_line is False
    assert observation.absolute_close_distance == 3.0


@pytest.mark.parametrize(
    "changes",
    [
        {"exact_line_price": 101.0},
        {"open_minus_line": 999.0},
        {"absolute_close_distance": 999.0},
        {"wick_intersects_line": False},
        {"body_intersects_line": True},
        {"close_relation": LinePriceRelation.BELOW},
        {"candle_direction": CandleDirection.DOWN},
        {"family_version": 0},
    ],
)
def test_observation_rejects_forged_semantics(changes: dict[str, object]) -> None:
    observation = _observation()
    with pytest.raises(ContractValidationError):
        replace(observation, **changes)


def test_observation_payload_keys_are_strict() -> None:
    payload = _observation().to_dict()
    payload["extra"] = True
    with pytest.raises(ContractValidationError):
        ExactLineBarObservation.from_dict(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_active_family_count": 1, "observation_count": 0},
        {"support_observation_count": 0, "resistance_observation_count": 0},
        {"wick_intersection_count": 2},
        {"body_intersection_count": 2},
    ],
)
def test_diagnostics_require_exact_population_and_counts(
    changes: dict[str, int],
) -> None:
    payload = {
        "source_active_family_count": 1,
        "observation_count": 1,
        "support_observation_count": 1,
        "resistance_observation_count": 0,
        "wick_intersection_count": 0,
        "body_intersection_count": 0,
    }
    payload.update(changes)
    with pytest.raises(ContractValidationError):
        InteractionObservationDiagnostics(**payload)


def test_snapshot_round_trip_and_empty_snapshot() -> None:
    snapshot = _snapshot()
    assert TrendlineInteractionSnapshot.from_dict(snapshot.to_dict()) == snapshot
    TrendlineInteractionSnapshot.from_dict(snapshot.to_dict()).validate_source_tracking(
        _initial_snapshot()
    )

    empty_bar = _bar(source_input_identity=deterministic_hash("empty_bar_input", {}))
    tracking = _empty_tracking()
    empty = TrendlineInteractionSnapshot.create(
        source_tracking=tracking,
        observation_policy_identity=ExactLineObservationPolicy().policy_identity,
        bar=empty_bar,
        observations=(),
        diagnostics=InteractionObservationDiagnostics(0, 0, 0, 0, 0, 0),
    )
    assert empty.observations == ()
    assert empty.diagnostics.observation_count == 0


def test_snapshot_rejects_duplicate_missing_extra_and_noncanonical_families() -> None:
    snapshot = _snapshot()
    observation = snapshot.observations[0]
    tracking = _initial_snapshot()
    for observations, source_ids in (
        ((observation, observation), (observation.family_id, observation.family_id)),
        ((), (observation.family_id,)),
        ((observation,), (observation.family_id, "f" * 64)),
    ):
        with pytest.raises(ContractValidationError):
            _structural_snapshot(
                tracking=tracking,
                bar=snapshot.bar,
                observations=observations,
                source_active_family_ids=source_ids,
            )


def test_snapshot_rejects_ownership_and_diagnostic_drift() -> None:
    snapshot = _snapshot()
    with pytest.raises(ContractValidationError):
        replace(snapshot, source_tracking_snapshot_id="f" * 64)
    with pytest.raises(ContractValidationError):
        replace(
            snapshot,
            diagnostics=InteractionObservationDiagnostics(1, 1, 0, 1, 0, 0),
        )
    with pytest.raises(ContractValidationError):
        replace(snapshot, snapshot_id="f" * 64)


def test_snapshot_source_tracking_validation_accepts_genuine_round_trip() -> None:
    tracking = _initial_snapshot()
    snapshot = _snapshot(tracking=tracking)
    decoded = TrendlineInteractionSnapshot.from_dict(snapshot.to_dict())
    decoded.validate_source_tracking(tracking)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_selection_snapshot_id": "a" * 64},
        {"source_candidate_id": "b" * 64},
        {"geometry_id": "c" * 64},
        {"family_version": 2},
        {"role": "resistance"},
    ],
)
def test_snapshot_source_tracking_rejects_rebound_family_provenance(
    changes: dict[str, object],
) -> None:
    tracking = _initial_snapshot()
    snapshot = _snapshot(tracking=tracking)
    forged_observation = _rebind_observation(snapshot.observations[0], **changes)
    forged_snapshot = _structural_snapshot(
        tracking=tracking,
        bar=snapshot.bar,
        observations=(forged_observation,),
    )
    with pytest.raises(ContractValidationError):
        forged_snapshot.validate_source_tracking(tracking)


def test_snapshot_source_tracking_rejects_rebound_exact_line_with_recomputed_formulas() -> None:
    tracking = _initial_snapshot()
    snapshot = _snapshot(tracking=tracking)
    forged_line = 150.0
    bar = snapshot.bar
    differences = (
        bar.open - forged_line,
        bar.high - forged_line,
        bar.low - forged_line,
        bar.close - forged_line,
    )
    forged_observation = _rebind_observation(
        snapshot.observations[0],
        exact_line_price=forged_line,
        open_minus_line=differences[0],
        high_minus_line=differences[1],
        low_minus_line=differences[2],
        close_minus_line=differences[3],
        absolute_close_distance=abs(differences[3]),
        wick_intersects_line=differences[2] <= 0.0 <= differences[1],
        body_intersects_line=min(differences[0], differences[3]) <= 0.0 <= max(
            differences[0], differences[3]
        ),
        close_relation="above" if differences[3] > 0 else "below",
        candle_direction="up" if differences[3] > differences[0] else "down",
    )
    forged_snapshot = _structural_snapshot(
        tracking=tracking,
        bar=bar,
        observations=(forged_observation,),
    )
    with pytest.raises(ContractValidationError):
        forged_snapshot.validate_source_tracking(tracking)


def test_snapshot_source_tracking_rejects_valid_id_from_other_tracking_snapshot() -> None:
    tracking = _initial_snapshot()
    other_tracking = track_selected_trendlines(
        _selection(input_identity=deterministic_hash("other_input", {})),
        previous=None,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    snapshot = _snapshot(tracking=tracking)
    rebound_observation = _rebind_observation(
        snapshot.observations[0],
        source_tracking_snapshot_id=other_tracking.snapshot_id,
    )
    forged_snapshot = _structural_snapshot(
        tracking=tracking,
        source_tracking=other_tracking,
        bar=snapshot.bar,
        observations=(rebound_observation,),
    )
    with pytest.raises(ContractValidationError):
        forged_snapshot.validate_source_tracking(tracking)


def test_snapshot_source_tracking_rejects_different_active_family_inventory() -> None:
    tracking = _initial_snapshot()
    snapshot = _structural_snapshot(
        tracking=tracking,
        bar=_bar(),
        observations=(),
        source_active_family_ids=(),
    )
    with pytest.raises(ContractValidationError):
        snapshot.validate_source_tracking(tracking)
