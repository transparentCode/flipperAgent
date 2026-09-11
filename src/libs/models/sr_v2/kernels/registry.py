"""The explicit, small SR v2 kernel catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..domain.candidates import Candidate
from . import plateau_sweep, previous_period_anchor

ParameterParser = Callable[[Mapping[str, Any], str], Mapping[str, Any]]
HistoryRequirement = Callable[[Mapping[str, Any]], int]
KernelEvaluator = Callable[..., "KernelEvaluation"]


@dataclass(frozen=True, slots=True, kw_only=True)
class KernelEvaluation:
    """Candidate output plus the exact feature rows consumed to produce it."""

    candidates: tuple[Candidate, ...]
    consumed_feature_rows: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        raw_rows = tuple(self.consumed_feature_rows)
        if any(not isinstance(item, Candidate) for item in candidates):
            raise TypeError("kernel evaluation candidates must contain Candidate values")
        if any(not isinstance(row, Mapping) for row in raw_rows):
            raise TypeError("kernel evaluation evidence must contain mappings")
        rows = tuple(MappingProxyType(dict(row)) for row in raw_rows)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "consumed_feature_rows", rows)


@dataclass(frozen=True, slots=True, kw_only=True)
class KernelSpec:
    identifier: str
    parse_parameters: ParameterParser
    history_required: HistoryRequirement
    evaluate: KernelEvaluator
    replacement_policy: str
    max_candidates: int = 2
    max_evidence_rows: int = 1
    max_evidence_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or "@" not in self.identifier:
            raise ValueError("kernel identifier must be versioned as name@version")
        if self.replacement_policy not in {"singleton_per_timeframe_side", "independent"}:
            raise ValueError("unsupported kernel replacement policy")
        for name in ("max_candidates", "max_evidence_rows", "max_evidence_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def kernel_id(self) -> str:
        return self.identifier.rsplit("@", 1)[0]

    @property
    def version(self) -> str:
        return self.identifier.rsplit("@", 1)[1]


KERNEL_CATALOG: Mapping[str, KernelSpec] = MappingProxyType(
    {
        previous_period_anchor.IDENTIFIER: KernelSpec(
            identifier=previous_period_anchor.IDENTIFIER,
            parse_parameters=previous_period_anchor.parse_parameters,
            history_required=previous_period_anchor.history_required,
            evaluate=previous_period_anchor.evaluate,
            replacement_policy="singleton_per_timeframe_side",
        ),
        plateau_sweep.IDENTIFIER: KernelSpec(
            identifier=plateau_sweep.IDENTIFIER,
            parse_parameters=plateau_sweep.parse_parameters,
            history_required=plateau_sweep.history_required,
            evaluate=plateau_sweep.evaluate,
            replacement_policy="independent",
        ),
    }
)


__all__ = [
    "KERNEL_CATALOG",
    "KernelEvaluation",
    "KernelSpec",
]
