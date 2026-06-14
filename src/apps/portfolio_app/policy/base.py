from __future__ import annotations

from typing import Protocol

from apps.portfolio_app.api.models import PortfolioRebalanceRecommendation
from apps.portfolio_app.policy.models import PortfolioPolicyInput


class PortfolioPolicy(Protocol):
    def recommend(self, inputs: PortfolioPolicyInput) -> PortfolioRebalanceRecommendation: ...
