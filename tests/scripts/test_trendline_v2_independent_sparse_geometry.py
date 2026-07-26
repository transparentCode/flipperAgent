from __future__ import annotations

from datetime import UTC, datetime, timedelta
import ast
from pathlib import Path
import os
import shutil
from types import SimpleNamespace

import pytest

from libs.models.trendline_v2.domain.provider_input import ProviderInput
from scripts import analyze_trendline_v2_independent_sparse_geometry as study


def _input(
    *,
    rows: int = 160,
    timeframe: str = "1h",
    asset: str = "BTCUSDT",
    lows: tuple[float, ...] | None = None,
    highs: tuple[float, ...] | None = None,
) -> ProviderInput:
    interval = study.INTERVAL_SECONDS[timeframe]
    first = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int((first + timedelta(seconds=interval * i)).timestamp() * study.NANOSECONDS)
        for i in range(rows)
    )
    close = tuple(100.0 + (i % 7) * 0.1 for i in range(rows))
    low = lows or tuple(value - 1.0 for value in close)
    high = highs or tuple(value + 1.0 for value in close)
    return ProviderInput(
        asset=asset,
        timeframe=timeframe,
        observed_at=first + timedelta(seconds=interval * rows),
        confirmed_through=first + timedelta(seconds=interval * rows),
        timestamps=timestamps,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=tuple(1.0 for _ in range(rows)),
    )


def _provider_payload(data: ProviderInput, *, forbidden: object = None) -> dict[str, object]:
    raw = data.to_dict()
    request = {"input_data": raw, "input_identity": data.input_identity}
    return {
        "provider_result": {
            "request": request,
            "candidates": forbidden if forbidden is not None else [],
            "evidence": forbidden if forbidden is not None else [],
            "selection_snapshot": forbidden,
            "tracking_snapshot": forbidden,
        }
    }


def test_contract_identity_matches_pinned_canonical_preimage() -> None:
    payload, contract_id = study._validated_contract()
    assert contract_id == study.CONTRACT_ID
    assert study.replay_contract_id(payload) == study.CONTRACT_ID
    assert set(payload) == {
        "schema_version",
        "base_commit",
        "prior_evidence",
        "independence",
        "scopes",
        "checkpoint_policy",
        "atr",
        "hierarchical_pivots",
        "owner_timeframe_validity",
        "seed_pool",
        "methods",
        "scope_method_sets",
        "research_line_contract",
        "stability",
        "future_evaluation",
        "matched_control_semantics",
        "validation",
        "holdout",
        "temporal_audit",
        "execution_accounting",
        "decision_statuses",
        "artifacts",
        "study_controls",
    }
    canonical = study.canonical_json(payload).encode()
    assert len(canonical) == study.CONTRACT_JSON_BYTE_LENGTH
    assert study._sha256_bytes(canonical) == study.CONTRACT_JSON_SHA256
    assert "controls" not in payload["methods"]["primary"]


@pytest.mark.parametrize(
    "section",
    [
        "checkpoint_policy",
        "atr",
        "hierarchical_pivots",
        "owner_timeframe_validity",
        "seed_pool",
        "methods",
        "stability",
        "future_evaluation",
        "validation",
        "execution_accounting",
    ],
)
def test_contract_drift_changes_derived_identity(section: str) -> None:
    payload = study._contract_payload()
    payload[section] = {**payload[section], "drift": True}
    assert study.replay_contract_id(payload) != study.CONTRACT_ID


def test_raw_loader_ignores_forbidden_provider_fields() -> None:
    data = _input()
    clean = study._raw_provider_input(_provider_payload(data))
    forged = study._raw_provider_input(
        _provider_payload(data, forbidden={"malformed": object()})
    )
    assert clean.to_dict() == forged.to_dict()


def test_raw_loader_rejects_input_identity_drift() -> None:
    data = _input()
    payload = _provider_payload(data)
    payload["provider_result"]["request"]["input_data"]["input_identity"] = "f" * 64  # type: ignore[index]
    with pytest.raises(study.StudyError, match="identity"):
        study._raw_provider_input(payload)


def test_960_row_1h_source_produces_22_checkpoints_and_excludes_would_be_23() -> None:
    data = _input(rows=960)
    schedule = study._checkpoint_schedule(data)
    assert len(schedule) == 22
    assert data.confirmed_through not in {
        study._datetime_from_ns(timestamp) for timestamp in data.timestamps
    }
    assert len(
        study._future_window_positions(
            data, checkpoint=schedule[-1][1], horizon_hours=96
        )
    ) == 96
    would_be_23 = schedule[-1][1] + timedelta(hours=24)
    last_source_timestamp = study._datetime_from_ns(data.timestamps[-1])
    assert would_be_23 + timedelta(hours=96) > last_source_timestamp


def test_240_row_4h_source_produces_22_checkpoints() -> None:
    data = _input(rows=240, timeframe="4h")
    schedule = study._checkpoint_schedule(data)
    assert len(schedule) == 22
    assert len(
        study._future_window_positions(
            data, checkpoint=schedule[-1][1], horizon_hours=96
        )
    ) == 24


def test_future_window_horizons_have_exact_counts() -> None:
    for timeframe, expected in (("1h", (24, 48, 96)), ("4h", (6, 12, 24))):
        data = _input(rows=180, timeframe=timeframe)
        checkpoint = _datetime_from_data(data, 60)
        assert tuple(
            len(
                study._future_window_positions(
                    data, checkpoint=checkpoint, horizon_hours=horizon
                )
            )
            for horizon in study.HORIZONS_HOURS
        ) == expected


def test_future_window_missing_interior_timestamp_blocks() -> None:
    data = _input(rows=180)
    checkpoint = _datetime_from_data(data, 60)
    malformed = SimpleNamespace(
        timeframe=data.timeframe,
        timestamps=data.timestamps[:70] + data.timestamps[71:],
    )
    with pytest.raises(study.StudyError, match="missing, duplicated, or misaligned"):
        study._future_window_positions(
            malformed, checkpoint=checkpoint, horizon_hours=24
        )


def test_future_window_duplicate_timestamp_blocks() -> None:
    data = _input(rows=180)
    checkpoint = _datetime_from_data(data, 60)
    malformed = SimpleNamespace(
        timeframe=data.timeframe,
        timestamps=data.timestamps[:70] + (data.timestamps[69],) + data.timestamps[70:],
    )
    with pytest.raises(study.StudyError, match="strictly ordered"):
        study._future_window_positions(
            malformed, checkpoint=checkpoint, horizon_hours=24
        )


def test_future_window_misaligned_timestamp_blocks() -> None:
    data = _input(rows=180)
    checkpoint = _datetime_from_data(data, 60)
    malformed = SimpleNamespace(
        timeframe=data.timeframe,
        timestamps=(
            data.timestamps[:70]
            + (data.timestamps[70] + study.NANOSECONDS,)
            + data.timestamps[71:]
        ),
    )
    with pytest.raises(study.StudyError, match="missing, duplicated, or misaligned"):
        study._future_window_positions(
            malformed, checkpoint=checkpoint, horizon_hours=24
        )


def test_schedule_and_accounting_contract_counts_are_exact() -> None:
    payload = study._contract_payload()
    assert study.VALIDATION_CHECKPOINT_COUNT == 88
    assert study.HOLDOUT_CHECKPOINT_COUNT == 44
    assert payload["checkpoint_policy"]["validation_checkpoint_count"] == 88
    assert payload["checkpoint_policy"]["holdout_checkpoint_count"] == 44
    assert payload["execution_accounting"]["validation_method_derivations"] == 704
    assert payload["execution_accounting"]["holdout_method_derivations_max"] == 176
    assert payload["execution_accounting"]["temporal_method_derivations_max"] == 10
    assert payload["execution_accounting"]["maximum_method_derivations"] == 890
    lock = study._validation_lock(
        contract_id=study.CONTRACT_ID,
        dataset_metrics={},
        ranking=(),
        winner=None,
    )
    assert lock["validation_method_derivation_count"] == 704


def test_checkpoint_schedule_rejects_short_source() -> None:
    with pytest.raises(study.StudyError, match="expected 22"):
        study._checkpoint_schedule(_input(rows=400))


def test_atr_uses_first_true_range_seed_and_wilder_recurrence() -> None:
    data = _input(rows=4)
    data = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
        timestamps=data.timestamps,
        open=(10.0, 11.0, 12.0, 13.0),
        high=(12.0, 13.0, 14.0, 15.0),
        low=(9.0, 10.0, 11.0, 12.0),
        close=(11.0, 12.0, 13.0, 14.0),
        volume=data.volume,
    )
    atr = study._atr(data)
    assert atr[0] == 3.0
    assert atr[1] == pytest.approx((13 * 3 + 3) / 14)


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [("1h", ((12, 12), (24, 24), (48, 48))), ("4h", ((12, 3), (24, 6), (48, 12)))],
)
def test_physical_scale_radius_mapping(timeframe: str, expected: tuple[tuple[int, int], ...]) -> None:
    assert study._scale_radii(timeframe) == expected


def test_pivot_confirmation_is_not_available_before_confirmation_bar() -> None:
    data = _input(rows=60)
    pivot = study._make_pivot(
        data,
        study._atr(data),
        "support",
        position=20,
        radius=3,
        scale_hours=12,
        checkpoint=study._datetime_from_ns(data.timestamps[22]),
    )
    assert pivot is None
    pivot = study._make_pivot(
        data,
        study._atr(data),
        "support",
        position=20,
        radius=3,
        scale_hours=12,
        checkpoint=study._datetime_from_ns(data.timestamps[24]),
    )
    assert pivot is not None
    assert pivot.available_at <= study._datetime_from_ns(data.timestamps[24])


def test_plateau_keeps_middle_candidate_at_scale() -> None:
    data = _input(rows=40)
    low = list(data.low)
    low[20:24] = [90.0] * 4
    data = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
        timestamps=data.timestamps,
        open=data.open,
        high=data.high,
        low=tuple(low),
        close=data.close,
        volume=data.volume,
    )
    pivots = study._hierarchical_pivots(
        data,
        prefix_last_position=39,
        checkpoint=_datetime_from_data(data, 39),
    )
    positions = [pivot.source_position for pivot in pivots if pivot.role == "support"]
    assert 21 in positions or 22 in positions or 23 in positions


def test_adjacent_unequal_extrema_are_not_one_plateau() -> None:
    groups = study._plateau_groups(
        (10, 11, 12, 15),
        price_at=lambda position: {10: 90.0, 11: 91.0, 12: 91.0, 15: 89.0}[position],
    )
    assert groups == ((10,), (11, 12), (15,))


def _datetime_from_data(data: ProviderInput, position: int) -> datetime:
    return study._datetime_from_ns(data.timestamps[position])


def _manual_pivot(
    data: ProviderInput,
    position: int,
    price: float,
    *,
    role: str = "support",
) -> study.Pivot:
    pivot_time = _datetime_from_data(data, position)
    confirmation_time = _datetime_from_data(data, position + 1)
    return study.Pivot(
        pivot_id=f"pivot-{position}-{price}",
        asset=data.asset,
        timeframe=data.timeframe,
        role=role,
        source_position=position,
        pivot_time=pivot_time,
        confirmation_time=confirmation_time,
        available_at=confirmation_time + timedelta(seconds=study._interval(data)),
        price=price,
        scale_hours=12,
        source_input_identity=data.input_identity,
    )


def test_line_projection_and_distance_use_checkpoint_instant() -> None:
    data = _input(rows=30)
    first = _manual_pivot(data, 2, 100.0)
    second = _manual_pivot(data, 4, 102.0)
    third = _manual_pivot(data, 6, 104.0)
    geometry = study._geometry(first, second)
    seed = study.Seed(
        seed_id="seed",
        role="support",
        first=first,
        second=second,
        touches=(first, second, third),
        geometry=geometry,
        current_valid=True,
        current_distance_atr=0.0,
        checkpoint_close=data.close[10],
        checkpoint_atr=study._atr(data)[10],
    )
    checkpoint = _datetime_from_data(data, 11)
    line = study._line_record(
        provider_id=study.PRIMARY_PROVIDERS[0],
        seed=seed,
        geometry=geometry,
        pivots=seed.touches,
        checkpoint=checkpoint,
        data=data,
        prefix_last_position=10,
        provider_evidence={"method": study.PRIMARY_PROVIDERS[0]},
        anchor_pivots=(first, second),
    )
    expected = geometry.value_at(checkpoint)
    assert line["projected_price_at_checkpoint"] == pytest.approx(expected)
    assert expected != pytest.approx(geometry.value_at(_datetime_from_data(data, 10)))
    assert line["current_distance_atr"] == pytest.approx(
        abs(data.close[10] - expected) / study._atr(data)[10]
    )


def test_seed_distance_uses_checkpoint_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _input(rows=300)
    pivots = tuple(
        _manual_pivot(data, position, 100.0 + position * 0.005)
        for position in (2, 100, 200)
    )
    monkeypatch.setattr(study, "_hierarchical_pivots", lambda *_args, **_kwargs: pivots)
    monkeypatch.setattr(
        study,
        "_sustained_breach",
        lambda *_args, **_kwargs: (False, None),
    )
    checkpoint = _datetime_from_data(data, 251)
    seeds = study._seed_pool(data, prefix_last_position=250, checkpoint=checkpoint)
    assert seeds["support"]
    seed = seeds["support"][0]
    expected = abs(
        data.close[250] - seed.geometry.value_at(checkpoint)
    ) / study._atr(data)[250]
    assert seed.current_distance_atr == pytest.approx(expected)


def test_theil_sen_validity_starts_after_final_inlier(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _input(rows=300)
    pivots = tuple(
        _manual_pivot(data, position, 100.0 + position * 0.005)
        for position in (2, 100, 200)
    )
    seed = study.Seed(
        seed_id="seed",
        role="support",
        first=pivots[0],
        second=pivots[1],
        touches=pivots,
        geometry=study._geometry(pivots[0], pivots[1]),
        current_valid=True,
        current_distance_atr=0.0,
        checkpoint_close=data.close[250],
        checkpoint_atr=study._atr(data)[250],
    )
    starts: list[int] = []
    monkeypatch.setattr(
        study,
        "_sustained_breach",
        lambda _data, _atr, _geometry, _role, start, _end: (
            starts.append(start) or (False, None)
        ),
    )
    record = study._theil_sen_candidate(
        seed,
        data=data,
        atr=study._atr(data),
        checkpoint=_datetime_from_data(data, 251),
        prefix_last_position=250,
    )
    assert record is not None
    assert starts == [pivots[-1].source_position + 1]


def test_two_close_breaches_invalidate_and_wick_crossing_does_not() -> None:
    data = _input(rows=30)
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 2),
        end_time=_datetime_from_data(data, 4),
        start_price=99.0,
        end_price=99.0,
    )
    atr = study._atr(data)
    invalid, position = study._sustained_breach(data, atr, geometry, "support", 5, 20)
    assert invalid is False
    assert position is None
    bad_close = list(data.close)
    bad_close[8] = 90.0
    bad_close[9] = 90.0
    bad_low = list(data.low)
    bad_low[8] = 89.0
    bad_low[9] = 89.0
    bad = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
        timestamps=data.timestamps,
        open=tuple(bad_close),
        high=data.high,
        low=tuple(bad_low),
        close=tuple(bad_close),
        volume=data.volume,
    )
    invalid, position = study._sustained_breach(bad, study._atr(bad), geometry, "support", 5, 20)
    assert invalid is True
    assert position == 9


def test_causal_prefix_ignores_future_rows() -> None:
    data = _input(rows=100)
    checkpoint = _datetime_from_data(data, 60)
    first_data = study._causal_input(data, prefix_last_position=59, checkpoint=checkpoint)
    first = study._hierarchical_pivots(first_data, prefix_last_position=59, checkpoint=checkpoint)
    future = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at + timedelta(hours=40),
        confirmed_through=data.confirmed_through + timedelta(hours=40),
        timestamps=data.timestamps + tuple(data.timestamps[-1] + study.NANOSECONDS * (i + 1) * 3600 for i in range(40)),
        open=data.open + tuple(data.open[-1] for _ in range(40)),
        high=data.high + tuple(data.high[-1] for _ in range(40)),
        low=data.low + tuple(data.low[-1] for _ in range(40)),
        close=data.close + tuple(data.close[-1] for _ in range(40)),
        volume=data.volume + tuple(data.volume[-1] for _ in range(40)),
    )
    second_data = study._causal_input(future, prefix_last_position=59, checkpoint=checkpoint)
    second = study._hierarchical_pivots(second_data, prefix_last_position=59, checkpoint=checkpoint)
    assert [pivot.to_dict() for pivot in first] == [pivot.to_dict() for pivot in second]


def test_provider_and_controls_are_deterministic() -> None:
    data = _input(rows=160)
    checkpoint = _datetime_from_data(data, 120)
    cp = study.ScopeCheckpoint("btcusdt_1h", 1, checkpoint, data, 119)
    first = study._run_checkpoint(cp)
    second = study._run_checkpoint(cp)
    assert first["derivation_identity"] == second["derivation_identity"]
    assert first["outputs"] == second["outputs"]


def test_scope_method_set_executes_only_requested_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _input(rows=160)
    checkpoint = _datetime_from_data(data, 121)
    cp = study.ScopeCheckpoint("btcusdt_1h", 1, checkpoint, data, 120)
    calls: list[str] = []

    def provider(name: str):
        def run(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
            calls.append(name)
            return []

        return run

    monkeypatch.setattr(study, "_hierarchical_provider", provider(study.PRIMARY_PROVIDERS[0]))
    monkeypatch.setattr(study, "_theil_sen_provider", provider(study.PRIMARY_PROVIDERS[1]))
    monkeypatch.setattr(
        study,
        "_control_provider",
        lambda *_args, provider_id, **_kwargs: (calls.append(provider_id) or []),
    )
    result = study._run_checkpoint(cp, method_ids=(study.PRIMARY_PROVIDERS[1],))
    assert calls == [study.PRIMARY_PROVIDERS[1]]
    assert tuple(result["outputs"]) == (study.PRIMARY_PROVIDERS[1],)


def test_matched_control_excludes_extra_role_and_preserves_one_sample_per_key() -> None:
    runs = [
        {
            "checkpoint_index": 7,
            "outputs": {
                study.PRIMARY_PROVIDERS[0]: [{"role": "support"}],
                study.CONTROL_PROVIDERS[0]: [
                    {"role": "support"},
                    {"role": "resistance"},
                ],
            },
        }
    ]
    primary, control, keys = study._matched_control_lines(
        runs,
        primary_provider_id=study.PRIMARY_PROVIDERS[0],
        control_provider_id=study.CONTROL_PROVIDERS[0],
    )
    assert len(primary) == len(control) == 1
    assert keys == ((7, "support"),)


def test_matched_control_missing_same_role_blocks() -> None:
    runs = [
        {
            "checkpoint_index": 7,
            "outputs": {
                study.PRIMARY_PROVIDERS[0]: [{"role": "support"}],
                study.CONTROL_PROVIDERS[0]: [{"role": "resistance"}],
            },
        }
    ]
    with pytest.raises(study.StudyError, match="missing checkpoint-role"):
        study._matched_control_lines(
            runs,
            primary_provider_id=study.PRIMARY_PROVIDERS[0],
            control_provider_id=study.CONTROL_PROVIDERS[0],
        )


def test_matched_control_two_roles_matches_two_samples() -> None:
    runs = [
        {
            "checkpoint_index": 7,
            "outputs": {
                study.PRIMARY_PROVIDERS[0]: [
                    {"role": "support"},
                    {"role": "resistance"},
                ],
                study.CONTROL_PROVIDERS[0]: [
                    {"role": "resistance"},
                    {"role": "support"},
                ],
            },
        }
    ]
    primary, control, keys = study._matched_control_lines(
        runs,
        primary_provider_id=study.PRIMARY_PROVIDERS[0],
        control_provider_id=study.CONTROL_PROVIDERS[0],
    )
    assert len(primary) == len(control) == 2
    assert keys == ((7, "resistance"), (7, "support"))


def _future_reaction_case(
    *, role: str, case: str
) -> tuple[ProviderInput, datetime]:
    data = _input(rows=180)
    checkpoint_position = 60
    open_values = list(data.open)
    close_values = list(data.close)
    low_values = list(data.low)
    high_values = list(data.high)
    for position in range(checkpoint_position + 1, len(data.timestamps)):
        open_values[position] = 100.0
        close_values[position] = 100.0
        low_values[position] = 99.9
        high_values[position] = 100.1
    first = checkpoint_position + 1
    second = checkpoint_position + 2
    if role == "support":
        if case == "contact_only":
            high_values[first] = 103.0
        elif case == "next_reaction":
            high_values[second] = 103.0
        elif case == "sustained_breach":
            for position in (second, second + 1):
                open_values[position] = 98.0
                close_values[position] = 98.0
                low_values[position] = 97.0
                high_values[position] = 99.0
    else:
        if case == "contact_only":
            low_values[first] = 97.0
        elif case == "next_reaction":
            low_values[second] = 97.0
        elif case == "sustained_breach":
            for position in (second, second + 1):
                open_values[position] = 102.0
                close_values[position] = 102.0
                low_values[position] = 101.0
                high_values[position] = 103.0
    return (
        ProviderInput(
            asset=data.asset,
            timeframe=data.timeframe,
            observed_at=data.observed_at,
            confirmed_through=data.confirmed_through,
            timestamps=data.timestamps,
            open=tuple(open_values),
            high=tuple(high_values),
            low=tuple(low_values),
            close=tuple(close_values),
            volume=data.volume,
        ),
        _datetime_from_data(data, checkpoint_position),
    )


@pytest.mark.parametrize("role", ["support", "resistance"])
def test_contact_candle_cannot_produce_reaction(role: str) -> None:
    data, checkpoint = _future_reaction_case(role=role, case="contact_only")
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 0),
        end_time=_datetime_from_data(data, 1),
        start_price=100.0,
        end_price=100.0,
    )
    result = study._future_evaluation(
        {"role": role, "geometry": geometry.to_dict()},
        data=data,
        prefix_last_position=60,
        checkpoint=checkpoint,
    )
    assert result["24"]["first_contact_offset_bars"] == 1
    assert result["24"]["has_role_consistent_reaction"] is False


def test_next_candle_can_produce_support_reaction() -> None:
    data, checkpoint = _future_reaction_case(role="support", case="next_reaction")
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 0),
        end_time=_datetime_from_data(data, 1),
        start_price=100.0,
        end_price=100.0,
    )
    result = study._future_evaluation(
        {"role": "support", "geometry": geometry.to_dict()},
        data=data,
        prefix_last_position=60,
        checkpoint=checkpoint,
    )
    assert result["24"]["has_role_consistent_reaction"] is True


def test_next_candle_can_produce_resistance_reaction() -> None:
    data, checkpoint = _future_reaction_case(role="resistance", case="next_reaction")
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 0),
        end_time=_datetime_from_data(data, 1),
        start_price=100.0,
        end_price=100.0,
    )
    result = study._future_evaluation(
        {"role": "resistance", "geometry": geometry.to_dict()},
        data=data,
        prefix_last_position=60,
        checkpoint=checkpoint,
    )
    assert result["24"]["has_role_consistent_reaction"] is True


@pytest.mark.parametrize("role", ["support", "resistance"])
def test_reaction_after_sustained_breach_is_rejected(role: str) -> None:
    data, checkpoint = _future_reaction_case(role=role, case="sustained_breach")
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 0),
        end_time=_datetime_from_data(data, 1),
        start_price=100.0,
        end_price=100.0,
    )
    result = study._future_evaluation(
        {"role": role, "geometry": geometry.to_dict()},
        data=data,
        prefix_last_position=60,
        checkpoint=checkpoint,
    )
    assert result["24"]["first_sustained_breach_offset_bars"] is not None
    assert result["24"]["has_role_consistent_reaction"] is False


def test_holdout_method_set_excludes_losing_primary_and_hash_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _input(rows=160)
    cp = study.ScopeCheckpoint(
        "btcusdt_1h", 1, _datetime_from_data(data, 121), data, 120
    )
    calls: list[str] = []
    monkeypatch.setattr(
        study,
        "_hierarchical_provider",
        lambda *_args, **_kwargs: (calls.append(study.PRIMARY_PROVIDERS[0]) or []),
    )
    monkeypatch.setattr(
        study,
        "_theil_sen_provider",
        lambda *_args, **_kwargs: pytest.fail("losing primary executed"),
    )
    monkeypatch.setattr(
        study,
        "_control_provider",
        lambda *_args, provider_id, **_kwargs: (
            calls.append(provider_id) or []
        )
        if provider_id == study.CONTROL_PROVIDERS[0]
        else pytest.fail("hash control executed"),
    )
    requested = (study.PRIMARY_PROVIDERS[0], study.CONTROL_PROVIDERS[0])
    study._run_checkpoint(cp, method_ids=requested)
    assert calls == list(requested)


def test_projection_slope_fallback_is_continuation() -> None:
    data = _input(rows=40)
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 2),
        end_time=_datetime_from_data(data, 4),
        start_price=100.0,
        end_price=100.0,
    )
    old = {
        "line_id": "old",
        "role": "support",
        "anchor_pivots": [{"pivot_id": "old-anchor"}],
        "geometry": geometry.to_dict(),
        "slope_per_second": geometry.slope_per_second,
    }
    new = {
        **old,
        "line_id": "new",
        "anchor_pivots": [{"pivot_id": "new-anchor"}],
    }
    checkpoint = _datetime_from_data(data, 21)
    events = study._stability(
        {"checkpoint": _iso_for_test(checkpoint), "outputs": {study.PRIMARY_PROVIDERS[0]: [old]}},
        {"checkpoint": _iso_for_test(checkpoint), "prefix_last_position": 20, "outputs": {study.PRIMARY_PROVIDERS[0]: [new]}},
        data=data,
    )
    assert events[0]["state"] == "continuation"
    assert events[0]["anchor_jaccard"] == 0.0


def _iso_for_test(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_replacement_state_lowers_continuation_rate() -> None:
    runs = [
        {
            "provider_stability": {
                study.PRIMARY_PROVIDERS[0]: [{"state": "continuation"}]
            }
        },
        {
            "provider_stability": {
                study.PRIMARY_PROVIDERS[0]: [{"state": "replacement"}]
            }
        },
    ]
    continuation, replacement = study._continuation_state_counts(
        runs, study.PRIMARY_PROVIDERS[0]
    )
    assert (continuation, replacement) == (1, 1)
    assert continuation / (continuation + replacement) == 0.5


def _synthetic_metric(
    *,
    successes: int,
    evaluable: int,
    control_successes: int,
    control_evaluable: int,
) -> dict[str, object]:
    outcome = {
        "sample_count": evaluable,
        "evaluable_count": evaluable,
        "survival_rate": successes / evaluable,
        "survival_success_count": successes,
        "zone_contact_and_survival_rate": successes / evaluable,
        "zone_contact_and_survival_success_count": successes,
        "reaction_rate": successes / evaluable,
        "reaction_success_count": successes,
        "contact_rate": successes / evaluable,
        "contact_success_count": successes,
    }
    matched_outcomes = {
        str(horizon): {
            "sample_count": control_evaluable,
            "evaluable_count": control_evaluable,
            "survival_rate": control_successes / control_evaluable,
            "survival_success_count": control_successes,
            "zone_contact_and_survival_rate": control_successes / control_evaluable,
            "zone_contact_and_survival_success_count": control_successes,
            "reaction_rate": control_successes / control_evaluable,
            "reaction_success_count": control_successes,
            "contact_rate": control_successes / control_evaluable,
            "contact_success_count": control_successes,
        }
        for horizon in study.HORIZONS_HOURS
    }
    return {
        "coverage": {"support": 1.0, "resistance": 1.0, "both": 1.0},
        "touch_count": {"median": 3.0},
        "structural_span_hours": {"median": 168.0},
        "channel_inversion_rate": 0.0,
        "channel_inversion_count": 0,
        "current_validity_rate": 1.0,
        "current_distance_atr": {"median": 1.0},
        "adjacent_continuation_rate": 0.8,
        "outcomes": {str(horizon): dict(outcome) for horizon in study.HORIZONS_HOURS},
        "deltas_vs_latest_wide": {
            str(horizon): {
                "survival_delta": successes / evaluable - control_successes / control_evaluable,
                "zone_contact_and_survival_delta": successes / evaluable - control_successes / control_evaluable,
                "reaction_delta": successes / evaluable - control_successes / control_evaluable,
            }
            for horizon in study.HORIZONS_HOURS
        },
        "matched_latest_wide_sample_keys": [
            [index, "support"] for index in range(control_evaluable)
        ],
        "matched_latest_wide_sample_count": control_evaluable,
        "matched_latest_wide_outcomes": matched_outcomes,
        "matched_latest_wide_control_id": study.CONTROL_PROVIDERS[0],
        "structural_gate_passed": True,
        "structural_rejection_reasons": [],
    }


def test_pooled_utility_uses_raw_counts() -> None:
    dataset_metrics = {
        "one": {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=9, evaluable=10, control_successes=0, control_evaluable=1
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=0, evaluable=1, control_successes=0, control_evaluable=1
            ),
        },
        "two": {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=0, evaluable=1, control_successes=1, control_evaluable=10
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=1, evaluable=10, control_successes=1, control_evaluable=10
            ),
        },
    }
    aggregate = study._aggregate_metrics(
        dataset_metrics, study.PRIMARY_PROVIDERS[0], phase="validation"
    )
    assert aggregate["outcomes"]["96"]["survival_success_count"] == 9
    assert aggregate["pooled_96_survival_delta"] == pytest.approx(8 / 11)


def test_pooled_utility_uses_matched_control_counts_not_full_control_counts() -> None:
    dataset_metrics = {}
    for dataset_id, successes in (("one", 10), ("two", 0)):
        dataset_metrics[dataset_id] = {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=successes,
                evaluable=10,
                control_successes=0,
                control_evaluable=10,
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=10,
                evaluable=10,
                control_successes=10,
                control_evaluable=10,
            ),
        }
    aggregate = study._aggregate_metrics(
        dataset_metrics, study.PRIMARY_PROVIDERS[0], phase="validation"
    )
    assert aggregate["matched_latest_wide_sample_count"] == 20
    assert aggregate["pooled_96_survival_delta"] == pytest.approx(0.5)


def test_validation_requires_every_dataset_structural_gate() -> None:
    dataset_metrics = {
        dataset_id: {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=1, evaluable=1, control_successes=0, control_evaluable=1
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=0, evaluable=1, control_successes=0, control_evaluable=1
            ),
        }
        for dataset_id in ("one", "two", "three", "four")
    }
    dataset_metrics["four"][study.PRIMARY_PROVIDERS[0]]["structural_gate_passed"] = False
    dataset_metrics["four"][study.PRIMARY_PROVIDERS[0]]["structural_rejection_reasons"] = [
        "support_coverage_below_0.70"
    ]
    aggregate = study._aggregate_metrics(
        dataset_metrics, study.PRIMARY_PROVIDERS[0], phase="validation"
    )
    assert aggregate["all_dataset_structural_gates_passed"] is False
    assert aggregate["gate_passed"] is False


def test_temporal_gate_requires_all_temporal_conditions() -> None:
    metric = {
        "checkpoint_count": 5,
        "support_present_count": 4,
        "resistance_present_count": 4,
        "both_present_count": 3,
        "coverage": {"support": 0.8, "resistance": 0.8, "both": 0.6},
        "touch_count": {"median": 3},
        "structural_span_hours": {"median": 168},
        "channel_inversion_count": 0,
        "current_validity_rate": 1.0,
        "current_distance_atr": {"median": 1.0},
        "adjacent_continuation_rate": 0.4,
    }
    assert study._structural_gate(metric, phase="temporal")[0] is True
    metric["touch_count"]["median"] = 0
    metric["current_distance_atr"]["median"] = 999.0
    assert study._structural_gate(metric, phase="temporal")[0] is True
    metric["both_present_count"] = 2
    assert study._structural_gate(metric, phase="temporal")[0] is False


def test_zero_values_are_not_treated_as_missing() -> None:
    metric = {
        "coverage": {"support": 0.7, "resistance": 0.7, "both": 0.6},
        "touch_count": {"median": 3},
        "structural_span_hours": {"median": 168},
        "channel_inversion_count": 0,
        "current_validity_rate": 1.0,
        "current_distance_atr": {"median": 0.0},
        "adjacent_continuation_rate": 0.0,
    }
    passed, reasons = study._structural_gate(metric, phase="validation")
    assert passed is False
    assert "median_distance_above_6atr" not in reasons
    assert "adjacent_continuation_below_0.50" in reasons


def test_missing_worst_dataset_delta_fails_without_type_error() -> None:
    dataset_metrics = {
        dataset_id: {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=1, evaluable=1, control_successes=1, control_evaluable=1
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=1, evaluable=1, control_successes=1, control_evaluable=1
            ),
        }
        for dataset_id in study.VALIDATION_DATASETS
    }
    dataset_metrics[study.VALIDATION_DATASETS[0]][study.PRIMARY_PROVIDERS[0]][
        "deltas_vs_latest_wide"
    ]["96"]["survival_delta"] = None
    aggregate = study._aggregate_metrics(
        dataset_metrics, study.PRIMARY_PROVIDERS[0], phase="validation"
    )
    assert aggregate["worst_dataset_96_survival_delta"] is None
    assert aggregate["gate_passed"] is False


def test_zero_utility_delta_and_ranking_values_remain_zero() -> None:
    dataset_metrics = {
        dataset_id: {
            study.PRIMARY_PROVIDERS[0]: _synthetic_metric(
                successes=0, evaluable=1, control_successes=0, control_evaluable=1
            ),
            study.CONTROL_PROVIDERS[0]: _synthetic_metric(
                successes=0, evaluable=1, control_successes=0, control_evaluable=1
            ),
        }
        for dataset_id in study.VALIDATION_DATASETS
    }
    aggregate = study._aggregate_metrics(
        dataset_metrics, study.PRIMARY_PROVIDERS[0], phase="validation"
    )
    assert aggregate["pooled_96_survival_delta"] == 0.0
    ranking = study._rank_validation({study.PRIMARY_PROVIDERS[0]: aggregate})
    assert ranking[0]["pooled_96_zone_survival_delta"] == 0.0
    assert ranking[0]["pooled_96_reaction_delta"] == 0.0


def test_exact_future_horizon_bar_counts_are_required() -> None:
    data = _input(rows=200)
    checkpoint = _datetime_from_data(data, 100)
    geometry = study.LineGeometry(
        start_time=_datetime_from_data(data, 0),
        end_time=_datetime_from_data(data, 1),
        start_price=100.0,
        end_price=100.0,
    )
    line = {"role": "support", "geometry": geometry.to_dict()}
    result = study._future_evaluation(
        line,
        data=data,
        prefix_last_position=99,
        checkpoint=checkpoint,
    )
    assert set(result) == {"24", "48", "96"}
    truncated = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
        timestamps=data.timestamps[:196],
        open=data.open[:196],
        high=data.high[:196],
        low=data.low[:196],
        close=data.close[:196],
        volume=data.volume[:196],
    )
    with pytest.raises(study.StudyError, match="missing, duplicated, or misaligned"):
        study._future_evaluation(
            line,
            data=truncated,
            prefix_last_position=99,
            checkpoint=checkpoint,
        )


def test_bundle_contract_declares_exact_21_paths() -> None:
    paths = study._expected_artifact_paths()
    assert len(paths) == 21
    assert len(set(paths)) == 21
    assert paths == tuple(sorted(paths))
    assert paths[0] == "cross_scope_summary.csv"
    assert paths[-1] == "validation_lock.json"


def test_validation_lock_binds_sources_and_canonical_bytes(tmp_path: Path) -> None:
    lock = study._validation_lock(
        contract_id=study.CONTRACT_ID,
        dataset_metrics={dataset_id: {} for dataset_id in study.VALIDATION_DATASETS},
        ranking=[],
        winner=None,
    )
    path = tmp_path / "validation_lock.json"
    study._write_json(path, lock)
    study._verify_lock_bytes(path, lock)
    assert set(lock["source_identities"]) == {
        "phase9c2_decision_id",
        "phase9c2_manifest_id",
        "phase9c2_output_inventory_sha256",
        "phase9c2_source_inventory_sha256",
        "phase10c2_replay_contract_id",
        "phase10c2_decision_id",
        "phase10c2_manifest_id",
        "phase10c2_output_inventory_sha256",
        "phase10c2_source_inventory_sha256",
        "phase11s1_contract_id",
        "phase11s1_decision_id",
        "phase11s1_manifest_id",
        "phase11s1_inventory_sha256",
    }


def test_identity_and_geometry_are_timestamp_space() -> None:
    data = _input(rows=30)
    first = study.Pivot("a", data.asset, data.timeframe, "support", 2, _datetime_from_data(data, 2), _datetime_from_data(data, 3), _datetime_from_data(data, 4), 99.0, 12, data.input_identity)
    second = study.Pivot("b", data.asset, data.timeframe, "support", 6, _datetime_from_data(data, 6), _datetime_from_data(data, 7), _datetime_from_data(data, 8), 101.0, 12, data.input_identity)
    geometry = study._geometry(first, second)
    assert geometry.value_at(first.pivot_time) == pytest.approx(99.0)
    assert geometry.value_at(second.pivot_time) == pytest.approx(101.0)


def test_no_forbidden_runtime_imports() -> None:
    tree = ast.parse(Path(study.__file__).read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    modules = {
        node.module
        for node in imports
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module in modules for module in {
        "app.trendlines",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "libs.models.trendline",
        "libs.models.trendline_family",
    })


def test_existing_output_rejected_before_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R1_STUDY", "1")
    monkeypatch.setattr(study, "_run_analysis", lambda _root: pytest.fail("source access"))
    with pytest.raises(FileExistsError):
        study.run_study(output_root=root)


def test_staging_failure_prevents_source_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R1_STUDY", "1")
    monkeypatch.setattr(study, "_prepare_staging", lambda _root: (_ for _ in ()).throw(OSError("stage")))
    monkeypatch.setattr(study, "_load_validation_scope", lambda: pytest.fail("source access"))
    with pytest.raises(OSError, match="stage"):
        study.run_study(output_root=tmp_path / "out")


def test_prepare_staging_creates_missing_parent(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "nested" / "bundle"
    staging = study._prepare_staging(root)
    assert staging.parent == root.parent
    assert staging.is_dir()
    shutil.rmtree(staging)


def test_publish_is_atomic_from_missing_parent(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "bundle"
    staging = study._prepare_staging(root)
    (staging / "marker").write_text("ok")
    study._publish(root, staging)
    assert (root / "marker").read_text() == "ok"
    assert not staging.exists()


def test_analysis_failure_cleans_prepared_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        study,
        "_validated_contract",
        lambda: (study._contract_payload(), study.CONTRACT_ID),
    )
    monkeypatch.setattr(study, "_validate_manifest", lambda *args, **kwargs: (_ for _ in ()).throw(study.StudyError("replay")))
    root = tmp_path / "failure" / "bundle"
    with pytest.raises(study.StudyError, match="replay"):
        study._run_analysis(root)
    assert not root.exists()
    assert not list(root.parent.glob(f".{root.name}.*"))


def _copy_external_bundle(tmp_path: Path) -> Path:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external generated bundle disabled")
    if not study.OUTPUT_ROOT.exists():
        pytest.skip("generated bundle unavailable")
    return Path(shutil.copytree(study.OUTPUT_ROOT, tmp_path / "bundle"))


def _rebind_manifest(root: Path) -> None:
    manifest = study._load_json(root / "manifest.json")
    members = tuple(item for item in study._inventory(root) if item["path"] != "manifest.json")
    payload = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifest_id", "members", "member_count", "output_inventory_sha256"}
    }
    payload.update(
        {
            "member_count": len(members),
            "members": list(members),
            "output_inventory_sha256": study._inventory_sha256(members),
        }
    )
    (root / "manifest.json").write_bytes(
        study._canonical_bytes({
            **payload,
            "manifest_id": study.deterministic_hash(study.MANIFEST_NAMESPACE, payload),
        })
    )


def test_external_bundle_verifies_read_only() -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external generated bundle disabled")
    assert study._verify_bundle(study.OUTPUT_ROOT)["study_status"] == "NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST"


def test_forged_pivot_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    membership_path = root / "datasets" / "btcusdt_4h" / "checkpoint_membership.json"
    membership = study._load_json(membership_path)
    line = membership["checkpoints"][0]["outputs"][study.PRIMARY_PROVIDERS[0]][0]
    line["touch_or_inlier_pivots"][0]["price"] += 1.0
    membership_path.write_bytes(study._canonical_bytes(membership))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError):
        study._verify_bundle(root)


@pytest.mark.parametrize("mutation", ["ranked_seed", "current_valid", "theil_geometry", "seed_pool", "provider_rank"])
def test_forged_checkpoint_replay_fields_rejected_after_rebinding(
    tmp_path: Path, mutation: str
) -> None:
    root = _copy_external_bundle(tmp_path)
    membership_path = root / "datasets" / "btcusdt_4h" / "checkpoint_membership.json"
    membership = study._load_json(membership_path)
    checkpoint = membership["checkpoints"][0]
    if mutation == "seed_pool":
        checkpoint["seed_pool_counts"]["support"] += 1
    else:
        provider_id = study.PRIMARY_PROVIDERS[0]
        lines = checkpoint["outputs"].get(provider_id, [])
        if not lines:
            pytest.skip("external fixture has no hierarchical line")
        line = lines[0]
        if mutation == "ranked_seed":
            line["provider_evidence"]["seed_id"] = "forged-seed"
        elif mutation == "current_valid":
            line["current_valid"] = not line["current_valid"]
        elif mutation == "provider_rank":
            original = line["provider_evidence"]["rank"][0]
            line["provider_evidence"]["rank"][0] = original + 1
            assert line["provider_evidence"]["rank"][0] != original
        else:
            theil_lines = checkpoint["outputs"].get(study.PRIMARY_PROVIDERS[1], [])
            if not theil_lines:
                pytest.skip("external fixture has no Theil-Sen line")
            theil_lines[0]["geometry"]["end_price"] += 1.0
    membership["membership_id"] = study.deterministic_hash(
        "phase11r1_membership", study._without_id(membership, "membership_id")
    )
    membership_path.write_bytes(study._canonical_bytes(membership))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError):
        study._verify_bundle(root)


def test_forged_cross_scope_summary_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / "cross_scope_summary.csv"
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b"X\n")
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="summary CSV"):
        study._verify_bundle(root)


def test_forged_temporal_summary_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / "temporal_summary.csv"
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b"X\n")
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="summary CSV"):
        study._verify_bundle(root)


def test_exact_bundle_paths_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    (root / "temporal_summary.csv").unlink()
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="artifact paths"):
        study._verify_bundle(root)


def test_forged_provider_metrics_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / "datasets" / "btcusdt_4h" / "provider_metrics.json"
    metrics = study._load_json(path)
    metrics[study.PRIMARY_PROVIDERS[0]]["coverage"]["support"] = 0.0
    path.write_bytes(study._canonical_bytes(metrics))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="metrics"):
        study._verify_bundle(root)


def test_forged_validation_lock_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / "validation_lock.json"
    lock = study._load_json(path)
    lock["winner_provider_id"] = study.PRIMARY_PROVIDERS[0]
    path.write_bytes(study._canonical_bytes(lock))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="lock"):
        study._verify_bundle(root)


def test_forged_decision_rejected_after_manifest_rebinding(tmp_path: Path) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / "decision.json"
    decision = study._load_json(path)
    decision["study_status"] = "INDEPENDENT_SPARSE_PROVIDER_PROMOTION_CANDIDATE"
    path.write_bytes(study._canonical_bytes(decision))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError, match="decision identity"):
        study._verify_bundle(root)


def test_unopened_holdout_is_explicit() -> None:
    membership, metrics = study._unopened_dataset("suiusdt_1h", reason="NO_VALIDATION_FINALIST")
    assert membership["status"] == "UNOPENED"
    assert metrics["reason"] == "NO_VALIDATION_FINALIST"
