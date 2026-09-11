import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from libs.analysis_capabilities.invocation import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisInvocationResult,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _series() -> AnalysisSeriesIdentity:
    return AnalysisSeriesIdentity(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="binance:BTCUSDT",
        timeframe="1h",
    )


def _source(
    *,
    source_type: str = "fixture",
    source_provider: str | None = None,
    source_timeframe: str | None = None,
    available_at: datetime = _START,
    volume_unit: str | None = None,
) -> AnalysisSourceAttestation:
    return AnalysisSourceAttestation(
        series=_series(),
        source_type=source_type,  # type: ignore[arg-type]
        source_provider=source_provider,
        source_timeframe=source_timeframe,
        source_revision="fixture-revision-1",
        source_slice_sha256="a" * 64,
        source_available_at=available_at,
        volume_unit=volume_unit,
    )


def _context(
    source: AnalysisSourceAttestation | None = None,
    *,
    market_as_of: datetime = _START + timedelta(hours=4),
    request_available_at: datetime = _START + timedelta(hours=5),
    evaluation_at: datetime = _START + timedelta(hours=6),
) -> AnalysisInvocationContext:
    return AnalysisInvocationContext(
        source=source or _source(),
        market_as_of=market_as_of,
        request_available_at=request_available_at,
        evaluation_at=evaluation_at,
    )


def _parameter_fingerprint(
    method_version: str,
    parameters: tuple[tuple[str, str], ...],
) -> str:
    canonical = json.dumps(
        {
            "method_version": method_version,
            "parameters": [list(entry) for entry in parameters],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _result_envelope(
    capability_id: str,
    method_version: str,
    parameters: tuple[tuple[str, str], ...],
    *,
    source: AnalysisSourceAttestation | None = None,
    state_fingerprint: str | None = None,
    result: object | None = None,
) -> AnalysisInvocationResult:
    context = _context(source if source is not None else _source())
    return AnalysisInvocationResult(
        capability_id=capability_id,
        method_version=method_version,
        source=context.source,
        market_as_of=context.market_as_of,
        request_available_at=context.request_available_at,
        evaluation_at=context.evaluation_at,
        parameter_identity=parameters,
        parameter_fingerprint=_parameter_fingerprint(method_version, parameters),
        result=object() if result is None else result,
        state_fingerprint=state_fingerprint,
    )


def test_source_attestation_accepts_provider_derived_and_fixture_shapes() -> None:
    provider = _source(source_type="provider", source_provider="binance")
    derived = _source(source_type="derived", source_timeframe="1h")
    fixture = _source()

    assert provider.source_provider == "binance"
    assert provider.source_timeframe is None
    assert derived.source_provider is None
    assert derived.source_timeframe == "1h"
    assert fixture.source_provider is None
    assert fixture.source_timeframe is None


@pytest.mark.parametrize(
    ("source_type", "source_provider", "source_timeframe"),
    [
        ("provider", None, None),
        ("provider", "binance", "1h"),
        ("derived", "binance", "1h"),
        ("derived", None, None),
        ("fixture", "binance", None),
        ("fixture", None, "1h"),
    ],
)
def test_source_type_combinations_fail_closed(
    source_type: str,
    source_provider: str | None,
    source_timeframe: str | None,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _source(
            source_type=source_type,
            source_provider=source_provider,
            source_timeframe=source_timeframe,
        )


@pytest.mark.parametrize(
    "sha",
    ("A" * 64, "a" * 63, "a" * 65, "g" * 64, ""),
)
def test_source_sha_requires_lowercase_64_hex(sha: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        AnalysisSourceAttestation(
            series=_series(),
            source_type="fixture",
            source_provider=None,
            source_timeframe=None,
            source_revision="r1",
            source_slice_sha256=sha,
            source_available_at=_START,
            volume_unit=None,
        )


def test_identity_is_exact_and_not_normalized() -> None:
    identity = AnalysisSeriesIdentity(
        asset=" btcusdt ",
        venue="Binance",
        instrument_id="raw-id",
        timeframe="01H",
    )
    assert identity.asset == " btcusdt "
    assert identity.venue == "Binance"
    assert identity.timeframe == "01H"
    with pytest.raises(FrozenInstanceError):
        identity.asset = "BTCUSDT"  # type: ignore[misc]


def test_context_allows_source_after_market_when_request_is_later() -> None:
    source = _source(available_at=_START + timedelta(hours=5))
    context = _context(
        source,
        market_as_of=_START + timedelta(hours=4),
        request_available_at=_START + timedelta(hours=5),
    )
    assert context.source.source_available_at > context.market_as_of
    assert context.request_available_at <= context.evaluation_at


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "source": _source(available_at=_START + timedelta(hours=2)),
            "request_available_at": _START + timedelta(hours=1),
            "evaluation_at": _START + timedelta(hours=3),
        },
        {
            "request_available_at": _START + timedelta(hours=3),
            "evaluation_at": _START + timedelta(hours=2),
        },
        {
            "market_as_of": _START + timedelta(hours=3),
            "request_available_at": _START + timedelta(hours=4),
            "evaluation_at": _START + timedelta(hours=2),
        },
    ],
)
def test_context_time_ordering_fails_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _context(**kwargs)  # type: ignore[arg-type]


def test_context_rejects_non_utc_aware_times() -> None:
    non_utc = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))
    with pytest.raises(ValueError):
        _context(market_as_of=non_utc)
    with pytest.raises(TypeError):
        _context(market_as_of=datetime.fromisoformat("2026-01-01T00:00:00"))


def test_result_fingerprint_is_canonical_and_native_result_is_retained() -> None:
    context = _context()
    parameters: tuple[tuple[str, str], ...] = ()
    result_object = object()
    envelope = AnalysisInvocationResult(
        capability_id="ta.traditional_pivot_geometry",
        method_version="pivot.traditional.v1",
        source=context.source,
        market_as_of=context.market_as_of,
        request_available_at=context.request_available_at,
        evaluation_at=context.evaluation_at,
        parameter_identity=parameters,
        parameter_fingerprint=_parameter_fingerprint(
            "pivot.traditional.v1", parameters
        ),
        result=result_object,
    )
    assert envelope.result is result_object
    assert envelope.parameter_identity == parameters


@pytest.mark.parametrize(
    ("capability_id", "method_version", "parameters", "volume_unit", "state"),
    [
        (
            "model.trendlines",
            "trendlines.geometry.v2",
            (("history_capacity_bars", "300"), ("pivot_window", "3")),
            None,
            None,
        ),
        (
            "model.sr",
            "sr.engine.step.schema.1.0",
            (("resolved_config_hash", "config-1"),),
            None,
            "d" * 64,
        ),
        (
            "model.regression",
            "regression.context.v1",
            (
                ("channel_config_hash", "channel-1"),
                ("source_config_hash", "source-1"),
                ("window_size", "20"),
            ),
            None,
            None,
        ),
        (
            "ta.fibonacci_geometry",
            "fibonacci.two_point_linear.v1",
            (("extension_ratios", "1.25,1.5"), ("retracement_ratios", "0.25,0.5")),
            None,
            None,
        ),
        (
            "ta.swing_anchors",
            "swing_anchors.strict_confirmed.v1",
            (("span", "1"),),
            None,
            None,
        ),
        (
            "ta.traditional_pivot_geometry",
            "pivot.traditional.v1",
            (),
            None,
            None,
        ),
        (
            "ta.vwap_geometry",
            "vwap.explicit_range_hlc3.v1",
            (),
            "quote_asset",
            None,
        ),
    ],
)
def test_result_accepts_exact_sorted_spec_parameter_names(
    capability_id: str,
    method_version: str,
    parameters: tuple[tuple[str, str], ...],
    volume_unit: str | None,
    state: str | None,
) -> None:
    source = _source(volume_unit=volume_unit) if volume_unit is not None else None
    envelope = _result_envelope(
        capability_id,
        method_version,
        parameters,
        source=source,
        state_fingerprint=state,
    )
    assert tuple(name for name, _ in envelope.parameter_identity) == tuple(
        sorted(name for name, _ in parameters)
    )


@pytest.mark.parametrize(
    ("capability_id", "method_version", "parameters", "volume_unit", "state"),
    [
        (
            "ta.traditional_pivot_geometry",
            "pivot.traditional.v1",
            (("unexpected", "1"),),
            None,
            None,
        ),
        (
            "ta.vwap_geometry",
            "vwap.explicit_range_hlc3.v1",
            (("unexpected", "1"),),
            "quote_asset",
            None,
        ),
        (
            "ta.swing_anchors",
            "swing_anchors.strict_confirmed.v1",
            (),
            None,
            None,
        ),
        (
            "ta.swing_anchors",
            "swing_anchors.strict_confirmed.v1",
            (("other", "1"),),
            None,
            None,
        ),
        (
            "ta.swing_anchors",
            "swing_anchors.strict_confirmed.v1",
            (("extra", "1"), ("span", "1")),
            None,
            None,
        ),
        (
            "model.regression",
            "regression.context.v1",
            (("channel_config_hash", "channel-1"), ("source_config_hash", "source-1")),
            None,
            None,
        ),
        (
            "model.regression",
            "regression.context.v1",
            (
                ("channel_config_hash", "channel-1"),
                ("source_config_hash", "source-1"),
                ("unexpected", "extra"),
                ("window_size", "20"),
            ),
            None,
            None,
        ),
        (
            "model.regression",
            "regression.context.v1",
            (
                ("channel_config_hash", "channel-1"),
                ("source_config_hash", "source-1"),
                ("window", "20"),
            ),
            None,
            None,
        ),
    ],
)
def test_result_rejects_parameter_identity_not_declared_by_spec(
    capability_id: str,
    method_version: str,
    parameters: tuple[tuple[str, str], ...],
    volume_unit: str | None,
    state: str | None,
) -> None:
    source = _source(volume_unit=volume_unit) if volume_unit is not None else None
    with pytest.raises(
        ValueError,
        match="parameter_identity fields do not match capability specification",
    ):
        _result_envelope(
            capability_id,
            method_version,
            parameters,
            source=source,
            state_fingerprint=state,
        )


@pytest.mark.parametrize(
    "parameters",
    [
        (("z", "1"), ("a", "2")),
        (("a", "1"), ("a", "2")),
    ],
)
def test_result_parameter_identity_must_be_sorted_and_unique(
    parameters: tuple[tuple[str, str], ...],
) -> None:
    context = _context()
    with pytest.raises(ValueError):
        AnalysisInvocationResult(
            capability_id="ta.traditional_pivot_geometry",
            method_version="pivot.traditional.v1",
            source=context.source,
            market_as_of=context.market_as_of,
            request_available_at=context.request_available_at,
            evaluation_at=context.evaluation_at,
            parameter_identity=parameters,
            parameter_fingerprint="b" * 64,
            result=object(),
        )


def test_attestation_is_not_authentication() -> None:
    source = _source()
    assert source.source_slice_sha256 == "a" * 64
    assert not hasattr(source, "authenticated")
    assert source.source_type == "fixture"


def test_result_enforces_required_source_fields_and_state_mode() -> None:
    context = _context()
    empty_parameters = ()
    vwap_payload = json.dumps(
        {
            "method_version": "vwap.explicit_range_hlc3.v1",
            "parameters": [],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    with pytest.raises(AnalysisBindingError):
        AnalysisInvocationResult(
            capability_id="ta.vwap_geometry",
            method_version="vwap.explicit_range_hlc3.v1",
            source=context.source,
            market_as_of=context.market_as_of,
            request_available_at=context.request_available_at,
            evaluation_at=context.evaluation_at,
            parameter_identity=empty_parameters,
            parameter_fingerprint=hashlib.sha256(vwap_payload).hexdigest(),
            result=object(),
        )

    sr_payload = json.dumps(
        {
            "method_version": "sr.engine.step.schema.1.0",
            "parameters": [["resolved_config_hash", "config-1"]],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    with pytest.raises((TypeError, ValueError)):
        AnalysisInvocationResult(
            capability_id="model.sr",
            method_version="sr.engine.step.schema.1.0",
            source=context.source,
            market_as_of=context.market_as_of,
            request_available_at=context.request_available_at,
            evaluation_at=context.evaluation_at,
            parameter_identity=(("resolved_config_hash", "config-1"),),
            parameter_fingerprint=hashlib.sha256(sr_payload).hexdigest(),
            result=object(),
        )

    with pytest.raises(ValueError):
        AnalysisInvocationResult(
            capability_id="ta.traditional_pivot_geometry",
            method_version="pivot.traditional.v1",
            source=context.source,
            market_as_of=context.market_as_of,
            request_available_at=context.request_available_at,
            evaluation_at=context.evaluation_at,
            parameter_identity=empty_parameters,
            parameter_fingerprint=hashlib.sha256(
                json.dumps(
                    {"method_version": "pivot.traditional.v1", "parameters": []},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            result=object(),
            state_fingerprint="d" * 64,
        )


def test_binding_error_remains_a_value_error_for_r2_contradictions() -> None:
    assert issubclass(AnalysisBindingError, ValueError)
