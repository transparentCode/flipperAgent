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
from libs.selection.overlays import apply_regime_v2_trend_gate, preview_regime_v2_trend_gate
from libs.selection.regime_v2_pa_asset_paper_guardrail import preview_pa_asset_paper_guardrail
from libs.selection.regime_v2_pa_paper_log import persist_pa_paper_decision
from libs.selection.regime_v2_shadow_log import persist_regime_v2_shadow_decision
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

        self._strategy = builder()
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

        shadow_payload = self._build_regime_v2_shadow_payload(candidates, feature_vec)
        pa_paper_payload = self._build_regime_v2_pa_paper_payload(candidates, feature_vec)

        candidates = apply_regime_v2_trend_gate(candidates, feature_vec, self._config)
        if not candidates:
            return []

        results = self._strategy.select(candidates, feature_vec, self._config)
        if shadow_payload:
            self._persist_regime_v2_shadow_payload(shadow_payload, feature_vec, selected_count=len(results))
            for result in results:
                result.candidate.metadata["regime_v2_trend_gate_shadow"] = shadow_payload
        if pa_paper_payload:
            self._persist_regime_v2_pa_paper_payload(pa_paper_payload, feature_vec, selected_count=len(results))
            for result in results:
                result.candidate.metadata["regime_v2_pa_asset_paper_guardrail"] = pa_paper_payload
        return results

    def _build_regime_v2_shadow_payload(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
    ) -> dict | None:
        gate_config = _regime_v2_gate_config(self._config)
        if not gate_config.get("shadow_enabled", False):
            return None

        baseline_results = self._strategy.select(candidates, feature_vec, self._config)
        shadow_candidates, decision = preview_regime_v2_trend_gate(
            candidates,
            feature_vec,
            self._config,
        )
        shadow_results = (
            self._strategy.select(shadow_candidates, feature_vec, self._config)
            if shadow_candidates
            else []
        )
        payload = _selection_shadow_payload(
            baseline_results,
            shadow_results,
            decision,
            shadow_candidate_count=len(shadow_candidates),
        )
        trendline_context = _trendline_shadow_context(feature_vec)
        if trendline_context:
            payload["trendline_context"] = trendline_context
        if gate_config.get("shadow_log_enabled", False):
            logger.info(
                f"RegimeV2 trend gate shadow for {self.asset}/{self.timeframe}: "
                f"baseline={payload['baseline_selected_model']} "
                f"shadow={payload['shadow_selected_model']} "
                f"changed={payload['selection_changed']} "
                f"reason={payload['reason']}"
            )
        return payload

    def _build_regime_v2_pa_paper_payload(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
    ) -> dict | None:
        guardrail_config = _pa_asset_guardrail_config(self._config)
        if not guardrail_config.get("paper_enabled", False):
            return None

        baseline_results = self._strategy.select(candidates, feature_vec, self._config)
        paper_candidates, decision = preview_pa_asset_paper_guardrail(candidates, self._config)
        paper_results = (
            self._strategy.select(paper_candidates, feature_vec, self._config)
            if paper_candidates
            else []
        )
        payload = _pa_asset_paper_payload(
            baseline_results,
            paper_results,
            decision,
            paper_candidate_count=len(paper_candidates),
        )
        if guardrail_config.get("paper_log_enabled", False):
            logger.info(
                f"RegimeV2 PA asset paper guardrail for {self.asset}/{self.timeframe}: "
                f"baseline={payload['baseline_selected_model']} "
                f"paper={payload['paper_selected_model']} "
                f"changed={payload['selection_changed']} "
                f"reason={payload['paper_reason']}"
            )
        return payload

    def _persist_regime_v2_shadow_payload(
        self,
        payload: dict,
        feature_vec: FeatureVector,
        *,
        selected_count: int,
    ) -> None:
        gate_config = _regime_v2_gate_config(self._config)
        try:
            path = persist_regime_v2_shadow_decision(
                payload,
                asset=self.asset,
                timeframe=self.timeframe,
                timestamp=feature_vec.timestamp,
                config=gate_config,
                selected_count=selected_count,
            )
        except Exception:
            logger.warning(
                "RegimeV2 shadow decision persistence failed for "
                f"{self.asset}/{self.timeframe}",
                exc_info=True,
            )
            return
        if path is not None and gate_config.get("shadow_log_enabled", False):
            logger.info(f"RegimeV2 shadow decision persisted for {self.asset}/{self.timeframe}: {path}")

    def _persist_regime_v2_pa_paper_payload(
        self,
        payload: dict,
        feature_vec: FeatureVector,
        *,
        selected_count: int,
    ) -> None:
        guardrail_config = _pa_asset_guardrail_config(self._config)
        try:
            path = persist_pa_paper_decision(
                payload,
                asset=self.asset,
                timeframe=self.timeframe,
                timestamp=feature_vec.timestamp,
                config=guardrail_config,
                selected_count=selected_count,
            )
        except Exception:
            logger.warning(
                "RegimeV2 PA asset paper persistence failed for "
                f"{self.asset}/{self.timeframe}",
                exc_info=True,
            )
            return
        if path is not None and guardrail_config.get("paper_log_enabled", False):
            logger.info(f"RegimeV2 PA asset paper decision persisted for {self.asset}/{self.timeframe}: {path}")


def _regime_v2_gate_config(config: dict) -> dict:
    overlays = config.get("overlays", {})
    if not isinstance(overlays, dict):
        return {}
    gate = overlays.get("regime_v2_trend_gate", {})
    return gate if isinstance(gate, dict) else {}


def _pa_asset_guardrail_config(config: dict) -> dict:
    overlays = config.get("overlays", {})
    if not isinstance(overlays, dict):
        return {}
    guardrail = overlays.get("regime_v2_pa_asset_guardrail", {})
    return guardrail if isinstance(guardrail, dict) else {}


def _trendline_shadow_context(feature_vec: FeatureVector) -> dict:
    trendline = feature_vec.features.get("trendline")
    if not isinstance(trendline, dict):
        return {}
    return {str(key): value for key, value in trendline.items() if str(key).startswith("trendline_")}


def _selection_shadow_payload(
    baseline_results: list[SelectionResult],
    shadow_results: list[SelectionResult],
    decision: dict,
    *,
    shadow_candidate_count: int,
) -> dict:
    baseline_top = _top_selection_summary(baseline_results)
    shadow_top = _top_selection_summary(shadow_results)
    baseline_score = baseline_top.get("selection_score")
    shadow_score = shadow_top.get("selection_score")
    edge_delta = (
        float(shadow_score) - float(baseline_score)
        if baseline_score is not None and shadow_score is not None
        else None
    )
    baseline_model = baseline_top.get("model_name")
    shadow_model = shadow_top.get("model_name")
    selection_changed = baseline_model != shadow_model
    conflict_models = list(decision.get("conflict_target_models", []))
    aligned_models = list(decision.get("aligned_target_models", []))

    if selection_changed:
        comparison_reason = "shadow_changed_top_pick"
    elif conflict_models:
        comparison_reason = "conflicts_filtered_below_top_pick"
    elif aligned_models:
        comparison_reason = "top_pick_aligned_with_regime"
    else:
        comparison_reason = str(decision.get("reason", "unknown"))

    return {
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "baseline_selected_direction": baseline_top.get("direction"),
        "shadow_selected_direction": shadow_top.get("direction"),
        "baseline_edge_score": baseline_top.get("edge_score"),
        "shadow_edge_score": shadow_top.get("edge_score"),
        "baseline_conviction": baseline_top.get("conviction"),
        "shadow_conviction": shadow_top.get("conviction"),
        "baseline_selection_score": baseline_score,
        "shadow_selection_score": shadow_score,
        "edge_delta": edge_delta,
        "selection_changed": selection_changed,
        "reason": comparison_reason,
        "gate_active": bool(decision.get("active", False)),
        "gate_reason": decision.get("reason"),
        "regime_side": decision.get("regime_side"),
        "active_playbooks": list(decision.get("active_playbooks", [])),
        "candidate_playbooks": dict(decision.get("candidate_playbooks", {})),
        "shadow_subset_name": decision.get("shadow_subset_name"),
        "shadow_subset_only": bool(decision.get("shadow_subset_only", False)),
        "include_non_target_models": bool(decision.get("include_non_target_models", True)),
        "target_models": list(decision.get("target_models", [])),
        "allow_trend_following": decision.get("allow_trend_following"),
        "allow_breakout": decision.get("allow_breakout"),
        "allow_mean_reversion": decision.get("allow_mean_reversion"),
        "trend_score": decision.get("trend_score"),
        "breakout_score": decision.get("breakout_score"),
        "mean_reversion_score": decision.get("mean_reversion_score"),
        "min_trend_score": decision.get("min_trend_score"),
        "min_breakout_score": decision.get("min_breakout_score"),
        "min_mean_reversion_score": decision.get("min_mean_reversion_score"),
        "min_confidence": decision.get("min_confidence"),
        "confidence": decision.get("confidence"),
        "uncertainty": decision.get("uncertainty"),
        "baseline_candidate_count": decision.get("baseline_candidate_count"),
        "shadow_candidate_count": shadow_candidate_count,
        "shadow_selected_count": len(shadow_results),
        "target_candidate_count": decision.get("target_candidate_count"),
        "aligned_target_models": aligned_models,
        "conflict_target_models": conflict_models,
    }


def _pa_asset_paper_payload(
    baseline_results: list[SelectionResult],
    paper_results: list[SelectionResult],
    decision: dict,
    *,
    paper_candidate_count: int,
) -> dict:
    baseline_top = _top_selection_summary(baseline_results)
    paper_top = _top_selection_summary(paper_results)
    baseline_score = baseline_top.get("selection_score")
    paper_score = paper_top.get("selection_score")
    edge_delta = (
        float(paper_score) - float(baseline_score)
        if baseline_score is not None and paper_score is not None
        else None
    )
    baseline_model = baseline_top.get("model_name")
    paper_model = paper_top.get("model_name")
    return {
        "paper_active": bool(decision.get("active", False)),
        "paper_reason": decision.get("reason"),
        "target_model": decision.get("target_model"),
        "target_asset": decision.get("target_asset"),
        "target_timeframe": decision.get("target_timeframe"),
        "target_direction": decision.get("target_direction"),
        "suppressed_count": decision.get("suppressed_count"),
        "suppressed_models": list(decision.get("suppressed_models", [])),
        "suppressed_edge_scores": list(decision.get("suppressed_edge_scores", [])),
        "suppressed_convictions": list(decision.get("suppressed_convictions", [])),
        "baseline_selected_model": baseline_model,
        "paper_selected_model": paper_model,
        "baseline_selected_direction": baseline_top.get("direction"),
        "paper_selected_direction": paper_top.get("direction"),
        "baseline_edge_score": baseline_top.get("edge_score"),
        "paper_edge_score": paper_top.get("edge_score"),
        "baseline_conviction": baseline_top.get("conviction"),
        "paper_conviction": paper_top.get("conviction"),
        "baseline_selection_score": baseline_score,
        "paper_selection_score": paper_score,
        "edge_delta": edge_delta,
        "selection_changed": baseline_model != paper_model,
        "candidate_count": decision.get("candidate_count"),
        "paper_candidate_count": paper_candidate_count,
        "paper_selected_count": len(paper_results),
        "candidate_snapshot_schema_version": 1,
        "baseline_ranked_candidates": _ranked_selection_snapshot(baseline_results),
        "paper_ranked_candidates": _ranked_selection_snapshot(paper_results),
    }


def _top_selection_summary(results: list[SelectionResult]) -> dict:
    if not results:
        return {}
    top = results[0]
    return {
        "model_name": top.candidate.model_name,
        "direction": int(top.candidate.direction),
        "edge_score": float(top.candidate.edge_score),
        "conviction": float(top.candidate.conviction),
        "selection_score": float(top.selection_score),
    }


def _ranked_selection_snapshot(results: list[SelectionResult]) -> list[dict]:
    snapshots: list[dict] = []
    for result in results:
        candidate = result.candidate
        snapshots.append(
            {
                "rank": int(result.rank),
                "model_name": candidate.model_name,
                "asset": candidate.asset,
                "timeframe": candidate.timeframe,
                "direction": int(candidate.direction),
                "edge_score": float(candidate.edge_score),
                "conviction": float(candidate.conviction),
                "selection_score": float(result.selection_score),
                "penalties": dict(result.penalties),
            }
        )
    return snapshots
