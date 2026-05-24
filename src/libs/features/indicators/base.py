from abc import ABC, abstractmethod
from typing import Sequence, TypeVar, Generic

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")

class Indicator(ABC, Generic[TInput, TOutput]):
    def __init__(self):
        self._is_primed = False

    @property
    @abstractmethod
    def lookback_required(self) -> int:
        pass

    @property
    def is_primed(self) -> bool:
        return self._is_primed

    @abstractmethod
    def batch(self, data: Sequence[TInput]) -> Sequence[TOutput]:
        """Offline backtesting over vectorized inputs."""
        pass

    @abstractmethod
    def prime(self, historical_data: Sequence[TInput]) -> None:
        """Pre-warms the live internal state."""
        pass

    @abstractmethod
    def update(self, new_value: TInput) -> TOutput:
        """Event-driven live trading update."""
        pass
