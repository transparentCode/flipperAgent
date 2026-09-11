"""Contract tests for deterministic replay diagnostics and evidence."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.data import TrendlineArtifactRef
from libs.models.trendlines.contracts.identity import TrendlineSnapshotFinality
from libs.models.trendlines.workflows.research import (
    TrendlineEvidenceSelection,
    TrendlineEvidenceContractError,
    TrendlineReplayIntegrityError,
    TrendlineResearchEvidenceBundle,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    TrendlineReplayWindow,
    build_research_evidence_bundle,
    inspect_replay_pivots,
    prepare_trendline_research,
    read_research_evidence_bundle,
    replay_line_rows,
    replay_pivot_count_rows,
    replay_ray_rows,
    replay_signal_rows,
    replay_snapshot_rows,
    replay_summary,
    run_causal_replay,
    write_research_evidence_bundle,
)


def _prepared(*, extractor: str = "fractal"):
    config = load_trendlines_config()
    if extractor == "rdp_zigzag":
        config = replace(
            config,
            extractor=extractor,
            extractor_params={"epsilon_atr": 0.5, "min_segment_bars": 3},
        )
    spec = TrendlineResearchSpec(
        purpose=(
            TrendlineResearchPurpose.RESEARCH
            if extractor == "rdp_zigzag"
            else TrendlineResearchPurpose.SMOKE
        ),
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=42,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={"1h": 48},
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    return asyncio.run(
        prepare_trendline_research(spec, trendlines_config=config)
    )


def _replay(
    *,
    include_signals: bool = False,
    extractor: str = "fractal",
    warmup: int = 19,
    record_start: int = 20,
    end: int = 23,
):
    prepared = _prepared(extractor=extractor)
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={
                "1h": TrendlineReplayWindow(
                    warmup,
                    record_start,
                    end,
                    1,
                )
            },
            include_signals=include_signals,
        ),
    )
    return prepared, replay


def _read_recomputed_payload(
    payload: dict,
    tmp_path: Path,
    name: str,
):
    candidate = TrendlineResearchEvidenceBundle.from_dict(payload)
    payload["bundle_id"] = candidate.computed_bundle_id()
    path = tmp_path / name
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return read_research_evidence_bundle(path)


def test_snapshot_summary_rows_match_recorded_outputs() -> None:
    _, replay = _replay(include_signals=True)
    rows = replay_snapshot_rows(replay)
    assert len(rows) == 4
    for row in rows:
        point = replay.output_at(row.timeframe, row.position)
        assert row.fit_valid == point.output.fit_result.is_valid
        assert row.boundary_snapshot_id == point.boundary_identity.snapshot_id
        assert row.signal_count == (point.output.signal_output or {}).get("signal_count", 0)
    summary = replay_summary(replay)
    assert summary.recorded_snapshot_count == len(rows)
    assert summary.unique_recorded_position_count == len(rows)


def test_pivot_count_rows_match_authoritative_pipeline_metadata() -> None:
    _, replay = _replay()
    rows = replay_pivot_count_rows(replay)
    assert len(rows) == 4
    for row in rows:
        point = replay.output_at(row.timeframe, row.position)
        metadata = point.output.fit_result.metadata["pipeline"]
        assert row.n_high_pivots == metadata["n_high_pivots"]
        assert row.n_low_pivots == metadata["n_low_pivots"]


def test_line_rows_match_fitted_line_counts_and_geometry() -> None:
    _, replay = _replay()
    rows = replay_line_rows(replay)
    expected = sum(
        len(point.output.fit_result.support_lines)
        + len(point.output.fit_result.resistance_lines)
        for point in replay.timeframes["1h"].points
    )
    assert len(rows) == expected
    for row in rows:
        assert row.start_position <= row.end_position


def test_ray_rows_match_boundary_rays_and_quality_values() -> None:
    _, replay = _replay()
    rows = replay_ray_rows(replay)
    expected = sum(
        len(point.boundary_snapshot.boundary.active_support_rays)
        + len(point.boundary_snapshot.boundary.active_resistance_rays)
        for point in replay.timeframes["1h"].points
    )
    assert len(rows) == expected
    for row in rows:
        assert row.quality >= 0.0
        assert row.touch_count >= 0


def test_signal_rows_match_native_signal_output() -> None:
    _, replay = _replay(include_signals=True)
    rows = replay_signal_rows(replay)
    expected = sum(
        len(point.output.signal_output["signals"])
        for point in replay.timeframes["1h"].points
        if point.output.signal_output is not None
    )
    assert len(rows) == expected
    for row in rows:
        assert row.replay_point_id


def test_selected_pivot_inspection_matches_authoritative_counts() -> None:
    prepared, replay = _replay()
    point = replay.output_at("1h", 22)
    rows = inspect_replay_pivots(prepared, replay, timeframe="1h", position=22)
    metadata = point.output.fit_result.metadata["pipeline"]
    assert sum(row.pivot_role == "high" for row in rows) == metadata["n_high_pivots"]
    assert sum(row.pivot_role == "low" for row in rows) == metadata["n_low_pivots"]
    assert all(row.replay_point_id == point.replay_point_id for row in rows)


def test_evidence_selection_derives_all_ids_from_one_replay_point() -> None:
    prepared, replay = _replay()
    selection = TrendlineEvidenceSelection(timeframe="1h", position=22)
    bundle = build_research_evidence_bundle(prepared, replay, selection=selection)
    point = replay.output_at("1h", 22)
    assert bundle.selected_binding["replay_point_id"] == point.replay_point_id
    assert bundle.selected_binding["source_id"] == point.prefix_source_ref.source_id
    assert bundle.selected_binding["checkpoint_id"] == point.boundary_identity.checkpoint.checkpoint_id
    assert bundle.selected_binding["boundary_revision_id"] == point.boundary_identity.revision_id


def test_evidence_bundle_is_deterministic_and_content_addressed() -> None:
    prepared, replay = _replay()
    selection = TrendlineEvidenceSelection("1h", 22)
    first = build_research_evidence_bundle(prepared, replay, selection=selection)
    second = build_research_evidence_bundle(prepared, replay, selection=selection)
    assert first.bundle_id == second.bundle_id
    assert first.to_dict() == second.to_dict()
    assert first.computed_bundle_id() == first.bundle_id


def test_evidence_json_round_trip_succeeds_and_tampering_is_rejected(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    artifact = TrendlineArtifactRef(str(tmp_path), "evidence/bundle.json")
    path = write_research_evidence_bundle(bundle, artifact)
    restored = read_research_evidence_bundle(path)
    assert restored.to_dict() == bundle.to_dict()
    payload = path.read_text(encoding="utf-8").replace(bundle.bundle_id, "0" * 64)
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="content-address"):
        read_research_evidence_bundle(path)


def test_evidence_construction_rejects_mutated_replay_point() -> None:
    prepared, replay = _replay()
    point = replay.output_at("1h", 22)
    point.boundary_snapshot.boundary.interaction = "MUTATED_AFTER_ID"
    with pytest.raises(TrendlineReplayIntegrityError):
        build_research_evidence_bundle(
            prepared,
            replay,
            selection=TrendlineEvidenceSelection("1h", 22),
        )


def test_reader_rejects_recomputed_id_with_selection_binding_mismatch(
    tmp_path: Path,
) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = bundle.to_dict()
    payload["selection"] = {"timeframe": "1h", "position": 20}
    recomputed = TrendlineResearchEvidenceBundle.from_dict(payload)
    payload["bundle_id"] = recomputed.computed_bundle_id()
    path = tmp_path / "selection-mismatch.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(TrendlineEvidenceContractError, match="selection position"):
        read_research_evidence_bundle(path)


def test_reader_rejects_recomputed_id_with_summary_row_mismatch(
    tmp_path: Path,
) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = bundle.to_dict()
    payload["summary"]["recorded_snapshot_count"] += 1
    recomputed = TrendlineResearchEvidenceBundle.from_dict(payload)
    payload["bundle_id"] = recomputed.computed_bundle_id()
    path = tmp_path / "summary-mismatch.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(TrendlineEvidenceContractError, match="recorded_snapshot_count"):
        read_research_evidence_bundle(path)


def test_reader_rejects_line_reassigned_to_another_point(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    original_point_id = payload["line_rows"][0]["replay_point_id"]
    payload["line_rows"][0]["replay_point_id"] = next(
        row["replay_point_id"]
        for row in payload["snapshot_rows"]
        if row["replay_point_id"] != original_point_id
    )
    with pytest.raises(TrendlineEvidenceContractError, match="differs from snapshot"):
        _read_recomputed_payload(payload, tmp_path, "line-reassignment.json")


def test_reader_rejects_pivot_checkpoint_or_content_mismatch(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["pivot_count_rows"][0]["checkpoint_id"] = payload[
        "pivot_count_rows"
    ][1]["checkpoint_id"]
    with pytest.raises(TrendlineEvidenceContractError, match="differs from snapshot"):
        _read_recomputed_payload(payload, tmp_path, "pivot-checkpoint.json")


def test_reader_rejects_stale_line_evidence_id(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["line_rows"][0]["slope"] += 1.0
    with pytest.raises(TrendlineEvidenceContractError, match="evidence_id"):
        _read_recomputed_payload(payload, tmp_path, "stale-line-id.json")


def test_reader_rejects_stale_ray_evidence_id(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["ray_rows"][0]["end_price"] += 1.0
    with pytest.raises(TrendlineEvidenceContractError, match="evidence_id"):
        _read_recomputed_payload(payload, tmp_path, "stale-ray-id.json")


def test_reader_rejects_incorrect_timeframe_count(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["summary"]["timeframe_count"] = 999
    with pytest.raises(TrendlineEvidenceContractError, match="timeframe_count"):
        _read_recomputed_payload(payload, tmp_path, "timeframe-count.json")


def test_reader_rejects_incorrect_executed_point_count(tmp_path: Path) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["summary"]["executed_point_count"] = 999
    with pytest.raises(TrendlineEvidenceContractError, match="executed_point_count"):
        _read_recomputed_payload(payload, tmp_path, "executed-count.json")


def test_reader_rejects_snapshot_coordinate_mismatch_with_replay_spec(
    tmp_path: Path,
) -> None:
    prepared, replay = _replay()
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 22),
    )
    payload = copy.deepcopy(bundle.to_dict())
    payload["replay_spec"]["windows"]["1h"]["record_every"] = 2
    with pytest.raises(TrendlineEvidenceContractError, match="replay-spec"):
        _read_recomputed_payload(payload, tmp_path, "coordinate-mismatch.json")


def test_selected_binding_ids_validate_without_selected_pivots(
    tmp_path: Path,
) -> None:
    base_prepared = _prepared()
    frame = base_prepared.dataset.frames["1h"].copy()
    frame.attrs = dict(frame.attrs)
    values = [100.0 + index for index in range(len(frame))]
    frame["open"] = values
    frame["close"] = values
    frame["high"] = [value + 0.1 for value in values]
    frame["low"] = [value - 0.1 for value in values]
    injected_spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(mode=TrendlineResearchDataMode.INJECTED),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    prepared = asyncio.run(
        prepare_trendline_research(
            injected_spec,
            trendlines_config=load_trendlines_config(),
            loader={"1h": frame},
        )
    )
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={"1h": TrendlineReplayWindow(19, 19, 19, 1)},
            include_signals=False,
        ),
    )
    bundle = build_research_evidence_bundle(
        prepared,
        replay,
        selection=TrendlineEvidenceSelection("1h", 19),
    )
    assert bundle.selected_pivots == ()
    payload = copy.deepcopy(bundle.to_dict())
    payload["selected_binding"]["content_id"] = "0" * 64
    with pytest.raises(TrendlineEvidenceContractError, match="selected binding differs"):
        _read_recomputed_payload(payload, tmp_path, "empty-pivots-binding.json")


def test_rdp_replay_is_research_only_and_retrospective() -> None:
    _, replay = _replay(extractor="rdp_zigzag")
    for point in replay.timeframes["1h"].points:
        assert point.boundary_identity.finality is TrendlineSnapshotFinality.RETROSPECTIVE_REVISING
        assert point.boundary_identity.checkpoint.execution_mode.value == "research"


def test_research_diagnostic_modules_have_no_application_or_viewer_dependencies() -> None:
    package = Path(__file__).parents[1] / "workflows" / "research"
    forbidden = ("app.connectors", "BinanceConnector", "jupyter", "IPython", "plotly", "TVLC")
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden), path


__all__ = []
