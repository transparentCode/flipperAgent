from __future__ import annotations

from pydantic import BaseModel, Field

from apps.portfolio_app.api.models import PortfolioExposureBucket


class PortfolioPolicyInput(BaseModel):
    equity: float | None = None
    gross_notional: float = 0.0
    gross_exposure_pct: float | None = None
    open_position_count: int = 0
    asset_views: list[PortfolioExposureBucket] = Field(default_factory=list)
    model_views: list[PortfolioExposureBucket] = Field(default_factory=list)
    timeframe_views: list[PortfolioExposureBucket] = Field(default_factory=list)
