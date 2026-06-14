from __future__ import annotations

from typing import Any

from apps.portfolio_app.observability.service import PortfolioObservabilityService
from apps.portfolio_app.policy.allocator import CappedAssetAllocatorPolicy
from apps.portfolio_app.policy.base import PortfolioPolicy
from apps.portfolio_app.policy.models import PortfolioPolicyInput


class PortfolioPolicyService:
    def __init__(
        self,
        observability_service: PortfolioObservabilityService,
        policy: PortfolioPolicy | None = None,
    ) -> None:
        self.observability_service = observability_service
        self.policy = policy or CappedAssetAllocatorPolicy()

    async def recommend_rebalance(self) -> dict[str, Any]:
        sleeves = await self.observability_service.sleeves_summary()
        if sleeves.get("status") == "error":
            return {
                "status": "error",
                "recommendation": None,
                "error": sleeves.get("error", "failed to compute sleeves summary"),
                "sample": {},
            }

        utilization = sleeves.get("utilization", {})
        views = sleeves.get("views", {})
        inputs = PortfolioPolicyInput(
            equity=utilization.get("equity"),
            gross_notional=float(utilization.get("gross_notional") or 0.0),
            gross_exposure_pct=utilization.get("gross_exposure_pct"),
            open_position_count=int(utilization.get("open_position_count") or 0),
            asset_views=views.get("asset", []),
            model_views=views.get("model", []),
            timeframe_views=views.get("timeframe", []),
        )
        recommendation = self.policy.recommend(inputs)
        return {
            "status": recommendation.status,
            "recommendation": recommendation.model_dump(mode="json"),
            "error": recommendation.error,
            "sample": {
                "asset_count": len(inputs.asset_views),
                "target_count": len(recommendation.targets),
            },
        }
