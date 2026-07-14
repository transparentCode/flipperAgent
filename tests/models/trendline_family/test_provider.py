from __future__ import annotations

import pytest

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.provider import (
    CandidateGenerationStatus,
    LINE_PROVIDER_NAME,
    NativeDeterministicLineProvider,
)
from libs.models.trendline_family.registry import (
    fitter_names,
    get_line_provider,
    line_provider_names,
    pivot_provider_names,
)

from .support import candidate_ohlcv, monotonic_ohlcv, resolved_config


def test_native_provider_and_registry_are_deterministic_and_self_contained() -> None:
    frame = candidate_ohlcv()
    result = get_line_provider(LINE_PROVIDER_NAME).generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert pivot_provider_names() == ("fractal",)
    assert fitter_names() == ("pathfinding",)
    assert line_provider_names() == (LINE_PROVIDER_NAME,)
    assert result.status is CandidateGenerationStatus.VALID
    assert {candidate.role.value for candidate in result.candidates} == {"SUPPORT", "RESISTANCE"}


def test_provider_returns_explicit_abstentions() -> None:
    provider = NativeDeterministicLineProvider()
    frame = candidate_ohlcv()
    insufficient = provider.generate(
        frame.iloc[:4],
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[3].to_pydatetime(),
        config=resolved_config(),
    )
    no_pivots_frame = monotonic_ohlcv()
    no_pivots = provider.generate(
        no_pivots_frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=no_pivots_frame.index[-1].to_pydatetime(),
        config=resolved_config(min_bars=8, lookback_bars=24),
    )
    low_quality = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(min_candidate_quality=1.0),
    )
    invalid_provider = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(pivot_provider="not_registered"),
    )

    assert insufficient.status is CandidateGenerationStatus.INSUFFICIENT_DATA
    assert no_pivots.status is CandidateGenerationStatus.NO_CONFIRMED_PIVOTS
    assert low_quality.status is CandidateGenerationStatus.REJECTED_LOW_QUALITY
    assert invalid_provider.status is CandidateGenerationStatus.PROVIDER_CONFIG_ERROR


def test_provider_rejects_invalid_request_identity_and_config_mismatches() -> None:
    frame = candidate_ohlcv()
    provider = NativeDeterministicLineProvider()
    invalid_asset = provider.generate(
        frame,
        asset="",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )
    asset_mismatch = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(asset="ETHUSDT"),
    )
    timeframe_mismatch = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(timeframe="4h"),
    )
    invalid_timeframe = provider.generate(
        frame,
        asset="BTCUSDT",
        timeframe=1,  # type: ignore[arg-type]
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )
    invalid_asset_scalar = provider.generate(
        frame,
        asset=1,  # type: ignore[arg-type]
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert invalid_asset.reason_codes == ("invalid_asset",)
    assert asset_mismatch.reason_codes == ("config_asset_mismatch",)
    assert timeframe_mismatch.reason_codes == ("config_timeframe_mismatch",)
    assert invalid_timeframe.reason_codes == ("invalid_timeframe",)
    assert invalid_asset_scalar.reason_codes == ("invalid_asset",)
    for result in (
        invalid_asset,
        asset_mismatch,
        timeframe_mismatch,
        invalid_timeframe,
        invalid_asset_scalar,
    ):
        assert result.status is CandidateGenerationStatus.PROVIDER_CONFIG_ERROR
        assert set(result.metadata) >= {
            "asset",
            "timeframe",
            "observed_at",
            "model_version",
            "config_version",
            "resolved_config_hash",
        }


@pytest.mark.parametrize(
    ("column", "value", "error"),
    [
        ("high", 7.0, "high is below low"),
        ("high", 11.0, "high is below open or close"),
        ("low", 13.0, "low is above open or close"),
    ],
)
def test_provider_returns_explicit_error_for_incoherent_ohlc_bar(
    column: str,
    value: float,
    error: str,
) -> None:
    frame = candidate_ohlcv()
    frame.loc[frame.index[0], column] = value

    result = NativeDeterministicLineProvider().generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert result.status is CandidateGenerationStatus.PROVIDER_CONFIG_ERROR
    assert result.reason_codes == ("invalid_provider_input",)
    assert error in result.metadata["error"]


def test_registry_rejects_unknown_provider_names() -> None:
    with pytest.raises(ContractValidationError, match="unknown line candidate provider"):
        get_line_provider("unknown")


def test_numeric_string_ohlcv_normalizes_to_the_same_provider_result() -> None:
    numeric = candidate_ohlcv()
    numeric_strings = numeric.astype(str)
    provider = NativeDeterministicLineProvider()
    numeric_result = provider.generate(
        numeric,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=numeric.index[-1].to_pydatetime(),
        config=resolved_config(),
    )
    string_result = provider.generate(
        numeric_strings,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=numeric_strings.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert numeric_result.status is string_result.status
    assert numeric_result.reason_codes == string_result.reason_codes
    assert dict(numeric_result.metadata) == dict(string_result.metadata)
    assert [candidate.to_dict() for candidate in numeric_result.candidates] == [
        candidate.to_dict() for candidate in string_result.candidates
    ]


def test_malformed_numeric_string_returns_explicit_provider_input_error() -> None:
    frame = candidate_ohlcv().astype(str)
    frame.loc[frame.index[0], "close"] = "not-a-number"

    result = NativeDeterministicLineProvider().generate(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert result.status is CandidateGenerationStatus.PROVIDER_CONFIG_ERROR
    assert result.reason_codes == ("invalid_provider_input",)
    assert "close must be numeric" in result.metadata["error"]
