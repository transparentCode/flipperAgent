from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    PROVIDER_NAME,
    PROVIDER_VERSION,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    CandidateProvider,
    ConfirmedExtremaPairProvider,
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc


def _config() -> ConfirmedExtremaPairConfig:
    return ConfirmedExtremaPairConfig(
        lookback_duration_seconds=86_400.0,
        left_confirmation_bars=1,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        max_hypotheses=100,
        max_output_candidates=100,
    )


def _foundation_config():
    return resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )


def _input() -> ProviderInput:
    base = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=datetime(2024, 1, 1, 6, tzinfo=UTC),
        confirmed_through=datetime(2024, 1, 1, 6, tzinfo=UTC),
        timestamps=tuple(base + index * 3_600_000_000_000 for index in range(7)),
        open=(10.0,) * 7,
        high=(11.0,) * 7,
        low=(5.0, 1.0, 5.0, 2.0, 5.0, 3.0, 5.0),
        close=(10.0,) * 7,
        volume=(1.0,) * 7,
    )


def _request(**config_changes) -> ProviderRequest:
    config = _config()
    if config_changes:
        config = replace(config, **config_changes)
    return ProviderRequest(input_data=_input(), config=_foundation_config(), provider_config=config)


def _success() -> ProviderResult:
    result = ConfirmedExtremaPairProvider().generate(_request())
    assert result.status is ProviderStatus.SUCCESS
    assert len(result.candidates) >= 2
    return result


def test_provider_protocol_and_explicit_data_boundary() -> None:
    provider = ConfirmedExtremaPairProvider()
    assert isinstance(provider, CandidateProvider)
    result = _success()
    assert result.provider_name == PROVIDER_NAME
    assert result.provider_version == PROVIDER_VERSION
    assert result.request.input_data.low[1] == 1.0


def test_success_requires_one_ordered_evidence_item_per_candidate() -> None:
    result = _success()
    assert tuple(item.candidate_id for item in result.evidence) == tuple(
        candidate.candidate_id for candidate in result.candidates
    )
    with pytest.raises(ContractValidationError, match="candidate IDs must match"):
        ProviderResult(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            request=result.request,
            status=ProviderStatus.SUCCESS,
            candidates=result.candidates,
            evidence=result.evidence[:-1],
            diagnostics=ProviderDiagnostics(len(result.candidates), result.request.input_data.row_count),
        )
    with pytest.raises(ContractValidationError, match="order"):
        ProviderResult(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            request=result.request,
            status=ProviderStatus.SUCCESS,
            candidates=result.candidates,
            evidence=tuple(reversed(result.evidence)),
            diagnostics=ProviderDiagnostics(len(result.candidates), result.request.input_data.row_count),
        )


def test_non_success_requires_empty_candidate_and_evidence_collections() -> None:
    result = _success()
    with pytest.raises(ContractValidationError, match="candidate IDs must match"):
        ProviderResult(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            request=result.request,
            status=ProviderStatus.ABSTAINED,
            candidates=(),
            evidence=(result.evidence[0],),
            diagnostics=ProviderDiagnostics(0, result.request.input_data.row_count),
            reason=ProviderReason.NO_CANDIDATES,
        )


@pytest.mark.parametrize(
    "reason,status",
    [
        (ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED, ProviderStatus.ABSTAINED),
        (ProviderReason.OUTPUT_LIMIT_EXCEEDED, ProviderStatus.ABSTAINED),
        (ProviderReason.PROVIDER_FAILURE, ProviderStatus.FAILED),
    ],
)
def test_reason_status_semantics_are_typed(reason, status) -> None:
    request = _request()
    result = ProviderResult(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        request=request,
        status=status,
        candidates=(),
        evidence=(),
        diagnostics=ProviderDiagnostics(0, request.input_data.row_count),
        reason=reason,
    )
    assert result.reason is reason
    wrong = ProviderStatus.FAILED if status is ProviderStatus.ABSTAINED else ProviderStatus.ABSTAINED
    with pytest.raises(ContractValidationError, match="incompatible"):
        ProviderResult(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            request=request,
            status=wrong,
            candidates=(),
            evidence=(),
            diagnostics=ProviderDiagnostics(0, request.input_data.row_count),
            reason=reason,
        )


def test_provider_result_serialization_is_deterministic() -> None:
    first = _success()
    second = _success()
    assert first.to_dict() == second.to_dict()


def test_provider_request_identity_binds_active_provider_config() -> None:
    first = _request()
    second = _request(max_hypotheses=101)
    assert first.provider_config_identity != second.provider_config_identity
    assert first.request_identity != second.request_identity


def test_runtime_source_has_no_forbidden_imports() -> None:
    source_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    forbidden = (
        "libs.models.trendline",
        "libs.models.trendline_family",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "app.trendlines",
        "libs.models.sr",
        "libs.models.regime_v2",
        "libs.integrations.trendline_regime_v2",
        "research",
        "optimization",
    )
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
        ), path


def test_discovery_imports_stay_inside_approved_layers() -> None:
    package_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    allowed_absolute = {
        "domain": {"__future__", "dataclasses", "datetime", "enum", "math", "types", "typing", "json", "hashlib", "numbers"},
        "input": {"__future__", "dataclasses", "datetime", "hashlib", "typing", "numpy", "pandas"},
        "configuration": {"__future__", "dataclasses", "enum", "typing", "yaml", "pathlib", "re", "types"},
        "discovery": {"__future__", "dataclasses", "datetime", "enum", "itertools", "typing"},
    }
    for layer, allowed in allowed_absolute.items():
        for path in (package_root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(alias.name.split(".", 1)[0] in allowed for alias in node.names), path
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    assert (node.module or "").split(".", 1)[0] in allowed, path
