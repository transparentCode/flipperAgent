from __future__ import annotations

from libs.models.trendline_family.provider import CandidateGenerationStatus, NativeDeterministicLineProvider

from .support import candidate_ohlcv, resolved_config


def test_minimum_candidate_quality_changes_candidate_selection() -> None:
    frame = candidate_ohlcv()
    provider = NativeDeterministicLineProvider()
    admitted = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(min_candidate_quality=0.0),
    )
    rejected = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(min_candidate_quality=1.0),
    )

    assert admitted.status is CandidateGenerationStatus.VALID
    assert rejected.status is CandidateGenerationStatus.REJECTED_LOW_QUALITY


def test_lookback_and_minimum_bars_change_candidate_stage_admission() -> None:
    frame = candidate_ohlcv()
    provider = NativeDeterministicLineProvider()
    short_lookback = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(lookback_bars=8, min_bars=8),
    )
    below_minimum = provider.generate(
        frame.iloc[:-1],
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-2].to_pydatetime(),
        config=resolved_config(lookback_bars=24, min_bars=24),
    )

    assert short_lookback.reason_codes == ("insufficient_pivots",)
    assert below_minimum.status is CandidateGenerationStatus.INSUFFICIENT_DATA
    assert below_minimum.reason_codes == ("min_bars_not_met",)


def test_resolved_fractal_window_settings_change_candidate_pivot_identity() -> None:
    frame = candidate_ohlcv()
    provider = NativeDeterministicLineProvider()
    left_one = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(fractal_left_bars=1, fractal_right_bars=1),
    )
    left_two = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(fractal_left_bars=2, fractal_right_bars=1),
    )
    right_two = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(fractal_left_bars=1, fractal_right_bars=2),
    )

    assert left_one.status is CandidateGenerationStatus.VALID
    assert left_two.status is CandidateGenerationStatus.VALID
    assert right_two.status is CandidateGenerationStatus.VALID
    assert [candidate.candidate_id for candidate in left_one.candidates] != [
        candidate.candidate_id for candidate in left_two.candidates
    ]
    assert [candidate.candidate_id for candidate in left_one.candidates] != [
        candidate.candidate_id for candidate in right_two.candidates
    ]


def test_selector_names_and_minimum_pivots_control_candidate_stage_behavior() -> None:
    frame = candidate_ohlcv()
    provider = NativeDeterministicLineProvider()
    too_many_pivots = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(min_pivots_per_side=4),
    )
    unknown_pivot_provider = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(pivot_provider="unknown"),
    )
    unknown_fitter = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(fitter="unknown"),
    )

    assert too_many_pivots.reason_codes == ("insufficient_pivots",)
    assert unknown_pivot_provider.reason_codes == ("unsupported_pivot_provider",)
    assert unknown_fitter.reason_codes == ("unsupported_fitter",)
