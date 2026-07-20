"""Native deterministic line-candidate provider for Phase B only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol

import pandas as pd

from .configuration.contracts import ResolvedTrendlineFamilyConfig
from .contracts import ContractValidationError, LineCandidate, LineDiagnostics, deterministic_id, require_utc
from .fitting import FITTER_NAME, FittedPath, PathfindingFitStatus, PathfindingLineFitter
from .pivots import (
    PIVOT_PROVIDER_NAME,
    CausalFractalPivotExtractor,
    PivotExtractionStatus,
    confirmed_ohlcv_window,
    freeze_result_metadata,
)


LINE_PROVIDER_NAME = "native_deterministic"
_HISTORICAL_NATIVE_PROVIDER_IDENTITY = "libs.models.trendline_family.provider.NativeDeterministicLineProvider"


class CandidateGenerationStatus(str, Enum):
    VALID = "valid"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_CONFIRMED_PIVOTS = "no_confirmed_pivots"
    NO_VALID_FITTED_PATHS = "no_valid_fitted_paths"
    REJECTED_LOW_QUALITY = "rejected_low_quality_candidates"
    PROVIDER_CONFIG_ERROR = "provider_config_error"


class _ProviderRequestValidationError(ContractValidationError):
    """Expected caller/config errors that should return an abstention result."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CandidateGenerationResult:
    """A valid candidate set or an explicit immutable abstention."""

    status: CandidateGenerationStatus | str
    candidates: tuple[LineCandidate, ...]
    reason_codes: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            status = CandidateGenerationStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid candidate generation status: {self.status!r}") from exc
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, LineCandidate) for candidate in candidates):
            raise ContractValidationError("candidates must contain only LineCandidate values")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ContractValidationError("candidate IDs must be unique")
        reason_codes = tuple(self.reason_codes)
        if any(not isinstance(reason, str) or not reason for reason in reason_codes):
            raise ContractValidationError("reason_codes must contain non-empty strings")
        if len(set(reason_codes)) != len(reason_codes):
            raise ContractValidationError("reason_codes must be unique")
        if status is CandidateGenerationStatus.VALID:
            if not candidates or reason_codes:
                raise ContractValidationError("valid candidate result requires candidates and no reason codes")
        elif candidates or not reason_codes:
            raise ContractValidationError("abstention result requires no candidates and at least one reason code")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(
            self,
            "metadata",
            freeze_result_metadata(self.metadata, field_name="candidate generation metadata"),
        )


class LineCandidateProvider(Protocol):
    """Small provider surface; lifecycle state is intentionally absent."""

    def generate(
        self,
        ohlcv: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
        context: Mapping[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        """Generate candidates using only completed bars at ``observed_at``."""


class NativeDeterministicLineProvider:
    """Compose native fractals and pathfinding into canonical line candidates."""

    def generate(
        self,
        ohlcv: pd.DataFrame,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
        context: Mapping[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        del context  # Candidate discovery deliberately has no policy or external-context input.
        audit_metadata = self._request_audit_metadata(asset, timeframe, observed_at, config)
        try:
            self._validate_request(asset=asset, timeframe=timeframe, config=config)
            observed = require_utc(observed_at, field_name="observed_at")
            frame = confirmed_ohlcv_window(
                ohlcv,
                observed_at=observed,
                required_columns=frozenset({"open", "high", "low", "close"}),
            ).tail(config.candidate.lookback_bars)
        except _ProviderRequestValidationError as exc:
            return self._abstain(
                CandidateGenerationStatus.PROVIDER_CONFIG_ERROR,
                exc.reason_code,
                audit_metadata=audit_metadata,
                error=str(exc),
            )
        except ContractValidationError as exc:
            return self._abstain(
                CandidateGenerationStatus.PROVIDER_CONFIG_ERROR,
                "invalid_provider_input",
                audit_metadata=audit_metadata,
                error=str(exc),
            )

        if len(frame) < config.candidate.min_bars:
            return self._abstain(
                CandidateGenerationStatus.INSUFFICIENT_DATA,
                "min_bars_not_met",
                audit_metadata=audit_metadata,
                confirmed_bars=len(frame),
                required_bars=config.candidate.min_bars,
            )

        extractor = CausalFractalPivotExtractor(
            left_bars=config.candidate.fractal_left_bars,
            right_bars=config.candidate.fractal_right_bars,
        )
        pivot_result = extractor.extract(frame, observed_at=observed)
        if pivot_result.status is PivotExtractionStatus.INSUFFICIENT_DATA:
            return self._abstain(
                CandidateGenerationStatus.INSUFFICIENT_DATA,
                "pivot_window_not_met",
                audit_metadata=audit_metadata,
                confirmed_bars=pivot_result.confirmed_bars,
            )
        if pivot_result.status is PivotExtractionStatus.NO_CONFIRMED_PIVOTS:
            return self._abstain(
                CandidateGenerationStatus.NO_CONFIRMED_PIVOTS,
                "no_confirmed_pivots",
                audit_metadata=audit_metadata,
                confirmed_bars=pivot_result.confirmed_bars,
            )

        fit_result = PathfindingLineFitter().fit(frame, pivot_result, config=config)
        if fit_result.status is not PathfindingFitStatus.VALID:
            return self._abstain(
                CandidateGenerationStatus.NO_VALID_FITTED_PATHS,
                fit_result.status.value,
                audit_metadata=audit_metadata,
                confirmed_pivots=len(pivot_result.pivots),
                fit_metadata=fit_result.metadata,
            )

        eligible: list[LineCandidate] = []
        for source_line_index, fitted in enumerate(fit_result.lines):
            candidate = self._to_candidate(
                fitted,
                source_line_index=source_line_index,
                asset=asset,
                timeframe=timeframe,
                observed_at=observed,
                config=config,
            )
            if candidate.diagnostics.normalized_quality >= config.candidate.min_candidate_quality:
                eligible.append(candidate)
        if not eligible:
            return self._abstain(
                CandidateGenerationStatus.REJECTED_LOW_QUALITY,
                "min_candidate_quality_not_met",
                audit_metadata=audit_metadata,
                fitted_paths=len(fit_result.lines),
                min_candidate_quality=config.candidate.min_candidate_quality,
            )

        return CandidateGenerationResult(
            status=CandidateGenerationStatus.VALID,
            candidates=tuple(sorted(eligible, key=lambda candidate: (candidate.role.value, candidate.candidate_id))),
            reason_codes=(),
            metadata={
                **audit_metadata,
                "confirmed_bars": len(frame),
                "confirmed_pivots": len(pivot_result.pivots),
                "fitted_paths": len(fit_result.lines),
            },
        )

    @staticmethod
    def _validate_request(
        *,
        asset: str,
        timeframe: str,
        config: ResolvedTrendlineFamilyConfig,
    ) -> None:
        if not isinstance(asset, str) or not asset:
            raise _ProviderRequestValidationError("invalid_asset", "asset must be a non-empty string")
        if not isinstance(timeframe, str) or not timeframe:
            raise _ProviderRequestValidationError(
                "invalid_timeframe",
                "timeframe must be a non-empty string",
            )
        if not isinstance(config, ResolvedTrendlineFamilyConfig):
            raise _ProviderRequestValidationError(
                "invalid_resolved_config",
                "provider requires ResolvedTrendlineFamilyConfig",
            )
        if config.asset != asset:
            raise _ProviderRequestValidationError(
                "config_asset_mismatch",
                "resolved config asset does not match provider request asset",
            )
        if config.timeframe != timeframe:
            raise _ProviderRequestValidationError(
                "config_timeframe_mismatch",
                "resolved config timeframe does not match provider request timeframe",
            )
        if not config.model.enabled:
            raise _ProviderRequestValidationError("model_disabled", "trendline-family model is disabled")
        if config.candidate.pivot_provider != PIVOT_PROVIDER_NAME:
            raise _ProviderRequestValidationError(
                "unsupported_pivot_provider",
                f"unsupported pivot provider: {config.candidate.pivot_provider}",
            )
        if config.candidate.fitter != FITTER_NAME:
            raise _ProviderRequestValidationError(
                "unsupported_fitter",
                f"unsupported fitter: {config.candidate.fitter}",
            )

    @staticmethod
    def _request_audit_metadata(
        asset: Any,
        timeframe: Any,
        observed_at: Any,
        config: Any,
    ) -> dict[str, Any]:
        observed_text: str | None = None
        if isinstance(observed_at, datetime):
            try:
                observed_text = require_utc(observed_at, field_name="observed_at").isoformat()
            except ContractValidationError:
                observed_text = None
        if isinstance(config, ResolvedTrendlineFamilyConfig):
            model_version: str | None = config.model_version
            config_version: str | None = config.config_version
            resolved_config_hash: str | None = config.resolved_config_hash
        else:
            model_version = None
            config_version = None
            resolved_config_hash = None
        return {
            "asset": asset if isinstance(asset, str) and asset else None,
            "timeframe": timeframe if isinstance(timeframe, str) and timeframe else None,
            "observed_at": observed_text,
            "model_version": model_version,
            "config_version": config_version,
            "resolved_config_hash": resolved_config_hash,
        }

    @staticmethod
    def _to_candidate(
        fitted: FittedPath,
        *,
        source_line_index: int,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
    ) -> LineCandidate:
        anchors = tuple(pivot.to_anchor() for pivot in fitted.anchor_pivots)
        candidate_id = deterministic_id(
            "candidate",
            {
                "asset": asset,
                "timeframe": timeframe,
                "observed_at": observed_at.isoformat(),
                "provider": LINE_PROVIDER_NAME,
                "method": FITTER_NAME,
                "role": fitted.role.value,
                "anchor_ids": [anchor.anchor_id for anchor in anchors],
                "geometry": {
                    "reference_time": fitted.geometry.reference_time.isoformat(),
                    "reference_price": fitted.geometry.reference_price,
                    "slope_per_second": fitted.geometry.slope_per_second,
                },
            },
        )
        return LineCandidate(
            candidate_id=candidate_id,
            asset=asset,
            timeframe=timeframe,
            observed_at=observed_at,
            geometry=fitted.geometry,
            anchors=anchors,
            role=fitted.role,
            method=FITTER_NAME,
            provider=LINE_PROVIDER_NAME,
            diagnostics=LineDiagnostics(
                raw_score=fitted.coverage,
                normalized_quality=fitted.quality,
                touch_count=2,
                effective_touch_count=2,
                coverage=fitted.coverage,
                inlier_ratio=None,
                residual_scale_atr=None,
                cut_fraction=None,
                fitter_consensus=None,
                anchor_stability=None,
            ),
            source_line_index=source_line_index,
            metadata={
                "pivot_provider": PIVOT_PROVIDER_NAME,
                "path_anchor_ids": tuple(pivot.pivot_id for pivot in fitted.path_pivots),
                "path_length": len(fitted.path_pivots),
                "quality_method": fitted.quality_method,
                "model_version": config.model_version,
                "config_version": config.config_version,
                "resolved_config_hash": config.resolved_config_hash,
            },
        )

    @staticmethod
    def _abstain(
        status: CandidateGenerationStatus,
        reason: str,
        *,
        audit_metadata: Mapping[str, Any],
        **metadata: Any,
    ) -> CandidateGenerationResult:
        return CandidateGenerationResult(
            status=status,
            candidates=(),
            reason_codes=(reason,),
            metadata={**audit_metadata, **metadata},
        )


def provider_identity(provider: LineCandidateProvider) -> str:
    """Return persisted provider identity without invalidating Phase-I artifacts."""

    if isinstance(provider, NativeDeterministicLineProvider):
        return _HISTORICAL_NATIVE_PROVIDER_IDENTITY
    return f"{provider.__class__.__module__}.{provider.__class__.__qualname__}"
