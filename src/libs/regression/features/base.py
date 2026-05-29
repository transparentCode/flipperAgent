from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, List

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..contracts.context import PipelineRequest
from ..contracts.result import FeatureSet
from ..registry import PluginRegistry

FeatureRegistry: PluginRegistry["FeatureExtractor"] = PluginRegistry("feature")


class FeatureExtractor(ABC):
    """Base class for all feature extraction plugins.

    Subclasses declare:
        requires: what upstream features/data they need
        provides: what they add to the FeatureSet
        min_warmup_bars: minimum bars needed
    """

    requires: ClassVar[List[str]] = []
    provides: ClassVar[List[str]] = []
    min_warmup_bars: ClassVar[int] = 0

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    @abstractmethod
    def extract(
        self,
        request: PipelineRequest,
        features: FeatureSet,
    ) -> None:
        """Mutate FeatureSet in-place.

        - AND your validity checks into features.valid_mask
        - Populate the arrays you declared in `provides`
        """
        ...
