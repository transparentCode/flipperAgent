from __future__ import annotations

import pytest

from libs.models.trendlines.research_lab import (
    compare_lab_sessions,
    compare_replay_positions,
    default_selection_position,
    select_replay_position,
)

from . import session_for


def test_default_selection_follows_defined_policy() -> None:
    session = session_for()
    position, reason = default_selection_position(session, "1h")
    assert position == session.replay.timeframes["1h"].recorded_positions[-1]
    assert reason in {
        "latest_valid_point_with_both_line_and_ray_roles",
        "latest_valid_point_with_any_line_or_ray",
        "final_recorded_point_no_valid_geometry",
    }


def test_explicit_recorded_position_succeeds_and_unrecorded_position_rejects() -> None:
    session = session_for()
    recorded = session.replay.timeframes["1h"].recorded_positions
    selection = select_replay_position(session, timeframe="1h", position=recorded[0])
    assert selection.position == recorded[0]
    with pytest.raises(Exception, match="not recorded"):
        select_replay_position(session, timeframe="1h", position=19)


def test_selection_does_not_rerun_replay() -> None:
    session = session_for()
    replay = session.replay
    recorded = replay.timeframes["1h"].recorded_positions
    session.open_viewer("1h", recorded[-2])
    old_bundle_root = session.viewer_bundle_paths["1h"].parent
    session.open_viewer("1h", recorded[-1])
    assert session.replay is replay
    assert session.replay.replay_id
    assert session.viewer_payloads["1h"]["selected_position"] == recorded[-1]
    assert not old_bundle_root.exists()
    session.close()


def test_position_comparison_and_session_comparison_are_descriptive() -> None:
    session = session_for()
    recorded = session.replay.timeframes["1h"].recorded_positions
    comparison = compare_replay_positions(
        session,
        timeframe="1h",
        left_position=recorded[0],
        right_position=recorded[-1],
    )
    assert comparison.left_position == recorded[0]
    assert "event_at" in comparison.differences
    result = compare_lab_sessions([session, session])
    assert result.compatible is True
    assert result.sessions_compared == 2
