from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from libs.models.trendline_family.provider import CandidateGenerationStatus, NativeDeterministicLineProvider

from .support import candidate_ohlcv, resolved_config


def test_frozen_pathfinding_reference_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "native_pathfinding_reference.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    frame = candidate_ohlcv()
    payload = {
        "index": [timestamp.isoformat() for timestamp in frame.index],
        "columns": list(frame.columns),
        "rows": [[float(value) for value in row] for row in frame.itertuples(index=False, name=None)],
    }
    result = NativeDeterministicLineProvider().generate(
        frame,
        asset=fixture["asset"],
        timeframe=fixture["timeframe"],
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert result.status is CandidateGenerationStatus.VALID
    assert fixture["fixture_version"] == 2
    assert fixture["reference_algorithm"]
    assert sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == fixture[
        "input_fixture"
    ]["sha256"]
    assert resolved_config().to_dict()["candidate"] == fixture["resolved_candidate_config"]
    by_role = {candidate.role.value: candidate for candidate in result.candidates}
    assert sorted(by_role) == fixture["expected"]["roles"]
    for role, candidate in by_role.items():
        expected = fixture["expected"][role]
        assert [anchor.timestamp.isoformat() for anchor in candidate.anchors] == expected["anchor_timestamps"]
        assert [anchor.price for anchor in candidate.anchors] == expected["anchor_prices"]
        assert candidate.geometry.reference_time.isoformat() == expected["geometry"]["reference_time"]
        assert candidate.geometry.reference_price == expected["geometry"]["reference_price"]
        assert candidate.geometry.slope_per_second == pytest.approx(
            expected["geometry"]["slope_per_second"],
            abs=1e-15,
        )
