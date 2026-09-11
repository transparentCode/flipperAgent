from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchorSnapshot
from research.analysis_capabilities import r3_requests
from tests.analysis_capabilities.test_r3_canonical_source import make_source_slice


def _arguments(source):
    swing = r3_requests.execute_swing_anchors(
        source,
        span=1,
        request_available_at=source.source.source_available_at,
    )
    snapshot = swing.result
    assert isinstance(snapshot, SwingAnchorSnapshot)
    low = next(anchor for anchor in snapshot.anchors if anchor.kind == "swing_low")
    high = next(
        anchor
        for anchor in snapshot.anchors
        if anchor.kind == "swing_high" and anchor.formed_at > low.formed_at
    )
    return {
        "span": 1,
        "vwap_start_open_at": source.records[20].bar.bar_open_at,
        "traditional_reference": source.records[100],
        "fibonacci_start_anchor": (low.kind, low.formed_at),
        "fibonacci_end_anchor": (high.kind, high.formed_at),
        "retracement_ratios": (0.382, 0.618),
        "extension_ratios": (1.618,),
        "selection_available_at": source.source.source_available_at,
        "request_available_at": source.source.source_available_at,
        "evaluation_at": source.source.source_available_at + timedelta(seconds=1),
    }


def test_vertical_slice_executes_each_named_capability_through_r2_bound_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source_slice()
    arguments = _arguments(source)
    calls: list[str] = []
    original = r3_requests.execute_bound_analysis_capability

    def record_call(capability_id, request, context):
        calls.append(capability_id)
        return original(capability_id, request, context)

    monkeypatch.setattr(r3_requests, "execute_bound_analysis_capability", record_call)
    bundle = r3_requests.execute_r3_vertical_slice(source, **arguments)

    assert calls == [
        "model.trendlines",
        "ta.swing_anchors",
        "ta.vwap_geometry",
        "ta.traditional_pivot_geometry",
        "ta.fibonacci_geometry",
    ]
    assert bundle.source_slice is source
    results = (
        bundle.trendlines,
        bundle.swing_anchors,
        bundle.vwap,
        bundle.traditional_pivot,
        bundle.fibonacci,
    )
    assert all(result.source == source.source for result in results)
    assert all(result.market_as_of == source.market_as_of for result in results)
    assert [result.capability_id for result in results] == calls


def test_vertical_slice_results_equal_direct_dispatcher_for_all_five_capabilities() -> (
    None
):
    source = make_source_slice()
    arguments = _arguments(source)
    bundle = r3_requests.execute_r3_vertical_slice(source, **arguments)
    swing_snapshot = bundle.swing_anchors.result
    assert isinstance(swing_snapshot, SwingAnchorSnapshot)

    requests_and_results = (
        (
            "model.trendlines",
            r3_requests.build_trendlines_request(source),
            bundle.trendlines.result,
        ),
        (
            "ta.swing_anchors",
            r3_requests.build_swing_request(source, span=arguments["span"]),
            bundle.swing_anchors.result,
        ),
        (
            "ta.vwap_geometry",
            r3_requests.build_vwap_request(
                source, start_open_at=arguments["vwap_start_open_at"]
            ),
            bundle.vwap.result,
        ),
        (
            "ta.traditional_pivot_geometry",
            r3_requests.build_traditional_pivot_request(
                source, reference=arguments["traditional_reference"]
            ),
            bundle.traditional_pivot.result,
        ),
        (
            "ta.fibonacci_geometry",
            r3_requests.build_fibonacci_request(
                source,
                swing_snapshot=swing_snapshot,
                start_anchor=arguments["fibonacci_start_anchor"],
                end_anchor=arguments["fibonacci_end_anchor"],
                retracement_ratios=arguments["retracement_ratios"],
                extension_ratios=arguments["extension_ratios"],
                selection_available_at=arguments["selection_available_at"],
            ),
            bundle.fibonacci.result,
        ),
    )
    for capability_id, request, expected in requests_and_results:
        assert execute_analysis_capability(capability_id, request) == expected


def test_vertical_slice_rejects_mixed_source_or_cutoff_results() -> None:
    source = make_source_slice()
    bundle = r3_requests.execute_r3_vertical_slice(source, **_arguments(source))

    forged_source = replace(bundle.vwap.source, source_slice_sha256="0" * 64)
    with pytest.raises(r3_requests.R3RequestError, match="source attestation"):
        r3_requests.R3ExecutionBundle(
            source_slice=source,
            trendlines=bundle.trendlines,
            swing_anchors=bundle.swing_anchors,
            vwap=replace(bundle.vwap, source=forged_source),
            traditional_pivot=bundle.traditional_pivot,
            fibonacci=bundle.fibonacci,
        )

    with pytest.raises(r3_requests.R3RequestError, match="source cutoff"):
        r3_requests.R3ExecutionBundle(
            source_slice=source,
            trendlines=bundle.trendlines,
            swing_anchors=bundle.swing_anchors,
            vwap=replace(
                bundle.vwap,
                market_as_of=source.market_as_of - timedelta(hours=4),
            ),
            traditional_pivot=bundle.traditional_pivot,
            fibonacci=bundle.fibonacci,
        )


def test_vertical_slice_results_keep_native_result_objects() -> None:
    source = make_source_slice()
    bundle = r3_requests.execute_r3_vertical_slice(source, **_arguments(source))

    assert bundle.trendlines.result.market_as_of == source.market_as_of
    assert bundle.swing_anchors.result.market_as_of == source.market_as_of
    assert bundle.vwap.result.market_as_of == source.market_as_of
    assert bundle.traditional_pivot.result.market_as_of == source.market_as_of
    assert bundle.fibonacci.result.market_as_of == source.market_as_of
