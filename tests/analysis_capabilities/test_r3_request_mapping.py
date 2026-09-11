from __future__ import annotations

import pytest

from libs.analysis_capabilities.ta.swing_anchors import SwingAnchorSnapshot
from libs.analysis_capabilities.ta.traditional_pivot_geometry import (
    TraditionalPivotGeometryRequest,
)
from libs.analysis_capabilities.ta.vwap_geometry import VWAPGeometryRequest
from research.analysis_capabilities.r3_requests import (
    R3RequestError,
    build_fibonacci_request,
    build_swing_request,
    build_traditional_pivot_request,
    build_trendlines_request,
    build_vwap_request,
    execute_swing_anchors,
)
from tests.analysis_capabilities.test_r3_canonical_source import (
    make_records,
    make_source_slice,
)


def _available_at(source) -> object:
    return source.source.source_available_at


def _anchor_pair(source) -> tuple[tuple[str, object], tuple[str, object]]:
    swing = execute_swing_anchors(
        source,
        span=1,
        request_available_at=_available_at(source),
    )
    snapshot = swing.result
    assert isinstance(snapshot, SwingAnchorSnapshot)
    low = next(anchor for anchor in snapshot.anchors if anchor.kind == "swing_low")
    high = next(
        anchor
        for anchor in snapshot.anchors
        if anchor.kind == "swing_high" and anchor.formed_at > low.formed_at
    )
    return (low.kind, low.formed_at), (high.kind, high.formed_at)


def test_trendlines_mapping_is_exactly_three_hundred_native_records() -> None:
    source = make_source_slice()
    request = build_trendlines_request(source)

    assert len(request.history) == 300
    assert request.history[0].closed_at == source.records[0].bar.bar_close_at
    assert request.history[-1].closed_at == source.market_as_of
    assert request.history[20].close == float(source.records[20].bar.close)
    with pytest.raises(R3RequestError, match="exactly 300"):
        build_trendlines_request(make_source_slice(make_records(299)))


def test_swing_mapping_requires_an_explicit_positive_span() -> None:
    source = make_source_slice()
    request = build_swing_request(source, span=1)
    assert request.span == 1
    assert len(request.bars) == len(source.records)
    with pytest.raises(R3RequestError, match="positive integer"):
        build_swing_request(source, span=0)
    with pytest.raises(R3RequestError, match="positive integer"):
        build_swing_request(source, span=True)  # type: ignore[arg-type]


def test_vwap_mapping_accepts_only_an_explicit_contiguous_range() -> None:
    source = make_source_slice()
    by_start = build_vwap_request(
        source,
        start_open_at=source.records[100].bar.bar_open_at,
    )
    by_records = build_vwap_request(source, records=source.records[100:])
    assert isinstance(by_start, VWAPGeometryRequest)
    assert by_start == by_records
    assert by_start.bars[-1].closed_at == source.market_as_of

    with pytest.raises(R3RequestError, match="exactly one"):
        build_vwap_request(source)
    with pytest.raises(R3RequestError, match="exactly one"):
        build_vwap_request(
            source,
            start_open_at=source.records[0].bar.bar_open_at,
            records=source.records,
        )
    with pytest.raises(R3RequestError, match="contiguous"):
        build_vwap_request(source, records=(source.records[0], source.records[2]))


def test_traditional_mapping_binds_one_exact_reference_record() -> None:
    source = make_source_slice()
    request = build_traditional_pivot_request(
        source,
        reference=source.records[50],
    )

    assert isinstance(request, TraditionalPivotGeometryRequest)
    assert request.reference.opened_at == source.records[50].bar.bar_open_at
    assert request.reference.closed_at == source.records[50].bar.bar_close_at
    with pytest.raises(R3RequestError, match="exact source record"):
        build_traditional_pivot_request(source, reference=object())  # type: ignore[arg-type]


def test_fibonacci_mapping_resolves_only_source_authenticated_swing_anchors() -> None:
    source = make_source_slice()
    start_anchor, end_anchor = _anchor_pair(source)
    request = build_fibonacci_request(
        source,
        swing_snapshot=execute_swing_anchors(
            source,
            span=1,
            request_available_at=_available_at(source),
        ).result,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        retracement_ratios=(0.382, 0.618),
        extension_ratios=(1.618,),
        selection_available_at=_available_at(source),
    )

    assert request.start_anchor.formed_at == start_anchor[1]
    assert request.end_anchor.formed_at == end_anchor[1]
    with pytest.raises(R3RequestError, match="selection_available_at"):
        build_fibonacci_request(
            source,
            swing_snapshot=execute_swing_anchors(
                source,
                span=1,
                request_available_at=_available_at(source),
            ).result,
            start_anchor=start_anchor,
            end_anchor=end_anchor,
            retracement_ratios=(0.5,),
            extension_ratios=(1.5,),
            selection_available_at=source.records[0].bar.bar_close_at,
        )

    with pytest.raises(R3RequestError, match="identity"):
        build_fibonacci_request(
            source,
            swing_snapshot=execute_swing_anchors(
                source,
                span=1,
                request_available_at=_available_at(source),
            ).result,
            start_anchor=("swing_low", source.records[0].bar.bar_close_at),
            end_anchor=end_anchor,
            retracement_ratios=(0.5,),
            extension_ratios=(1.5,),
            selection_available_at=_available_at(source),
        )


def test_request_mapping_does_not_mutate_the_canonical_source() -> None:
    source = make_source_slice()
    before = source.records
    build_trendlines_request(source)
    build_swing_request(source, span=1)
    build_vwap_request(source, start_open_at=source.records[0].bar.bar_open_at)
    build_traditional_pivot_request(source, reference=source.records[10])
    assert source.records == before
