from __future__ import annotations

import pytest

from libs.models.trendline_family.provider import CandidateGenerationStatus, NativeDeterministicLineProvider

from .support import candidate_ohlcv, resolved_config


def test_candidates_only_use_anchors_confirmed_at_or_before_observed_at() -> None:
    frame = candidate_ohlcv()
    result = NativeDeterministicLineProvider().generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert result.status is CandidateGenerationStatus.VALID
    for candidate in result.candidates:
        assert all(anchor.confirmation_time <= candidate.observed_at for anchor in candidate.anchors)
        for anchor in candidate.anchors:
            assert candidate.geometry.value_at(anchor.timestamp) == pytest.approx(anchor.price, abs=1e-12)


def test_future_rows_do_not_change_the_observed_at_result() -> None:
    frame = candidate_ohlcv()
    observed_at = frame.index[18].to_pydatetime()
    provider = NativeDeterministicLineProvider()
    full = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=observed_at,
        config=resolved_config(),
    )
    truncated = provider.generate(
        frame.loc[: frame.index[18]],
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=observed_at,
        config=resolved_config(),
    )

    assert full.status is truncated.status
    assert full.reason_codes == truncated.reason_codes
    assert dict(full.metadata) == dict(truncated.metadata)
    assert [candidate.to_dict() for candidate in full.candidates] == [
        candidate.to_dict() for candidate in truncated.candidates
    ]
