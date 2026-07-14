from __future__ import annotations

from libs.models.trendline_family.provider import NativeDeterministicLineProvider

from .support import candidate_ohlcv, resolved_config


def test_identical_ohlcv_and_config_produce_identical_candidate_order_and_ids() -> None:
    frame = candidate_ohlcv()
    config = resolved_config()
    provider = NativeDeterministicLineProvider()
    first = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=config,
    )
    second = provider.generate(
        frame.copy(),
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=config,
    )

    assert [candidate.candidate_id for candidate in first.candidates] == [
        candidate.candidate_id for candidate in second.candidates
    ]
    assert [candidate.to_dict() for candidate in first.candidates] == [
        candidate.to_dict() for candidate in second.candidates
    ]
