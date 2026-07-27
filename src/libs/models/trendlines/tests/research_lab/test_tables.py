from __future__ import annotations

import pandas as pd

from libs.models.trendlines.research_lab import (
    lab_config_table,
    lab_identity_table,
    lab_line_table,
    lab_pivot_count_table,
    lab_performance_table,
    lab_ray_table,
    lab_signal_history_table,
    lab_signal_table,
    lab_snapshot_timeline,
    lab_source_table,
)

from . import session_for


def test_identity_source_and_config_tables_match_typed_objects() -> None:
    session = session_for(("1h", "4h"))
    identity = lab_identity_table(session)
    source = lab_source_table(session)
    config = lab_config_table(session)
    assert tuple(identity["timeframe"]) == ("1h", "4h")
    assert tuple(source["source_id"]) == tuple(
        session.prepared.dataset.identity.source_refs[tf].source_id
        for tf in ("1h", "4h")
    )
    assert tuple(config["extractor"]) == tuple(
        session.prepared.configuration.pipeline_configs[tf].extractor
        for tf in ("1h", "4h")
    )


def test_diagnostic_tables_match_selected_evidence_exactly() -> None:
    session = session_for()
    selection = session.latest_selection("1h")
    assert len(lab_pivot_count_table(session, "1h")) == len(
        [row for row in session._diagnostics()["pivot_count"] if row.timeframe == "1h"]
    )
    assert len(lab_line_table(selection)) == len(selection.line_rows)
    assert len(lab_ray_table(selection)) == len(selection.ray_rows)
    assert len(lab_signal_table(selection)) == len(selection.signal_rows)
    assert set(lab_line_table(selection).get("replay_point_id", [])) <= {
        selection.point.replay_point_id
    }


def test_signal_history_table_preserves_snapshot_revision_pairing() -> None:
    session = session_for()
    table = lab_signal_history_table(session.latest_selection("1h"))
    metadata = session.latest_selection("1h").point.output.metadata
    assert tuple(table["history_snapshot_id"]) == tuple(metadata.get("history_snapshot_ids", ()))
    assert tuple(table["history_revision_id"]) == tuple(metadata.get("history_revision_ids", ()))


def test_performance_table_has_stable_shape_and_empty_tables_are_typed() -> None:
    session = session_for()
    session.time_table(lab_snapshot_timeline, session, "1h")
    performance = lab_performance_table(session)
    timeline = lab_snapshot_timeline(session, "1h")
    assert tuple(performance.columns) == ("scope", "timeframe", "operation", "milliseconds")
    assert tuple(timeline.columns[:3]) == ("timeframe", "position", "replay_point_id")
    assert isinstance(performance, pd.DataFrame)
    assert session.timings.table_ms > 0.0
    table_row = performance.loc[performance["operation"] == "table_construction", "milliseconds"]
    assert table_row.iloc[0] > 0.0
