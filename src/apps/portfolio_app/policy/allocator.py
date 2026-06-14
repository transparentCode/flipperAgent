from __future__ import annotations

import time

from apps.portfolio_app.api.models import PortfolioRebalanceRecommendation, PortfolioTargetWeight
from apps.portfolio_app.policy.base import PortfolioPolicy
from apps.portfolio_app.policy.models import PortfolioPolicyInput


class CappedAssetAllocatorPolicy(PortfolioPolicy):
    def __init__(
        self,
        *,
        max_asset_weight_pct: float = 40.0,
        min_rebalance_delta_pct: float = 5.0,
    ) -> None:
        self.max_asset_weight_pct = max_asset_weight_pct
        self.min_rebalance_delta_pct = min_rebalance_delta_pct

    def recommend(self, inputs: PortfolioPolicyInput) -> PortfolioRebalanceRecommendation:
        summary = {
            "equity": inputs.equity,
            "gross_notional": inputs.gross_notional,
            "gross_exposure_pct": inputs.gross_exposure_pct,
            "open_position_count": inputs.open_position_count,
            "asset_count": len(inputs.asset_views),
            "overweight_asset_count": 0,
        }
        constraints = {
            "max_asset_weight_pct": self.max_asset_weight_pct,
            "min_rebalance_delta_pct": self.min_rebalance_delta_pct,
        }

        if not inputs.asset_views or inputs.gross_notional <= 0:
            return PortfolioRebalanceRecommendation(
                status="ok",
                policy_name="capped_asset_allocator",
                generated_at=time.time(),
                summary=summary,
                targets=[],
                constraints=constraints,
                notes=["No active asset sleeves available for rebalance recommendations."],
            )

        if len(inputs.asset_views) == 1:
            bucket = inputs.asset_views[0]
            return PortfolioRebalanceRecommendation(
                status="ok",
                policy_name="capped_asset_allocator",
                generated_at=time.time(),
                summary={
                    **summary,
                    "overweight_asset_count": int(bucket.gross_weight_pct > self.max_asset_weight_pct),
                },
                targets=[],
                constraints=constraints,
                notes=[
                    "Single-asset concentration detected; this endpoint only emits recommendations and does not execute de-risking.",
                ],
            )

        current_weights = {bucket.group_key: float(bucket.gross_weight_pct) for bucket in inputs.asset_views}
        target_weights = current_weights.copy()
        overflow = 0.0
        overweight_assets = 0

        recipients = [
            bucket.group_key
            for bucket in inputs.asset_views
            if current_weights[bucket.group_key] < self.max_asset_weight_pct
        ]
        for key, weight in current_weights.items():
            if weight > self.max_asset_weight_pct:
                overflow += weight - self.max_asset_weight_pct
                overweight_assets += 1
                target_weights[key] = self.max_asset_weight_pct

        remaining = overflow
        active_recipients = recipients[:]
        while remaining > 1e-9 and active_recipients:
            share = remaining / len(active_recipients)
            distributed = 0.0
            next_recipients: list[str] = []
            for key in active_recipients:
                capacity = self.max_asset_weight_pct - target_weights[key]
                addition = min(capacity, share)
                if addition > 0:
                    target_weights[key] += addition
                    distributed += addition
                if self.max_asset_weight_pct - target_weights[key] > 1e-9:
                    next_recipients.append(key)
            if distributed <= 1e-9:
                break
            remaining -= distributed
            active_recipients = next_recipients

        targets: list[PortfolioTargetWeight] = []
        for bucket in inputs.asset_views:
            current_weight = float(bucket.gross_weight_pct)
            target_weight = float(target_weights[bucket.group_key])
            delta = target_weight - current_weight
            if abs(delta) < self.min_rebalance_delta_pct:
                continue
            targets.append(
                PortfolioTargetWeight(
                    group_type="asset",
                    group_key=bucket.group_key,
                    current_weight_pct=current_weight,
                    target_weight_pct=target_weight,
                    delta_weight_pct=delta,
                    current_gross_notional=float(bucket.gross_notional),
                    target_gross_notional=inputs.gross_notional * target_weight / 100.0,
                    rationale=(
                        "Reduce concentration above asset cap."
                        if delta < 0
                        else "Receive redistributed gross notional from capped sleeves."
                    ),
                )
            )

        notes = ["Recommendation-only output; execution, sizing, and safety gates stay downstream."]
        if overflow <= 0:
            notes.append("Current asset sleeves already sit within the configured cap.")

        return PortfolioRebalanceRecommendation(
            status="ok",
            policy_name="capped_asset_allocator",
            generated_at=time.time(),
            summary={**summary, "overweight_asset_count": overweight_assets},
            targets=targets,
            constraints=constraints,
            notes=notes,
        )
