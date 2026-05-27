"""SelectionLayer — normalizes model outputs and applies selection strategies."""

from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_SELECTION
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.signal import (
    FeatureVector,
    ModelOutput,
    ScoringOutput,
    SelectionCandidate,
    SelectionResult,
)
from libs.selection.base import SelectionStrategy
from libs.selection.strategies import (
    ConvictionWeightedStrategy,
    OverlapPenalizedStrategy,
    TopKStrategy,
)

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

_STRATEGY_MAP: dict[str, type[SelectionStrategy] | callable] = {
    "conviction_weighted": ConvictionWeightedStrategy,
    "overlap_penalized": OverlapPenalizedStrategy,
    "overlap_penalized_top_k": lambda: TopKStrategy(OverlapPenalizedStrategy()),
    "top_k": lambda: TopKStrategy(ConvictionWeightedStrategy()),
}


class SelectionLayer:
    """Normalizes model outputs and applies selection strategies."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self._config: dict = {}
        self._strategy: SelectionStrategy = OverlapPenalizedStrategy()
        self._initialize()

    def _initialize(self) -> None:
        config_mgr = ConfigManager()
        config_mgr.register_file(CONFIG_FILE_SELECTION)
        sel_config = config_mgr.get("selection", {})

        # Fallback chain: asset/tf → asset/default → default/tf → default/default
        assets_config = sel_config.get("assets", {})
        asset_node = assets_config.get(self.asset, assets_config.get("default", {}))
        tf_node = asset_node.get("timeframes", {}).get(
            self.timeframe, asset_node.get("timeframes", {}).get("default", {})
        )
        self._config = tf_node if isinstance(tf_node, dict) else {}

        strategy_name = self._config.get("strategy", "overlap_penalized_top_k")
        builder = _STRATEGY_MAP.get(strategy_name)
        if builder is None:
            logger.warning(
                f"Unknown selection strategy '{strategy_name}', "
                f"falling back to overlap_penalized_top_k"
            )
            builder = _STRATEGY_MAP["overlap_penalized_top_k"]

        self._strategy = builder() if callable(builder) and not isinstance(builder, type) else builder()
        logger.info(
            f"SelectionLayer initialized for {self.asset}/{self.timeframe} "
            f"with strategy={strategy_name}"
        )

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_model_output(output: ModelOutput) -> SelectionCandidate:
        """Convert threshold-model ModelOutput to SelectionCandidate.

        edge_score = direction * conviction
        """
        return SelectionCandidate(
            model_name=output.model_name,
            asset=output.asset,
            timeframe=output.timeframe,
            timestamp=output.timestamp,
            direction=output.direction,
            edge_score=float(output.direction) * output.conviction,
            conviction=output.conviction,
            source_type="threshold",
            metadata=output.metadata,
        )

    @staticmethod
    def normalize_scoring_output(output: ScoringOutput) -> SelectionCandidate:
        """Convert ScoringOutput to SelectionCandidate.

        Direction is derived from sign of edge_score.
        """
        if output.edge_score > 0:
            direction = 1
        elif output.edge_score < 0:
            direction = -1
        else:
            direction = 0

        return SelectionCandidate(
            model_name=output.model_name,
            asset=output.asset,
            timeframe=output.timeframe,
            timestamp=output.timestamp,
            direction=direction,
            edge_score=output.edge_score,
            conviction=output.conviction,
            source_type="scoring",
            metadata=output.metadata,
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(
        self,
        model_outputs: list[ModelOutput],
        scoring_outputs: list[ScoringOutput] | None,
        feature_vec: FeatureVector,
    ) -> list[SelectionResult]:
        """Normalize all outputs and run selection strategy."""
        candidates: list[SelectionCandidate] = []

        for mo in model_outputs:
            if mo.direction != 0:
                candidates.append(self.normalize_model_output(mo))

        if scoring_outputs:
            min_edge = self._config.get("min_edge_threshold", 0.0)
            for so in scoring_outputs:
                if abs(so.edge_score) > min_edge:
                    candidates.append(self.normalize_scoring_output(so))

        if not candidates:
            return []

        return self._strategy.select(candidates, feature_vec, self._config)
