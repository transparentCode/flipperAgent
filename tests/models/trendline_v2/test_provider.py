from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from libs.models.trendline_v2.configuration import (
    BodyValidationPolicy,
    ConfirmedExtremaPairConfig,
    HistoryHorizon,
    PairEnumerationOrder,
    PlateauPolicy,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    CandidateProvider,
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc


def _config():
    return resolve_trendline_v2_config(
        {
            "model": {
                "name": "trendline_v2",
                "version": "foundation_v1",
                "schema_version": 1,
            }
        }
    )


def _provider_config(**changes):
    values = {
        "provider_name": "confirmed_extrema_pair",
        "provider_version": "v1",
        "plateau_policy": PlateauPolicy.LEFTMOST_STRICT_LEFT_NONSTRICT_RIGHT_V1,
        "history_horizon": HistoryHorizon.LOOKBACK_DURATION_SECONDS_V1,
        "lookback_duration_seconds": 86_400.0,
        "left_confirmation_bars": 2,
        "right_confirmation_bars": 2,
        "min_extrema_per_role": 2,
        "body_validation_policy": BodyValidationPolicy.EXACT_SIDE_V1,
        "pair_enumeration_order": PairEnumerationOrder.CHRONOLOGICAL_V1,
        "candidate_order_version": "candidate_order_v1",
        "structural_validation_version": "exact_side_v1",
        "max_hypotheses": 100,
        "max_output_candidates": 20,
        "provider_evidence_schema_version": "v1",
    }
    values.update(changes)
    return ConfirmedExtremaPairConfig(**values)


def _input(
    *,
    observed_at: datetime = datetime(2024, 1, 3, tzinfo=UTC),
    confirmed_through: datetime = datetime(2024, 1, 3, tzinfo=UTC),
) -> ProviderInput:
    timestamps = tuple(
        int(datetime(2024, 1, 1, hour, tzinfo=UTC).timestamp() * 1_000_000_000)
        for hour in range(3)
    )
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=observed_at,
        confirmed_through=confirmed_through,
        timestamps=timestamps,
        open=(100.0, 101.0, 102.0),
        high=(101.0, 102.0, 103.0),
        low=(99.0, 100.0, 101.0),
        close=(100.5, 101.5, 102.5),
        volume=(10.0, 11.0, 12.0),
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        input_data=_input(), config=_config(), provider_config=_provider_config()
    )


class FixtureProvider:
    provider_name = "confirmed_extrema_pair"
    provider_version = "v1"

    def generate(self, request: ProviderRequest) -> ProviderResult:
        assert request.input_data.close == (100.5, 101.5, 102.5)
        assert request.config.model_name == "trendline_v2"
        return ProviderResult(
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            request=request,
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            diagnostics=ProviderDiagnostics(candidate_count=0, input_row_count=3),
            reason=ProviderReason.NO_CANDIDATES,
        )


def test_protocol_conformance_and_explicit_data_boundary() -> None:
    provider = FixtureProvider()
    assert isinstance(provider, CandidateProvider)
    result = provider.generate(_request())
    assert result.status is ProviderStatus.ABSTAINED
    assert result.reason is ProviderReason.NO_CANDIDATES
    assert result.provider_identity == ProviderResult(
        provider_name="confirmed_extrema_pair",
        provider_version="v1",
        request=_request(),
        status="abstained",
        candidates=(),
        diagnostics=ProviderDiagnostics(0, 3),
        reason="no_candidates",
    ).provider_identity


def test_provider_request_identity_is_derived_from_input_and_config() -> None:
    request = _request()
    changed_input = ProviderRequest(
        input_data=ProviderInput(
            asset=request.input_data.asset,
            timeframe=request.input_data.timeframe,
            observed_at=request.input_data.observed_at,
            confirmed_through=request.input_data.confirmed_through,
            timestamps=request.input_data.timestamps,
            open=request.input_data.open,
            high=request.input_data.high,
            low=request.input_data.low,
            close=(100.6, 101.5, 102.5),
            volume=request.input_data.volume,
            ),
        config=request.config,
        provider_config=request.provider_config,
    )
    assert changed_input.input_identity != request.input_identity
    assert changed_input.request_identity != request.request_identity


def test_provider_result_distinguishes_success_and_failure() -> None:
    request = _request()
    with pytest.raises(ContractValidationError):
        ProviderResult(
            provider_name="confirmed_extrema_pair",
            provider_version="v1",
            request=request,
            status=ProviderStatus.SUCCESS,
            candidates=(),
            diagnostics=ProviderDiagnostics(0, 3),
        )
    with pytest.raises(ContractValidationError):
        ProviderResult(
            provider_name="confirmed_extrema_pair",
            provider_version="v1",
            request=request,
            status=ProviderStatus.FAILED,
            candidates=(),
            diagnostics=ProviderDiagnostics(0, 3),
            reason=None,
        )
    with pytest.raises(ContractValidationError):
        ProviderResult(
            provider_name="confirmed_extrema_pair",
            provider_version="v1",
            request=request,
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            diagnostics=ProviderDiagnostics(0, 3),
            reason="free form reason",
        )


def test_provider_result_identity_must_match_typed_request_config() -> None:
    with pytest.raises(ContractValidationError, match="identity"):
        ProviderResult(
            provider_name="other_provider",
            provider_version="v1",
            request=_request(),
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            diagnostics=ProviderDiagnostics(candidate_count=0, input_row_count=3),
            reason=ProviderReason.NO_CANDIDATES,
        )


def test_request_rejects_invalid_time_boundary() -> None:
    with pytest.raises(ContractValidationError, match="after observed_at"):
        ProviderRequest(
            input_data=_input(
                observed_at=datetime(2024, 1, 1, tzinfo=UTC),
                confirmed_through=datetime(2024, 1, 2, tzinfo=UTC),
            ),
            config=_config(),
            provider_config=_provider_config(),
        )


def test_provider_input_rejects_future_or_invalid_candle_data() -> None:
    future_timestamp = int(datetime(2024, 1, 4, tzinfo=UTC).timestamp() * 1_000_000_000)
    with pytest.raises(ContractValidationError, match="after confirmed_through"):
        ProviderInput(
            **{
                "asset": "BTCUSDT",
                "timeframe": "4h",
                "observed_at": datetime(2024, 1, 3, tzinfo=UTC),
                "confirmed_through": datetime(2024, 1, 3, tzinfo=UTC),
                "timestamps": (future_timestamp,),
                "open": (100.0,),
                "high": (101.0,),
                "low": (99.0,),
                "close": (100.5,),
                "volume": (1.0,),
            }
        )
    with pytest.raises(ContractValidationError, match="OHLC"):
        ProviderInput(
            asset="BTCUSDT",
            timeframe="4h",
            observed_at=datetime(2024, 1, 3, tzinfo=UTC),
            confirmed_through=datetime(2024, 1, 3, tzinfo=UTC),
            timestamps=(1,),
            open=(100.0,),
            high=(98.0,),
            low=(99.0,),
            close=(100.5,),
            volume=(1.0,),
        )


def test_runtime_source_has_no_old_trendline_imports() -> None:
    source_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    forbidden = (
        "libs.models.trendline",
        "libs.models.trendline_family",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "app.trendlines",
    )
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path


def _import_target(path: Path, node: ast.ImportFrom) -> str:
    current = ["trendline_v2", path.parent.name]
    if node.level == 0:
        return node.module or ""
    base = current[: max(1, len(current) - node.level + 1)]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def test_every_v2_dependency_edge_stays_inside_the_approved_layer_matrix() -> None:
    package_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    allowed_absolute = {
        "domain": {"__future__", "dataclasses", "datetime", "enum", "math", "types", "typing", "json", "hashlib", "numbers"},
        "input": {"__future__", "dataclasses", "datetime", "hashlib", "typing", "numpy", "pandas"},
        "configuration": {"__future__", "dataclasses", "enum", "typing", "yaml", "pathlib", "re", "types"},
        "discovery": {"__future__", "dataclasses", "enum", "typing"},
    }
    allowed_layers = {
        "domain": {"domain"},
        "input": {"domain", "input"},
        "configuration": {"domain", "configuration"},
        "discovery": {"domain", "configuration", "discovery"},
    }
    for layer, absolute in allowed_absolute.items():
        for path in (package_root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(alias.name.split(".", 1)[0] in absolute for alias in node.names), path
                elif isinstance(node, ast.ImportFrom):
                    target = _import_target(path, node)
                    if node.level == 0:
                        assert target.split(".", 1)[0] in absolute, (path, target)
                    else:
                        assert target.split(".")[1] in allowed_layers[layer], (path, target)


def test_yaml_read_is_owned_by_configuration_loader() -> None:
    package_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    loaders = []
    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "yaml.safe_load" in text:
            loaders.append(path)
    assert loaders == [package_root / "configuration" / "loader.py"]
