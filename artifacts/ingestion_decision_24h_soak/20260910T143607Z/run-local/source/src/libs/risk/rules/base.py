"""RiskRule ABC, RiskContext dataclass, and RiskRuleRegistry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from libs.contracts.schemas import RiskVerdict, TradeSignal


@dataclass
class RiskContext:
    """Evaluation context passed to every risk rule."""

    signal: TradeSignal
    proposed_size: float
    account: Any  # AccountState — forward ref to avoid circular imports
    positions: Any  # PositionTracker — forward ref to avoid circular imports
    risk_config: dict[str, Any] = field(default_factory=dict)


class RiskRule(ABC):
    """Base class for all pluggable risk rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate(self, context: RiskContext) -> RiskVerdict:
        ...


class RiskRuleRegistry:
    """Decorator-based registry for risk rules — mirrors ModelRegistry."""

    _registry: dict[str, type[RiskRule]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: ``@RiskRuleRegistry.register("MaxExposureRule")``."""

        def wrapper(rule_class: type[RiskRule]):
            cls._registry[name] = rule_class
            return rule_class

        return wrapper

    @classmethod
    def get(cls, name: str) -> type[RiskRule]:
        if name not in cls._registry:
            raise KeyError(f"Risk rule '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
