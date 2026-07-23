from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendline_v2 import (
    LatestValidPredecessorPolicy,
    discover_trendlines,
    select_trendline_candidates,
)
import libs.models.trendline_v2 as trendline_v2
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ConfirmedExtremaPairProvider,
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.domain import (
    AbstentionReason,
    DiscoveryStatus,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame


UTC = timezone.utc
_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _foundation_config():
    return resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )


def _provider_config(**changes) -> ConfirmedExtremaPairConfig:
    values = {
        "lookback_duration_seconds": 24 * 3_600.0,
        "left_confirmation_bars": 1,
        "right_confirmation_bars": 1,
        "min_extrema_per_role": 2,
        "max_hypotheses": 100,
        "max_output_candidates": 100,
    }
    values.update(changes)
    return ConfirmedExtremaPairConfig(**values)


def _ohlcv_frame(
    *,
    low: tuple[float, ...] = (5.0, 1.0, 5.0, 2.0, 5.0, 3.0, 5.0),
    high: tuple[float, ...] | None = None,
    body: tuple[float, ...] | None = None,
    offsets: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    offsets = offsets or tuple(range(len(low)))
    count = len(offsets)
    if len(low) != count:
        raise ValueError("low and offsets must have equal lengths")
    high = high or (11.0,) * count
    body = body or (10.0,) * count
    index = [_BASE + timedelta(hours=offset) for offset in offsets]
    return pd.DataFrame(
        {
            "open": body,
            "high": high,
            "low": low,
            "close": body,
            "volume": (1.0,) * count,
        },
        index=pd.DatetimeIndex(index),
    )


def _frame(
    data: pd.DataFrame | None = None,
    *,
    observed_hours: int | None = None,
    confirmed_hours: int | None = None,
) -> ConfirmedOHLCVFrame:
    data = data if data is not None else _ohlcv_frame()
    last_hour = int((data.index[-1] - _BASE).total_seconds() // 3_600)
    confirmed_hours = last_hour if confirmed_hours is None else confirmed_hours
    observed_hours = confirmed_hours if observed_hours is None else observed_hours
    return ConfirmedOHLCVFrame.from_frame(
        data,
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=_BASE + timedelta(hours=observed_hours),
        confirmed_through=_BASE + timedelta(hours=confirmed_hours),
    )


def _manual_request(frame: ConfirmedOHLCVFrame, provider_config=None) -> ProviderRequest:
    arrays = frame.arrays()
    provider_input = ProviderInput(
        asset=frame.asset,
        timeframe=frame.timeframe,
        observed_at=frame.observed_at,
        confirmed_through=frame.confirmed_through,
        timestamps=tuple(int(value) for value in arrays.timestamps),
        open=tuple(float(value) for value in arrays.open),
        high=tuple(float(value) for value in arrays.high),
        low=tuple(float(value) for value in arrays.low),
        close=tuple(float(value) for value in arrays.close),
        volume=tuple(float(value) for value in arrays.volume),
    )
    return ProviderRequest(
        input_data=provider_input,
        config=_foundation_config(),
        provider_config=provider_config or _provider_config(),
    )


def test_discover_trendlines_matches_manual_provider_path() -> None:
    frame = _frame()
    result = discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    manual = ConfirmedExtremaPairProvider().generate(_manual_request(frame))

    assert result.to_dict() == manual.to_dict()
    assert result.request.input_identity == manual.request.input_identity
    assert result.request.input_identity == result.to_snapshot().input_identity


def test_successful_discovery_preserves_candidates_and_evidence() -> None:
    frame = _frame()
    result = discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )

    assert result.status is ProviderStatus.SUCCESS
    assert result.candidates
    assert tuple(item.candidate_id for item in result.evidence) == tuple(
        item.candidate_id for item in result.candidates
    )
    assert result.request.config_identity == result.request.to_dict()["config_identity"]


def test_public_selection_api_is_explicit_and_does_not_filter_discovery() -> None:
    frame = _frame()
    result = discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    source = result.to_snapshot()

    selected = select_trendline_candidates(
        source,
        policy=LatestValidPredecessorPolicy(),
    )

    assert len(result.candidates) == len(source.candidates)
    assert selected.diagnostics.source_candidate_count == len(result.candidates)
    with pytest.raises(TypeError):
        select_trendline_candidates(source)  # type: ignore[call-arg]
    with pytest.raises(ContractValidationError):
        select_trendline_candidates(object(), policy=LatestValidPredecessorPolicy())  # type: ignore[arg-type]


def test_public_exports_are_exact() -> None:
    assert trendline_v2.__all__ == [
        "CandidateSelectionSnapshot",
        "LatestValidPredecessorPolicy",
        "discover_trendlines",
        "select_trendline_candidates",
    ]


@pytest.mark.parametrize(
    ("data", "provider_changes", "expected_reason"),
    [
        (
            _ohlcv_frame(low=(5.0, 1.0)),
            {},
            ProviderReason.INSUFFICIENT_INPUT,
        ),
        (
            _ohlcv_frame(
                low=(0.0,) * 7,
                high=(5.0, 10.0, 10.0, 5.0, 8.0, 5.0, 5.0),
                body=(4.0, 4.0, 10.0, 4.0, 4.0, 4.0, 4.0),
            ),
            {},
            ProviderReason.NO_CANDIDATES,
        ),
        (
            _ohlcv_frame(),
            {"max_hypotheses": 2},
            ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED,
        ),
        (
            _ohlcv_frame(),
            {"max_output_candidates": 1},
            ProviderReason.OUTPUT_LIMIT_EXCEEDED,
        ),
    ],
)
def test_public_api_preserves_expected_abstentions(
    data: pd.DataFrame,
    provider_changes: dict[str, int],
    expected_reason: ProviderReason,
) -> None:
    frame = _frame(data)
    result = discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(**provider_changes),
    )

    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is expected_reason
    assert result.to_snapshot().status is DiscoveryStatus.ABSTAINED


def test_submicrosecond_timestamps_abstain_as_invalid_input_through_api() -> None:
    data = _ohlcv_frame(low=(5.0, 1.0, 5.0), offsets=(0, 1, 2))
    data.index = pd.to_datetime(
        [
            "2024-01-01T00:00:00.000000001Z",
            "2024-01-01T00:00:00.000001001Z",
            "2024-01-01T00:00:00.000002001Z",
        ]
    )
    frame = ConfirmedOHLCVFrame.from_frame(
        data,
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=_BASE + timedelta(microseconds=2),
        confirmed_through=_BASE + timedelta(microseconds=2),
    )

    result = discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )

    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is ProviderReason.INVALID_INPUT
    assert result.to_snapshot().reason is AbstentionReason.INVALID_INPUT


def test_future_rows_cannot_change_public_api_result() -> None:
    base_data = _ohlcv_frame()
    future = _ohlcv_frame(low=(5.0,), offsets=(7,))
    future.loc[future.index[0], "close"] = float("nan")
    future.loc[future.index[0], "volume"] = -1.0
    base = _frame(base_data)
    extended = _frame(pd.concat([base_data, future]), confirmed_hours=6, observed_hours=6)

    base_result = discover_trendlines(
        base,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    extended_result = discover_trendlines(
        extended,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )

    assert extended.row_count == base.row_count
    assert extended_result.to_dict() == base_result.to_dict()


def test_public_api_does_not_mutate_frame() -> None:
    frame = _frame()
    before_identity = frame.input_identity
    before_frame = frame.frame
    before_arrays = frame.arrays()

    discover_trendlines(
        frame,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )

    after_arrays = frame.arrays()
    assert frame.input_identity == before_identity
    assert frame.frame.equals(before_frame)
    assert all(
        (getattr(before_arrays, name) == getattr(after_arrays, name)).all()
        for name in ("timestamps", "open", "high", "low", "close", "volume")
    )
    assert not after_arrays.close.flags.writeable


@pytest.mark.parametrize(
    "kwargs",
    [
        {"frame": _ohlcv_frame()},
        {"config": {"model": {}}},
        {"provider_config": {"max_output_candidates": 1}},
    ],
)
def test_public_api_rejects_unvalidated_input_types(kwargs: dict[str, object]) -> None:
    frame = _frame()
    values: dict[str, object] = {
        "frame": frame,
        "config": _foundation_config(),
        "provider_config": _provider_config(),
    }
    values.update(kwargs)

    with pytest.raises(ContractValidationError):
        discover_trendlines(**values)  # type: ignore[arg-type]


def test_snapshot_conversion_sorts_only_snapshot_copy() -> None:
    result = discover_trendlines(
        _frame(),
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    reordered = ProviderResult(
        provider_name=result.provider_name,
        provider_version=result.provider_version,
        request=result.request,
        status=result.status,
        candidates=tuple(reversed(result.candidates)),
        evidence=tuple(reversed(result.evidence)),
        diagnostics=ProviderDiagnostics(
            len(result.candidates), result.request.input_data.row_count
        ),
    )
    original_candidates = reordered.candidates
    original_evidence = reordered.evidence

    snapshot = reordered.to_snapshot()

    assert snapshot.candidates == tuple(
        sorted(reordered.candidates, key=lambda item: (item.role.value, item.candidate_id))
    )
    assert reordered.candidates == original_candidates
    assert reordered.evidence == original_evidence
    assert snapshot == reordered.to_snapshot()
    assert snapshot.snapshot_id == reordered.to_snapshot().snapshot_id
    assert snapshot == type(snapshot).from_dict(snapshot.to_dict())


@pytest.mark.parametrize(
    ("status", "reason", "snapshot_status", "snapshot_reason"),
    [
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.INSUFFICIENT_INPUT,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.INSUFFICIENT_DATA,
        ),
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.NO_CANDIDATES,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.NO_CANDIDATES,
        ),
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.INVALID_INPUT,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.INVALID_INPUT,
        ),
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.CONFIGURATION_ERROR,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.CONFIGURATION_ERROR,
        ),
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.HYPOTHESIS_LIMIT_EXCEEDED,
        ),
        (
            ProviderStatus.ABSTAINED,
            ProviderReason.OUTPUT_LIMIT_EXCEEDED,
            DiscoveryStatus.ABSTAINED,
            AbstentionReason.OUTPUT_LIMIT_EXCEEDED,
        ),
        (
            ProviderStatus.FAILED,
            ProviderReason.PROVIDER_FAILURE,
            DiscoveryStatus.FAILED,
            AbstentionReason.PROVIDER_FAILURE,
        ),
    ],
)
def test_snapshot_conversion_maps_all_closed_provider_outcomes(
    status: ProviderStatus,
    reason: ProviderReason,
    snapshot_status: DiscoveryStatus,
    snapshot_reason: AbstentionReason,
) -> None:
    request = _manual_request(_frame())
    result = ProviderResult(
        provider_name=request.provider_config.provider_name,
        provider_version=request.provider_config.provider_version,
        request=request,
        status=status,
        candidates=(),
        evidence=(),
        diagnostics=ProviderDiagnostics(0, request.input_data.row_count),
        reason=reason,
        detail="operational detail",
    )

    snapshot = result.to_snapshot()

    assert snapshot.status is snapshot_status
    assert snapshot.reason is snapshot_reason
    assert snapshot.input_identity == request.input_identity
    assert snapshot.config_identity == request.config_identity
    assert snapshot.provider_identity == result.provider_identity
    assert snapshot.to_dict() == result.to_snapshot().to_dict()


def test_snapshot_identity_excludes_provider_detail() -> None:
    request = _manual_request(_frame())
    first = ProviderResult(
        provider_name=request.provider_config.provider_name,
        provider_version=request.provider_config.provider_version,
        request=request,
        status=ProviderStatus.ABSTAINED,
        candidates=(),
        evidence=(),
        diagnostics=ProviderDiagnostics(0, request.input_data.row_count),
        reason=ProviderReason.NO_CANDIDATES,
        detail="first detail",
    )
    second = replace(first, detail="different detail")

    assert first.to_snapshot().to_dict() == second.to_snapshot().to_dict()


def test_snapshot_mapping_fails_closed_for_unsupported_outcome() -> None:
    result = discover_trendlines(
        _frame(),
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    malformed = object.__new__(ProviderResult)
    object.__setattr__(malformed, "provider_name", result.provider_name)
    object.__setattr__(malformed, "provider_version", result.provider_version)
    object.__setattr__(malformed, "request", result.request)
    object.__setattr__(malformed, "status", ProviderStatus.ABSTAINED)
    object.__setattr__(malformed, "reason", None)
    object.__setattr__(malformed, "candidates", ())

    with pytest.raises(ContractValidationError, match="unsupported"):
        malformed.to_snapshot()


def test_api_has_no_implicit_configuration_or_forbidden_imports() -> None:
    source_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    source = (source_root / "api.py").read_text(encoding="utf-8")
    assert "load_trendline_v2_config" not in source
    assert "yaml" not in source
    tree = ast.parse(source, filename=str(source_root / "api.py"))
    forbidden = (
        "libs.models.trendline",
        "libs.models.trendline_family",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "libs.models.sr",
        "libs.models.regime_v2",
        "research",
        "optimization",
        "storage",
        "tracking",
        "viewer",
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        name == token or name.startswith(f"{token}.")
        for token in forbidden
        for name in imported
    )
