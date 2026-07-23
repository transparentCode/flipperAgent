from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendline_v2.configuration import ConfirmedExtremaPairConfig, resolve_trendline_v2_config
from libs.models.trendline_v2.discovery import (
    ConfirmedExtremaPairProvider,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderStatus,
)
from libs.models.trendline_v2.domain.enums import LineRole
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc
_HOUR_NS = 3_600_000_000_000


def _foundation_config():
    return resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )


def _provider_config(**changes) -> ConfirmedExtremaPairConfig:
    values = {
        "lookback_duration_seconds": 12 * 3_600.0,
        "left_confirmation_bars": 1,
        "right_confirmation_bars": 1,
        "min_extrema_per_role": 2,
        "max_hypotheses": 100,
        "max_output_candidates": 100,
    }
    values.update(changes)
    return ConfirmedExtremaPairConfig(**values)


def _input(
    *,
    low: tuple[float, ...],
    high: tuple[float, ...] | None = None,
    body: tuple[float, ...] | None = None,
    offsets_hours: tuple[int, ...] | None = None,
) -> ProviderInput:
    count = len(low)
    high = high or tuple(11.0 for _ in range(count))
    body = body or tuple(10.0 for _ in range(count))
    offsets_hours = offsets_hours or tuple(range(count))
    base = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    timestamps = tuple(base + offset * _HOUR_NS for offset in offsets_hours)
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=offsets_hours[-1]),
        confirmed_through=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=offsets_hours[-1]),
        timestamps=timestamps,
        open=body,
        high=high,
        low=low,
        close=body,
        volume=tuple(1.0 for _ in range(count)),
    )


def _request(input_data: ProviderInput, **config_changes) -> ProviderRequest:
    return ProviderRequest(
        input_data=input_data,
        config=_foundation_config(),
        provider_config=_provider_config(**config_changes),
    )


def _low_population() -> ProviderInput:
    return _input(low=(5.0, 1.0, 5.0, 2.0, 5.0, 3.0, 5.0))


def _candidate_by_sources(result, first: int, second: int):
    return next(
        candidate
        for candidate, evidence in zip(result.candidates, result.evidence)
        if evidence.anchor_source_positions == (first, second)
    )


def test_causal_low_candidates_and_evidence_are_emitted() -> None:
    result = ConfirmedExtremaPairProvider().generate(_request(_low_population()))
    assert result.status is ProviderStatus.SUCCESS
    assert {candidate.role for candidate in result.candidates} == {LineRole.SUPPORT}
    assert tuple(item.anchor_source_positions for item in result.evidence) == ((1, 3), (1, 5), (3, 5))
    assert tuple(item.confirmation_positions for item in result.evidence) == ((2, 4), (2, 6), (4, 6))
    assert all(anchor.confirmation_time <= result.request.observed_at for candidate in result.candidates for anchor in candidate.anchors)


def test_future_rows_cannot_change_fixed_prefix_input() -> None:
    prefix = _low_population()
    provider = ConfirmedExtremaPairProvider()
    assert provider.generate(_request(prefix)).to_dict() == provider.generate(_request(prefix)).to_dict()
    future_timestamp = prefix.timestamps[-1] + _HOUR_NS
    with pytest.raises(ContractValidationError, match="after confirmed_through"):
        ProviderInput(
            asset=prefix.asset,
            timeframe=prefix.timeframe,
            observed_at=prefix.observed_at,
            confirmed_through=prefix.confirmed_through,
            timestamps=(*prefix.timestamps, future_timestamp),
            open=(*prefix.open, 10.0),
            high=(*prefix.high, 11.0),
            low=(*prefix.low, 5.0),
            close=(*prefix.close, 10.0),
            volume=(*prefix.volume, 1.0),
        )


def test_confirmed_anchor_id_persists_across_later_prefixes() -> None:
    initial = _input(low=(5.0, 1.0, 5.0, 2.0, 5.0))
    extended = _low_population()
    provider = ConfirmedExtremaPairProvider()
    first = provider.generate(_request(initial))
    later = provider.generate(_request(extended))
    initial_candidate = _candidate_by_sources(first, 1, 3)
    later_candidate = _candidate_by_sources(later, 1, 3)
    # Candidate snapshots are intentionally observed-at scoped. Confirmed anchors
    # remain the stable causal identity across later observations.
    assert initial_candidate.candidate_id != later_candidate.candidate_id
    assert initial_candidate.anchors[0].anchor_id == later_candidate.anchors[0].anchor_id


def test_leftmost_high_and_low_plateaus_are_selected() -> None:
    high_input = _input(
        low=(0.0,) * 7,
        high=(5.0, 10.0, 10.0, 5.0, 9.0, 9.0, 5.0),
        body=(4.0,) * 7,
    )
    low_input = _input(low=(5.0, 1.0, 1.0, 5.0, 0.0, 0.0, 5.0), body=(8.0,) * 7)
    provider = ConfirmedExtremaPairProvider()
    high_result = provider.generate(_request(high_input))
    low_result = provider.generate(_request(low_input))
    assert tuple(item.anchor_source_positions for item in high_result.evidence) == ((1, 4),)
    assert tuple(item.anchor_source_positions for item in low_result.evidence) == ((1, 4),)


def test_timestamp_space_geometry_uses_irregular_elapsed_time() -> None:
    input_data = _input(
        low=(5.0, 1.0, 5.0, 2.0, 5.0),
        offsets_hours=(0, 1, 3, 4, 7),
    )
    result = ConfirmedExtremaPairProvider().generate(_request(input_data))
    candidate = _candidate_by_sources(result, 1, 3)
    middle_time = datetime(2024, 1, 1, 3, tzinfo=UTC)
    assert candidate.geometry.value_at(middle_time) == pytest.approx(1.6666666666666665)


def test_sub_microsecond_timestamps_abstain_before_geometry() -> None:
    data = _low_population()
    base = data.timestamps[0]
    nanosecond_input = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=datetime(2024, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
        confirmed_through=datetime(2024, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
        timestamps=tuple(base + index * 100 for index in range(data.row_count)),
        open=data.open,
        high=data.high,
        low=data.low,
        close=data.close,
        volume=data.volume,
    )
    result = ConfirmedExtremaPairProvider().generate(_request(nanosecond_input))
    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is ProviderReason.INVALID_INPUT
    assert result.detail == (
        "confirmed_extrema_pair v1 requires microsecond-aligned epoch nanoseconds"
    )


def test_support_and_resistance_body_validation_and_equality() -> None:
    provider = ConfirmedExtremaPairProvider()
    support_valid = _input(
        low=(5.0, 1.0, 5.0, 2.0, 6.0, 5.0, 6.0),
        body=(10.0, 10.0, 10.0, 3.0, 10.0, 10.0, 10.0),
    )
    support_equal = support_valid
    support_invalid = _input(
        low=(5.0, 1.0, 5.0, 2.0, 6.0, 5.0, 6.0),
        body=(10.0, 10.0, 10.0, 2.0, 10.0, 10.0, 10.0),
    )
    resistance_valid = _input(
        low=(0.0,) * 7,
        high=(5.0, 10.0, 9.0, 5.0, 8.0, 5.0, 5.0),
        body=(4.0, 4.0, 9.0, 4.0, 4.0, 4.0, 4.0),
    )
    resistance_invalid = _input(
        low=(0.0,) * 7,
        high=(5.0, 10.0, 10.0, 5.0, 8.0, 5.0, 5.0),
        body=(4.0, 4.0, 10.0, 4.0, 4.0, 4.0, 4.0),
    )
    assert provider.generate(_request(support_valid)).status is ProviderStatus.SUCCESS
    assert provider.generate(_request(support_equal)).status is ProviderStatus.SUCCESS
    assert not any(
        item.anchor_source_positions == (1, 5)
        for item in provider.generate(_request(support_invalid)).evidence
    )
    assert provider.generate(_request(resistance_valid)).status is ProviderStatus.SUCCESS
    assert provider.generate(_request(resistance_invalid)).reason is ProviderReason.NO_CANDIDATES


def test_history_and_confirmation_parameters_change_only_owned_behavior() -> None:
    provider = ConfirmedExtremaPairProvider()
    data = _low_population()
    assert provider.generate(_request(data, lookback_duration_seconds=2 * 3_600.0)).reason is ProviderReason.INSUFFICIENT_INPUT
    right_two = provider.generate(_request(data, right_confirmation_bars=2))
    assert right_two.status is ProviderStatus.SUCCESS
    assert all(item.confirmation_positions[0] == item.anchor_source_positions[0] + 2 for item in right_two.evidence)
    assert provider.generate(_request(data, min_extrema_per_role=4)).reason is ProviderReason.INSUFFICIENT_INPUT


def test_workload_guards_abstain_without_truncating() -> None:
    provider = ConfirmedExtremaPairProvider()
    data = _low_population()
    assert provider.generate(_request(data, max_hypotheses=2)).reason is ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED
    assert provider.generate(_request(data, max_output_candidates=1)).reason is ProviderReason.OUTPUT_LIMIT_EXCEEDED


def test_flat_monotonic_and_short_inputs_abstain() -> None:
    provider = ConfirmedExtremaPairProvider()
    flat = _input(low=(5.0, 5.0, 5.0, 5.0, 5.0))
    monotonic = _input(low=(5.0, 4.0, 3.0, 2.0, 1.0))
    short = _input(low=(5.0, 1.0))
    assert provider.generate(_request(flat)).reason is ProviderReason.INSUFFICIENT_INPUT
    assert provider.generate(_request(monotonic)).reason is ProviderReason.INSUFFICIENT_INPUT
    assert provider.generate(_request(short)).reason is ProviderReason.INSUFFICIENT_INPUT


def test_repeated_calls_and_equivalent_input_sequences_are_identical() -> None:
    provider = ConfirmedExtremaPairProvider()
    first = provider.generate(_request(_low_population()))
    second = provider.generate(_request(_low_population()))
    assert first.to_dict() == second.to_dict()
    data = _low_population()
    equivalent = ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=data.observed_at,
        confirmed_through=data.confirmed_through,
        timestamps=list(data.timestamps),
        open=list(data.open),
        high=list(data.high),
        low=list(data.low),
        close=list(data.close),
        volume=list(data.volume),
    )
    assert provider.generate(_request(equivalent)).to_dict() == first.to_dict()


def test_large_extrema_population_hits_hypothesis_guard() -> None:
    lows = tuple(1.0 if index % 2 else 5.0 for index in range(101))
    result = ConfirmedExtremaPairProvider().generate(
        _request(_input(low=lows), max_hypotheses=1)
    )
    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED


def test_internal_contract_error_is_provider_failure(monkeypatch) -> None:
    provider = ConfirmedExtremaPairProvider()

    def raise_internal_contract_error(*_args, **_kwargs):
        raise ContractValidationError("forced internal construction defect")

    monkeypatch.setattr(provider, "_candidate_record", raise_internal_contract_error)
    result = provider.generate(_request(_low_population()))
    assert result.status is ProviderStatus.FAILED
    assert result.reason is ProviderReason.PROVIDER_FAILURE
    assert result.detail == "internal_contract_validation:forced internal construction defect"


def test_extreme_finite_lookback_does_not_overflow_duration_conversion() -> None:
    result = ConfirmedExtremaPairProvider().generate(
        _request(_low_population(), lookback_duration_seconds=1e308)
    )
    assert result.status is ProviderStatus.SUCCESS
