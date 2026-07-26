import asyncio
from dataclasses import replace

import pytest

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.research_viewer import (
    TrendlineViewerSpec,
    build_trendlines_viewer_payload,
    validate_viewer_payload,
)
from libs.models.trendlines.research_viewer.contracts import TrendlineViewerContractError
from libs.models.trendlines.research_viewer.payload import _ray_payload
from libs.models.trendlines.research_viewer.contracts import (
    VIEWER_PAYLOAD_SEMANTICS_VERSION,
)
from libs.models.trendlines.research_viewer.notebook_support import (
    TrendlineResearchNotebookSession,
    run_research_notebook_session,
)
from libs.models.trendlines.workflows.research import (
    TrendlineEvidenceSelection,
    build_research_evidence_bundle,
)


@pytest.fixture(scope="module")
def smoke_session() -> TrendlineResearchNotebookSession:
    result = asyncio.run(run_research_notebook_session(start_viewer=False))
    yield result
    result.close()


def test_payload_is_deterministic(smoke_session: TrendlineResearchNotebookSession) -> None:
    assert build_trendlines_viewer_payload(
        smoke_session.prepared,
        smoke_session.replay,
        smoke_session.evidence_bundle,
        TrendlineViewerSpec(
            timeframe="1h",
            position=smoke_session.payload["selected_position"],
            display_lookback_bars=32,
        ),
    ) == smoke_session.payload


def test_selection_changes_payload_id(smoke_session: TrendlineResearchNotebookSession) -> None:
    position = smoke_session.replay.timeframes["1h"].recorded_positions[0]
    evidence = build_research_evidence_bundle(
        smoke_session.prepared,
        smoke_session.replay,
        selection=TrendlineEvidenceSelection(timeframe="1h", position=position),
    )
    payload = build_trendlines_viewer_payload(
        smoke_session.prepared,
        smoke_session.replay,
        evidence,
        TrendlineViewerSpec(timeframe="1h", position=position, display_lookback_bars=8),
    )
    assert payload["payload_id"] != smoke_session.payload["payload_id"]


def test_display_window_identity_is_stable(smoke_session: TrendlineResearchNotebookSession) -> None:
    payload = smoke_session.payload
    assert payload["display_window_id"] == build_trendlines_viewer_payload(
        smoke_session.prepared,
        smoke_session.replay,
        smoke_session.evidence_bundle,
        TrendlineViewerSpec(
            timeframe=payload["timeframe"],
            position=payload["selected_position"],
            display_lookback_bars=32,
        ),
    )["display_window_id"]


def test_display_contains_no_future_candle(smoke_session: TrendlineResearchNotebookSession) -> None:
    payload = smoke_session.payload
    assert payload["display_end_position"] == payload["selected_position"]
    assert len(payload["candles"]) == payload["display_end_position"] - payload["display_start_position"] + 1


def test_geometry_layers_match_selected_evidence(smoke_session: TrendlineResearchNotebookSession) -> None:
    payload = smoke_session.payload
    assert {row["evidence_id"] for row in payload["lines"]} == {
        row.evidence_id
        for row in smoke_session.evidence_bundle.line_rows
        if (row.timeframe, row.position) == (payload["timeframe"], payload["selected_position"])
    }
    assert {row["evidence_id"] for row in payload["rays"]} == {
        row.evidence_id
        for row in smoke_session.evidence_bundle.ray_rows
        if (row.timeframe, row.position) == (payload["timeframe"], payload["selected_position"])
    }
    assert {row["replay_point_id"] for row in payload["pivots"]} == {
        payload["replay_point_id"]
    }


def test_default_payload_contains_geometry_positions(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = smoke_session.payload
    assert payload["lines"]
    assert payload["rays"]
    for row in (*payload["lines"], *payload["rays"]):
        assert isinstance(row["start_position"], int)
        assert isinstance(row["end_position"], int)


def test_geometry_segment_may_begin_before_display_window(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = smoke_session.payload
    assert any(
        row["start_position"] < payload["display_start_position"]
        for row in (*payload["lines"], *payload["rays"])
    )


def test_line_positions_match_canonical_evidence(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = smoke_session.payload
    evidence_by_id = {
        row.evidence_id: row
        for row in smoke_session.evidence_bundle.line_rows
        if (row.timeframe, row.position) == (payload["timeframe"], payload["selected_position"])
    }
    for row in payload["lines"]:
        evidence = evidence_by_id[row["evidence_id"]]
        assert row["start_position"] == evidence.start_position
        assert row["end_position"] == evidence.end_position


def test_ray_positions_match_prepared_frame_timestamps(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = smoke_session.payload
    frame = smoke_session.prepared.dataset.frames[payload["timeframe"]]
    for row in payload["rays"]:
        assert int(frame.index[row["start_position"]].timestamp()) == row["start_time"]
        assert int(frame.index[row["end_position"]].timestamp()) == row["end_time"]


def test_invalid_ray_timestamp_mapping_is_rejected(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = smoke_session.payload
    frame = smoke_session.prepared.dataset.frames[payload["timeframe"]]
    ray = next(
        row
        for row in smoke_session.evidence_bundle.ray_rows
        if (row.timeframe, row.position) == (payload["timeframe"], payload["selected_position"])
    )
    with pytest.raises(TrendlineViewerContractError, match="does not match a prepared frame timestamp"):
        _ray_payload(replace(ray, start_time="2035-01-01T00:00:00+00:00"), frame)


def test_retrospective_finality_survives_payload_validation(
    smoke_session: TrendlineResearchNotebookSession,
) -> None:
    payload = dict(smoke_session.payload)
    payload["finality"] = "retrospective_revising"
    payload["payload_id"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "payload_id"},
        semantics_version=VIEWER_PAYLOAD_SEMANTICS_VERSION,
    )
    assert validate_viewer_payload(payload)["finality"] == "retrospective_revising"
