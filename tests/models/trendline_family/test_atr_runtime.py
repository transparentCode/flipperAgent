from __future__ import annotations

from functools import partial

from libs.models.trendline.interaction.atr import calculate_interaction_atr
from libs.models.trendline.tracking.matching import calculate_normalization_atr
from libs.models.trendline.tracking.service import TrendlineFamilyTracker
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    serialize_snapshot,
)

from .tracker_support import (
    SequenceProvider,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def test_public_atr_paths_share_short_frame_and_compiled_python_parity() -> None:
    frame = tracker_ohlcv(timestamp()).iloc[-5:]
    interaction_compiled = calculate_interaction_atr(frame, window=50)
    interaction_python = calculate_interaction_atr(
        frame,
        window=50,
        compiled=False,
    )
    matching_compiled = calculate_normalization_atr(frame, window=50)
    matching_python = calculate_normalization_atr(
        frame,
        window=50,
        compiled=False,
    )

    assert interaction_compiled == interaction_python
    assert matching_compiled == matching_python
    assert interaction_compiled.value == matching_compiled.value
    assert interaction_compiled.sample_count == matching_compiled.sample_count == len(frame)


def test_tracker_snapshot_and_output_are_backend_identical(monkeypatch) -> None:
    config = tracker_config()
    observed_at = timestamp()
    result = valid_result(
        candidate(config, observed_at, candidate_id="backend-parity", quality=0.80)
    )
    compiled_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((result,)),
        config=config,
    ).update(tracker_ohlcv(observed_at))

    import libs.models.trendline.tracking.service as service

    monkeypatch.setattr(
        service,
        "calculate_interaction_atr",
        partial(calculate_interaction_atr, compiled=False),
    )
    monkeypatch.setattr(
        service,
        "calculate_normalization_atr",
        partial(calculate_normalization_atr, compiled=False),
    )
    python_output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((result,)),
        config=config,
    ).update(tracker_ohlcv(observed_at))

    assert serialize_snapshot(compiled_output.snapshot) == serialize_snapshot(
        python_output.snapshot
    )
    assert compiled_output.snapshot.snapshot_id == python_output.snapshot.snapshot_id
    assert compiled_output.features == python_output.features
