"""Concrete selection strategies for the SelectionLayer."""

from libs.contracts.signal import SelectionCandidate, SelectionResult, FeatureVector
from libs.selection.base import SelectionStrategy


class ConvictionWeightedStrategy(SelectionStrategy):
    """Ranks candidates by abs(edge_score) * conviction, sorted descending."""

    def select(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
        config: dict,
    ) -> list[SelectionResult]:
        scored = []
        for c in candidates:
            score = abs(c.edge_score) * c.conviction
            scored.append((c, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (candidate, score) in enumerate(scored, start=1):
            results.append(
                SelectionResult(
                    candidate=candidate,
                    rank=rank,
                    selection_score=score,
                    penalties={},
                )
            )
        return results


class OverlapPenalizedStrategy(SelectionStrategy):
    """Ranks by conviction-weighted score, penalizing same-asset same-direction duplicates."""

    def select(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
        config: dict,
    ) -> list[SelectionResult]:
        same_direction_penalty = config.get("same_direction_penalty", 0.3)
        max_penalty = config.get("max_penalty", 0.8)

        # Sort by base score descending first
        base_scored = [(c, abs(c.edge_score) * c.conviction) for c in candidates]
        base_scored.sort(key=lambda x: x[1], reverse=True)

        selected: list[tuple[SelectionCandidate, float, dict[str, float]]] = []

        for candidate, base_score in base_scored:
            cumulative_penalty = 0.0
            for sel_candidate, _, _ in selected:
                if (
                    candidate.asset == sel_candidate.asset
                    and candidate.direction == sel_candidate.direction
                ):
                    cumulative_penalty += same_direction_penalty

            capped_penalty = min(cumulative_penalty, max_penalty)
            adjusted_score = base_score * (1.0 - capped_penalty)
            penalties = {}
            if cumulative_penalty > 0:
                penalties["overlap_penalty"] = capped_penalty

            selected.append((candidate, adjusted_score, penalties))

        # Re-sort by adjusted score
        selected.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (candidate, adj_score, penalties) in enumerate(selected, start=1):
            results.append(
                SelectionResult(
                    candidate=candidate,
                    rank=rank,
                    selection_score=adj_score,
                    penalties=penalties,
                )
            )
        return results


class TopKStrategy(SelectionStrategy):
    """Wraps an inner strategy and truncates results to top_k."""

    def __init__(self, inner: SelectionStrategy | None = None) -> None:
        self._inner = inner or OverlapPenalizedStrategy()

    def select(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
        config: dict,
    ) -> list[SelectionResult]:
        inner_results = self._inner.select(candidates, feature_vec, config)
        top_k = config.get("top_k", 3)
        return inner_results[:top_k]
