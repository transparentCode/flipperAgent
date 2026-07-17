"""Canonical immutable contract for one causal candidate replay."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from libs.models.sr.domain.contracts import (
    ClosedBar,
    ContractValidationError,
    SRSnapshot,
    SRState,
)
from libs.models.sr.evaluation.contracts import SREvaluationTrace
from libs.models.sr.evaluation.diagnostics import SRDiagnostics


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{field_name} must be an integer >= {minimum}")
    return value


def _number(value: Any, *, field_name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be >= {minimum}")
    return result


@dataclass(frozen=True)
class CandidateReplay:
    """One full causal SR replay for one ATR candidate."""

    period: int
    reference_period: int
    common_start_index: int
    model_bars: tuple[ClosedBar, ...]
    reference_atr: tuple[float, ...]
    initial_state: SRState
    final_state: SRState
    snapshots: tuple[SRSnapshot, ...]
    trace: SREvaluationTrace
    diagnostics: SRDiagnostics

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", _integer(self.period, field_name="period", minimum=1))
        object.__setattr__(self, "reference_period", _integer(self.reference_period, field_name="reference_period", minimum=1))
        object.__setattr__(self, "common_start_index", _integer(self.common_start_index, field_name="common_start_index", minimum=0))
        if type(self.model_bars) is not tuple or not self.model_bars:
            raise ContractValidationError("model_bars must be a non-empty tuple")
        if any(type(bar) is not ClosedBar for bar in self.model_bars):
            raise ContractValidationError("model_bars must contain ClosedBar values")
        if type(self.reference_atr) is not tuple or len(self.reference_atr) != len(self.model_bars):
            raise ContractValidationError("reference_atr must align to model_bars")
        if any(_number(value, field_name="reference_atr", minimum=0.0) <= 0 for value in self.reference_atr):
            raise ContractValidationError("reference_atr values must be positive")
        for field_name, expected_type in (("initial_state", SRState), ("final_state", SRState), ("trace", SREvaluationTrace), ("diagnostics", SRDiagnostics)):
            if type(getattr(self, field_name)) is not expected_type:
                raise ContractValidationError(f"{field_name} has invalid type")
        if type(self.snapshots) is not tuple or any(type(item) is not SRSnapshot for item in self.snapshots):
            raise ContractValidationError("snapshots must contain SRSnapshot values")
        if len(self.snapshots) != len(self.model_bars):
            raise ContractValidationError("snapshots must align to model_bars")
        if self.initial_state.state_key != self.model_bars[0].state_key:
            raise ContractValidationError("initial state does not own model bars")
        if self.final_state.state_key != self.initial_state.state_key:
            raise ContractValidationError("final state key changed during replay")
        if self.trace.state_key != self.initial_state.state_key:
            raise ContractValidationError("trace state key does not reconcile")


__all__ = ["CandidateReplay"]
