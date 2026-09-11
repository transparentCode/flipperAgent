from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import fsum, inf, nextafter
from random import Random

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.invocation import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.ta.volume_profile_geometry import (
    VolumeProfileBar,
    VolumeProfileGeometryRequest,
    _aggregate_equal,
    _aggregate_operation_budget,
    compute_volume_profile_geometry,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bars() -> tuple[VolumeProfileBar, ...]:
    return (
        VolumeProfileBar(_START, 1.0, 3.0, 1.0, 2.0, 10.0),
        VolumeProfileBar(
            _START + timedelta(hours=1),
            2.0,
            4.0,
            2.0,
            3.0,
            5.0,
        ),
        VolumeProfileBar(
            _START + timedelta(hours=2),
            3.0,
            4.0,
            3.0,
            3.0,
            0.0,
        ),
    )


def _request(
    *, row_count: int = 3, value_area_fraction: float = 0.7
) -> VolumeProfileGeometryRequest:
    bars = _bars()
    return VolumeProfileGeometryRequest(
        bars=bars,
        market_as_of=bars[-1].closed_at,
        row_count=row_count,
        value_area_fraction=value_area_fraction,
    )


def _two_bar_roundoff_request() -> VolumeProfileGeometryRequest:
    bars = (
        VolumeProfileBar(
            _START,
            58.98846482623204,
            90.31559569514134,
            15.210033797683325,
            72.92435339154655,
            9440962.888190709,
        ),
        VolumeProfileBar(
            _START + timedelta(hours=1),
            63.16306781746646,
            67.67859817261935,
            59.850121678203365,
            60.99389871516891,
            1.9300545045114127e-06,
        ),
    )
    return VolumeProfileGeometryRequest(
        bars=bars,
        market_as_of=bars[-1].closed_at,
        row_count=19,
        value_area_fraction=0.7,
    )


def _unit_row_profile_request() -> VolumeProfileGeometryRequest:
    bars = (
        VolumeProfileBar(_START, 1.0, 1.0, 1.0, 1.0, 1.0),
        VolumeProfileBar(
            _START + timedelta(hours=1),
            2.0,
            2.0,
            2.0,
            2.0,
            2.0,
        ),
        VolumeProfileBar(
            _START + timedelta(hours=2),
            3.0,
            3.0,
            3.0,
            3.0,
            1.0,
        ),
    )
    return VolumeProfileGeometryRequest(
        bars=bars,
        market_as_of=bars[-1].closed_at,
        row_count=3,
        value_area_fraction=0.75,
    )


def _context(cutoff: datetime, *, source_available_at: datetime | None = None):
    series = AnalysisSeriesIdentity(
        asset="BTCUSDT",
        venue="fixture",
        instrument_id="fixture:BTCUSDT",
        timeframe="1h",
    )
    return AnalysisInvocationContext(
        source=AnalysisSourceAttestation(
            series=series,
            source_type="fixture",
            source_provider=None,
            source_timeframe=None,
            source_revision="volume-profile-test",
            source_slice_sha256="d" * 64,
            source_available_at=source_available_at or cutoff,
            volume_unit="base_asset",
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_uniform_overlap_allocation_conserves_volume_and_classifies_up() -> None:
    snapshot = compute_volume_profile_geometry(_request())

    assert tuple(row.total_volume for row in snapshot.rows) == (5.0, 7.5, 2.5)
    assert snapshot.total_volume == 15.0
    assert snapshot.total_up_volume == 15.0
    assert snapshot.total_down_volume == 0.0
    assert sum(row.total_volume for row in snapshot.rows) == sum(
        bar.volume for bar in _bars()
    )


def test_down_volume_uses_strict_close_below_open_classification() -> None:
    bars = list(_bars())
    bars[0] = replace(bars[0], open=2.5, close=1.5)
    request = replace(_request(), bars=tuple(bars))
    snapshot = compute_volume_profile_geometry(request)

    assert snapshot.total_down_volume == 10.0
    assert snapshot.total_up_volume == 5.0


def test_flat_bar_goes_to_one_containing_row_and_global_high_is_final_row() -> None:
    bars = (
        VolumeProfileBar(_START, 1.0, 1.0, 1.0, 1.0, 2.0),
        VolumeProfileBar(_START + timedelta(hours=1), 1.0, 3.0, 1.0, 2.0, 4.0),
    )
    snapshot = compute_volume_profile_geometry(
        VolumeProfileGeometryRequest(bars, bars[-1].closed_at, 2, 1.0)
    )
    assert snapshot.rows[-1].total_volume == 2.0
    assert snapshot.rows[0].total_volume == 4.0


def test_value_area_expands_by_volume_and_stops_before_overshoot() -> None:
    snapshot = compute_volume_profile_geometry(_request(value_area_fraction=0.9))

    assert snapshot.poc_row_index == 1
    assert snapshot.value_area_row_indices == (0, 1)
    assert snapshot.value_area_low == snapshot.rows[0].low
    assert snapshot.value_area_high == snapshot.rows[1].high


def test_value_area_equal_volume_equal_distance_prefers_above() -> None:
    bars = (
        VolumeProfileBar(_START, 1.0, 2.0, 1.0, 2.0, 1.0),
        VolumeProfileBar(_START + timedelta(hours=1), 2.0, 3.0, 2.0, 3.0, 2.0),
        VolumeProfileBar(_START + timedelta(hours=2), 3.0, 4.0, 3.0, 4.0, 1.0),
    )
    snapshot = compute_volume_profile_geometry(
        VolumeProfileGeometryRequest(bars, bars[-1].closed_at, 3, 0.75)
    )
    assert snapshot.poc_row_index == 1
    assert snapshot.value_area_row_indices == (1, 2)


def test_poc_tie_chooses_lower_index_and_poc_alone_can_meet_target() -> None:
    bars = (
        VolumeProfileBar(_START, 1.0, 2.0, 1.0, 2.0, 4.0),
        VolumeProfileBar(_START + timedelta(hours=1), 2.0, 3.0, 2.0, 3.0, 4.0),
    )
    snapshot = compute_volume_profile_geometry(
        VolumeProfileGeometryRequest(bars, bars[-1].closed_at, 2, 0.5)
    )
    assert snapshot.poc_row_index == 0
    assert snapshot.value_area_row_indices == (0,)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, bars=()),
        lambda request: replace(request, row_count=True),
        lambda request: replace(request, row_count=0),
        lambda request: replace(request, value_area_fraction=0.0),
        lambda request: replace(request, value_area_fraction=1.1),
        lambda request: replace(
            request,
            bars=(VolumeProfileBar(_START, 1.0, 1.0, 1.0, 1.0, 1.0),),
        ),
    ],
)
def test_invalid_profile_requests_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_request())


def test_snapshot_rejects_forged_poc_value_area_or_row_total() -> None:
    snapshot = compute_volume_profile_geometry(_request())
    with pytest.raises(ValueError):
        replace(snapshot, poc_row_index=0)
    with pytest.raises(ValueError):
        replace(snapshot, value_area_low=999.0)
    with pytest.raises(ValueError):
        replace(
            snapshot,
            rows=(replace(snapshot.rows[0], up_volume=999.0),) + snapshot.rows[1:],
        )
    with pytest.raises(ValueError):
        replace(
            snapshot,
            value_area_row_indices=(0, 1, 2),
            value_area_low=snapshot.rows[0].low,
            value_area_high=snapshot.rows[2].high,
        )


def test_two_bar_profile_accepts_operation_scaled_reassociation_roundoff() -> None:
    request = _two_bar_roundoff_request()
    snapshot = compute_volume_profile_geometry(request)
    input_total = fsum(bar.volume for bar in request.bars)
    row_total = fsum(row.total_volume for row in snapshot.rows)

    assert snapshot.total_volume == row_total
    assert _aggregate_equal(
        input_total,
        snapshot.total_volume,
        _aggregate_operation_budget(len(request.bars), request.row_count),
    )
    assert snapshot.input_bar_count == 2
    assert snapshot.row_count == 19


def test_snapshot_accepts_tight_roundoff_but_rejects_material_total_forgery() -> None:
    snapshot = compute_volume_profile_geometry(_request())
    rounded_total = nextafter(nextafter(snapshot.total_volume, inf), inf)
    rounded_up = nextafter(snapshot.total_up_volume, inf)
    rounded_down = nextafter(snapshot.total_down_volume, inf)

    reconstructed = replace(
        snapshot,
        total_volume=rounded_total,
        total_up_volume=rounded_up,
        total_down_volume=rounded_down,
    )
    assert reconstructed.total_volume == snapshot.total_volume
    assert reconstructed.total_up_volume == snapshot.total_up_volume
    assert reconstructed.total_down_volume == snapshot.total_down_volume
    assert reconstructed.value_area_row_indices == snapshot.value_area_row_indices
    with pytest.raises(ValueError):
        replace(
            snapshot,
            input_bar_count=10**16,
            total_volume=snapshot.total_volume + 1.0,
        )


def test_row_total_is_authority_for_value_area_under_one_ulp_roundoff() -> None:
    snapshot = compute_volume_profile_geometry(_unit_row_profile_request())

    assert tuple(row.total_volume for row in snapshot.rows) == (1.0, 2.0, 1.0)
    assert snapshot.total_volume == 4.0
    assert snapshot.value_area_row_indices == (1, 2)

    rounded_total = nextafter(snapshot.total_volume, -inf)
    reconstructed = replace(snapshot, total_volume=rounded_total)
    assert reconstructed.total_volume == 4.0
    assert reconstructed.value_area_row_indices == (1, 2)

    with pytest.raises(ValueError):
        replace(
            snapshot,
            total_volume=rounded_total,
            value_area_row_indices=(1,),
            value_area_low=snapshot.rows[1].low,
            value_area_high=snapshot.rows[1].high,
        )


def test_forged_input_count_cannot_widen_snapshot_tolerance() -> None:
    snapshot = compute_volume_profile_geometry(_request())
    forged_count = replace(snapshot, input_bar_count=10**16)

    assert forged_count.rows == snapshot.rows
    assert forged_count.value_area_row_indices == snapshot.value_area_row_indices
    with pytest.raises(ValueError):
        replace(
            forged_count,
            total_volume=snapshot.total_volume + 1.0,
        )


def test_randomized_profile_aggregate_stress_is_deterministic() -> None:
    random = Random(0x4B1)
    for case in range(256):
        base = 10.0 ** random.uniform(-3.0, 6.0)
        bars = []
        for index in range(random.randint(2, 8)):
            low = base * (0.5 + 8.0 * random.random())
            high = low + base * (0.01 + 2.0 * random.random())
            open_price = low + (high - low) * random.random()
            close_price = low + (high - low) * random.random()
            volume = 10.0 ** random.uniform(-6.0, 10.0)
            bars.append(
                VolumeProfileBar(
                    _START + timedelta(hours=index),
                    open_price,
                    high,
                    low,
                    close_price,
                    volume,
                )
            )
        request = VolumeProfileGeometryRequest(
            bars=tuple(bars),
            market_as_of=bars[-1].closed_at,
            row_count=random.randint(2, 40),
            value_area_fraction=random.uniform(0.2, 1.0),
        )
        first = compute_volume_profile_geometry(request)
        second = compute_volume_profile_geometry(request)
        assert first == second, case
        assert _aggregate_equal(
            fsum(bar.volume for bar in bars),
            first.total_volume,
            _aggregate_operation_budget(len(bars), request.row_count),
        ), case


def test_direct_dispatcher_matches_native_kernel() -> None:
    request = _request()
    assert execute_analysis_capability(
        "ta.volume_profile_geometry", request
    ) == compute_volume_profile_geometry(request)


def test_bound_profile_requires_volume_unit_and_matches_direct() -> None:
    request = _request()
    direct = compute_volume_profile_geometry(request)
    bound = execute_bound_analysis_capability(
        "ta.volume_profile_geometry", request, _context(request.market_as_of)
    )
    changed = execute_bound_analysis_capability(
        "ta.volume_profile_geometry",
        replace(request, row_count=2),
        _context(request.market_as_of),
    )
    assert bound.result == direct
    assert bound.parameter_identity == (
        ("row_count", "3"),
        ("value_area_fraction", "0x1.6666666666666p-1"),
    )
    assert bound.parameter_fingerprint != changed.parameter_fingerprint

    missing_unit = replace(_context(request.market_as_of).source, volume_unit=None)
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.volume_profile_geometry",
            request,
            replace(_context(request.market_as_of), source=missing_unit),
        )


def test_bound_profile_requires_source_availability_at_final_close() -> None:
    request = _request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.volume_profile_geometry",
            request,
            _context(
                request.market_as_of,
                source_available_at=request.market_as_of - timedelta(seconds=1),
            ),
        )
