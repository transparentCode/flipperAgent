from abc import ABC, abstractmethod

from libs.contracts.signal import SelectionCandidate, SelectionResult, FeatureVector


class SelectionStrategy(ABC):
    """Base class for signal selection/filtering strategies."""

    @abstractmethod
    def select(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
        config: dict,
    ) -> list[SelectionResult]:
        ...
