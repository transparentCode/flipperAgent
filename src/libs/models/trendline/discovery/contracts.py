"""Complete candidate-provider boundary contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import pandas as pd

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..domain.candidates import LineCandidate
from ..domain.validation import ContractValidationError, require_utc


class CandidateGenerationStatus(str, Enum):
    VALID = "valid"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_CONFIRMED_PIVOTS = "no_confirmed_pivots"
    NO_VALID_FITTED_PATHS = "no_valid_fitted_paths"
    REJECTED_LOW_QUALITY = "rejected_low_quality_candidates"
    PROVIDER_CONFIG_ERROR = "provider_config_error"


def _freeze_result_metadata(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})

    def freeze(item: Any, *, path: str) -> Any:
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ContractValidationError(f"{path} float must be finite")
            return item
        if isinstance(item, datetime):
            return require_utc(item, field_name=path)
        if isinstance(item, Enum):
            return item
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise ContractValidationError(f"{path} keys must be strings")
            return MappingProxyType(
                {key: freeze(child, path=f"{path}.{key}") for key, child in item.items()}
            )
        if isinstance(item, (tuple, list)):
            return tuple(freeze(child, path=f"{path} item") for child in item)
        raise ContractValidationError(f"unsupported {path} value type: {type(item)!r}")

    frozen = freeze(value, path=field_name)
    if not isinstance(frozen, Mapping):
        raise ContractValidationError(f"{field_name} must be a mapping")
    return frozen


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
            raise ContractValidationError(
                f"invalid candidate generation status: {self.status!r}"
            ) from exc
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, LineCandidate) for candidate in candidates):
            raise ContractValidationError(
                "candidates must contain only LineCandidate values"
            )
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ContractValidationError("candidate IDs must be unique")
        reason_codes = tuple(self.reason_codes)
        if any(not isinstance(reason, str) or not reason for reason in reason_codes):
            raise ContractValidationError(
                "reason_codes must contain non-empty strings"
            )
        if len(set(reason_codes)) != len(reason_codes):
            raise ContractValidationError("reason_codes must be unique")
        if status is CandidateGenerationStatus.VALID:
            if not candidates or reason_codes:
                raise ContractValidationError(
                    "valid candidate result requires candidates and no reason codes"
                )
        elif candidates or not reason_codes:
            raise ContractValidationError(
                "abstention result requires no candidates and at least one reason code"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(
            self,
            "metadata",
            _freeze_result_metadata(
                self.metadata,
                field_name="candidate generation metadata",
            ),
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

__all__ = ["CandidateGenerationResult", "CandidateGenerationStatus", "LineCandidateProvider"]
