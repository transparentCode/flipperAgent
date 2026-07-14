from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyRole,
    FamilyInteractionObservation,
    TrendlineFamilyState,
    TrendlineFamilySnapshot,
)
from libs.models.trendline_family.features import build_interaction_features
from libs.models.trendline_family.interactions import InteractionAtr, evaluate_family_interaction
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    candidate,
    interaction_family,
    legacy_pre_phase_g_payload,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def test_interaction_observation_is_frozen_and_rejects_noncanonical_evidence() -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10})
    family = interaction_family(config, timestamp())
    observation = evaluate_family_interaction(
        family,
        timestamp=timestamp(),
        open_price=100.0,
        high_price=100.0,
        low_price=98.0,
        close_price=100.0,
        interaction_atr=InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3),
        config=config,
        tick_size=None,
    ).observation

    with pytest.raises(ContractValidationError, match="WICK_BREACH"):
        replace(observation, wick_penetration_atr=0.0)
    with pytest.raises(ContractValidationError, match="symmetric"):
        replace(observation.zone, upper_price=102.0)


_INTERACTION_DIAGNOSTIC_KEYS = (
    "interaction_atr",
    "interaction_atr_method",
    "interaction_atr_sample_count",
    "interaction_observation_count",
)


def test_snapshot_decoding_accepts_real_phase_c_payload_without_interaction_diagnostics() -> None:
    snapshot = _tracked_snapshot()
    legacy_payload = legacy_pre_phase_g_payload(snapshot)
    legacy_payload.pop("observations")
    legacy_payload.pop("interaction_events")
    legacy_payload.pop("interaction_event_transitions")
    for key in _INTERACTION_DIAGNOSTIC_KEYS:
        legacy_payload["diagnostics"].pop(key)

    decoded = TrendlineFamilySnapshot.from_dict(legacy_payload)

    assert decoded.observations == ()
    assert all(key not in decoded.diagnostics for key in _INTERACTION_DIAGNOSTIC_KEYS)


def test_phase_e_legacy_snapshot_without_events_may_omit_close_price() -> None:
    snapshot = _tracked_snapshot()
    legacy_payload = legacy_pre_phase_g_payload(snapshot)
    legacy_payload.pop("interaction_events")
    legacy_payload.pop("interaction_event_transitions")
    legacy_payload["observations"][0]["close_price"] = None

    decoded = TrendlineFamilySnapshot.from_dict(legacy_payload)

    assert decoded.interaction_events == ()
    assert decoded.observations[0].close_price is None


def test_phase_f_active_event_requires_current_close_price() -> None:
    snapshot = _tracked_snapshot()
    observation = snapshot.observations[0]

    with pytest.raises(ContractValidationError, match="active current interaction event requires"):
        replace(
            snapshot,
            observations=(replace(observation, close_price=None),),
        )


def test_snapshot_accepts_explicit_empty_phase_d_interaction_diagnostics() -> None:
    snapshot = _tracked_snapshot()
    legacy_payload = legacy_pre_phase_g_payload(snapshot)
    diagnostics = legacy_payload["diagnostics"]
    diagnostics.update(
        {
            "interaction_atr": None,
            "interaction_atr_method": None,
            "interaction_atr_sample_count": None,
            "interaction_observation_count": 0,
        }
    )

    legacy_payload["observations"] = []
    legacy_payload["interaction_events"] = []
    legacy_payload["interaction_event_transitions"] = []
    empty = TrendlineFamilySnapshot.from_dict(legacy_payload)

    assert empty.observations == ()
    assert empty.diagnostics["interaction_observation_count"] == 0
    assert empty.diagnostics["interaction_atr"] is None
    assert empty.diagnostics["interaction_atr_method"] is None
    assert empty.diagnostics["interaction_atr_sample_count"] is None


@pytest.mark.parametrize("present_key", _INTERACTION_DIAGNOSTIC_KEYS)
def test_snapshot_rejects_partial_interaction_diagnostics_without_observations(
    present_key: str,
) -> None:
    snapshot = _tracked_snapshot()
    diagnostics = {
        key: snapshot.diagnostics[key]
        for key in snapshot.diagnostics
        if key not in _INTERACTION_DIAGNOSTIC_KEYS
    }
    diagnostics[present_key] = (
        0 if present_key == "interaction_observation_count" else None
    )

    with pytest.raises(ContractValidationError, match="complete empty set"):
        replace(
            snapshot,
            observations=(),
            interaction_events=(),
            interaction_event_transitions=(),
            diagnostics=diagnostics,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("interaction_observation_count", 1),
        ("interaction_atr", 1.0),
        ("interaction_atr_method", "simple_true_range_mean_v1"),
        ("interaction_atr_sample_count", 1),
    ),
)
def test_snapshot_rejects_nonempty_interaction_diagnostics_without_observations(
    field_name: str,
    replacement: object,
) -> None:
    snapshot = _tracked_snapshot()
    diagnostics = dict(snapshot.diagnostics)
    diagnostics.update(
        {
            "interaction_atr": None,
            "interaction_atr_method": None,
            "interaction_atr_sample_count": None,
            "interaction_observation_count": 0,
            field_name: replacement,
        }
    )

    with pytest.raises(ContractValidationError, match="empty snapshot observations"):
        replace(
            snapshot,
            observations=(),
            interaction_events=(),
            interaction_event_transitions=(),
            diagnostics=diagnostics,
        )


def test_snapshot_rejects_duplicate_observations_and_feature_projection_defends_against_them() -> None:
    snapshot = _tracked_snapshot()
    observation = snapshot.observations[0]
    duplicate = replace(observation, observation_id="z-duplicate-observation")

    with pytest.raises(ContractValidationError, match="exactly one observation per family"):
        replace(snapshot, observations=(observation, duplicate))
    with pytest.raises(ContractValidationError, match="exactly one observation per family"):
        build_interaction_features(
            SimpleNamespace(observations=(observation, duplicate)),  # type: ignore[arg-type]
            nearest_support_family_id=observation.family_id,
            nearest_resistance_family_id=None,
        )


def test_snapshot_rejects_missing_observation_for_a_published_family() -> None:
    snapshot = _tracked_snapshot(two_roles=True)

    with pytest.raises(ContractValidationError, match="cover every published family"):
        replace(snapshot, observations=(snapshot.observations[0],))


def test_snapshot_rejects_observation_role_or_exact_geometry_mismatch() -> None:
    snapshot = _tracked_snapshot()
    observation = snapshot.observations[0]
    opposite_role = FamilyRole.RESISTANCE if observation.role is FamilyRole.SUPPORT else FamilyRole.SUPPORT
    mismatched_zone = replace(
        observation.zone,
        center_price=observation.zone.center_price + 1.0,
        lower_price=observation.zone.lower_price + 1.0,
        upper_price=observation.zone.upper_price + 1.0,
    )

    with pytest.raises(ContractValidationError, match="role must match"):
        replace(snapshot, observations=(replace(observation, role=opposite_role),))
    with pytest.raises(ContractValidationError, match="exact line price must match"):
        replace(
            snapshot,
            observations=(
                replace(
                    observation,
                    exact_line_price=mismatched_zone.center_price,
                    zone=mismatched_zone,
                    close_price=observation.close_price + 1.0,
                ),
            ),
        )


def test_observation_rejects_state_specific_penetration_and_audit_math_conflicts() -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10})
    family = interaction_family(config, timestamp())
    atr = InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3)
    wick = evaluate_family_interaction(
        family,
        timestamp=timestamp(),
        open_price=100.0,
        high_price=100.0,
        low_price=98.5,
        close_price=100.0,
        interaction_atr=atr,
        config=config,
        tick_size=None,
    ).observation
    body = evaluate_family_interaction(
        family,
        timestamp=timestamp(),
        open_price=98.5,
        high_price=100.0,
        low_price=98.0,
        close_price=100.0,
        interaction_atr=atr,
        config=config,
        tick_size=None,
    ).observation
    tick_floor = evaluate_family_interaction(
        family,
        timestamp=timestamp(),
        open_price=100.0,
        high_price=100.0,
        low_price=100.0,
        close_price=100.0,
        interaction_atr=atr,
        config=config,
        tick_size=2.0,
    ).observation

    with pytest.raises(ContractValidationError, match="WICK_BREACH"):
        replace(wick, body_penetration_atr=wick.wick_penetration_atr / 2.0)
    with pytest.raises(ContractValidationError, match="BODY_BREACH"):
        replace(body, close_penetration_atr=body.body_penetration_atr / 2.0)
    with pytest.raises(ContractValidationError, match="width_atr"):
        replace(wick, zone=replace(wick.zone, width_atr=wick.zone.width_atr + 0.1))
    with pytest.raises(ContractValidationError, match="tick_half_width"):
        replace(tick_floor, tick_half_width=tick_floor.tick_half_width - 0.5)
    with pytest.raises(ContractValidationError, match="tick_floor_applied"):
        replace(tick_floor, tick_floor_applied=False)
    with pytest.raises(ContractValidationError, match="distance_to_zone_atr"):
        replace(wick, distance_to_zone_atr=wick.distance_to_zone_atr + 0.1)
    with pytest.raises(ContractValidationError, match="close_price must match"):
        replace(wick, close_price=wick.close_price + 50.0)


@pytest.mark.parametrize("field_name", ("interaction_atr", "interaction_atr_method", "interaction_atr_sample_count"))
def test_snapshot_rejects_observations_with_mismatched_interaction_atr_audit(field_name: str) -> None:
    snapshot = _tracked_snapshot(two_roles=True)
    first, second = snapshot.observations
    if field_name == "interaction_atr":
        interaction_atr = second.interaction_atr * 2.0
        half_width = second.zone.upper_price - second.zone.center_price
        zone = replace(second.zone, width_atr=half_width / interaction_atr)
        second = replace(
            second,
            interaction_atr=interaction_atr,
            zone=zone,
            distance_to_line_atr=abs(second.close_price - second.exact_line_price) / interaction_atr,
            distance_to_zone_atr=max(
                abs(second.close_price - second.exact_line_price) / interaction_atr
                - zone.width_atr,
                0.0,
            ),
        )
    elif field_name == "interaction_atr_method":
        second = replace(second, interaction_atr_method="other_interaction_atr_v1")
    else:
        second = replace(second, interaction_atr_sample_count=second.interaction_atr_sample_count + 1)

    with pytest.raises(ContractValidationError, match="one interaction ATR"):
        replace(snapshot, observations=(first, second))


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("interaction_atr", 999.0),
        ("interaction_atr_method", "other_interaction_atr_v1"),
        ("interaction_atr_sample_count", 99),
        ("interaction_observation_count", 99),
    ),
)
def test_snapshot_rejects_interaction_atr_diagnostic_mismatch(field_name: str, replacement: object) -> None:
    snapshot = _tracked_snapshot()
    diagnostics = dict(snapshot.diagnostics)
    diagnostics[field_name] = replacement

    with pytest.raises(ContractValidationError, match="interaction_.*diagnostic"):
        replace(snapshot, diagnostics=diagnostics)


def test_observation_ids_are_content_addressed_for_state_zone_and_tick_evidence() -> None:
    atr = InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3)
    base_config = tracker_config(interaction={"tolerance_atr": 0.10})
    base_family = interaction_family(base_config, timestamp())
    base = _evaluate(base_family, base_config, atr=atr, candle=(100.0, 100.0, 100.0, 100.0), tick_size=None)
    repeat = _evaluate(base_family, base_config, atr=atr, candle=(100.0, 100.0, 100.0, 100.0), tick_size=None)
    changed_state = _evaluate(base_family, base_config, atr=atr, candle=(100.0, 100.0, 98.0, 98.0), tick_size=None)
    wider_config = tracker_config(interaction={"tolerance_atr": 0.20})
    wider_zone = _evaluate(
        interaction_family(wider_config, timestamp()),
        wider_config,
        atr=atr,
        candle=(100.0, 100.0, 100.0, 100.0),
        tick_size=None,
    )
    tick_floor = _evaluate(base_family, base_config, atr=atr, candle=(100.0, 100.0, 100.0, 100.0), tick_size=2.0)

    assert repeat.observation_id == base.observation_id
    assert changed_state.observation_id != base.observation_id
    assert wider_zone.observation_id != base.observation_id
    assert tick_floor.observation_id != base.observation_id


def _tracked_snapshot(*, two_roles: bool = False) -> TrendlineFamilySnapshot:
    config = tracker_config()
    observed = timestamp()
    candidates = (candidate(config, observed),)
    if two_roles:
        candidates += (candidate(config, observed, candidate_id="resistance", role=FamilyRole.RESISTANCE, reference_price=101.0),)
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*candidates),)),
        config=config,
    ).update(tracker_ohlcv(observed)).snapshot


def _evaluate(
    family: TrendlineFamilyState,
    config: ResolvedTrendlineFamilyConfig,
    *,
    atr: InteractionAtr,
    candle: tuple[float, float, float, float],
    tick_size: float | None,
) -> FamilyInteractionObservation:
    return evaluate_family_interaction(
        family,
        timestamp=timestamp(),
        open_price=candle[0],
        high_price=candle[1],
        low_price=candle[2],
        close_price=candle[3],
        interaction_atr=atr,
        config=config,
        tick_size=tick_size,
    ).observation
