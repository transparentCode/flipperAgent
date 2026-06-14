from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from libs.contracts.schemas import BenchmarkComparison, ClosedTrade, PerformanceSummary, PnLAttribution


class PortfolioTradesResponse(BaseModel):
    status: str
    count: int
    total: int
    trades: list[ClosedTrade]


class PortfolioPerformanceResponse(BaseModel):
    status: str
    performance: PerformanceSummary | None = None
    sample: dict[str, int | float] = Field(default_factory=dict)
    error: str | None = None


class PortfolioAttributionResponse(BaseModel):
    status: str
    group_by: Literal["asset", "model", "timeframe"]
    count: int
    attribution: list[PnLAttribution]
    error: str | None = None


class BenchmarkPricePoint(BaseModel):
    timestamp: float
    price: float


class PortfolioBenchmarkRequest(BaseModel):
    benchmark_name: str = "BTC_BUY_HOLD"
    benchmark_prices: list[BenchmarkPricePoint]
    start_timestamp: float | None = None
    end_timestamp: float | None = None
    interval_seconds: int = Field(default=3600, ge=1)
    risk_free_rate: float = 0.0


class PortfolioBenchmarkResponse(BaseModel):
    status: str
    comparison: BenchmarkComparison | None = None
    sample: dict[str, int | float] = Field(default_factory=dict)
    error: str | None = None


class PortfolioExposureBucket(BaseModel):
    group_key: str
    position_count: int
    net_notional: float
    gross_notional: float
    long_notional: float
    short_notional: float
    gross_weight_pct: float = 0.0


class PortfolioExposureGroupResponse(BaseModel):
    status: str
    group_by: Literal["asset", "model", "timeframe"]
    total_exposure: float
    groups: list[PortfolioExposureBucket]
    error: str | None = None


class PortfolioSleevesResponse(BaseModel):
    status: str
    utilization: dict[str, int | float | None]
    concentration: dict[str, int | float | str | None]
    counts: dict[str, int]
    views: dict[str, list[PortfolioExposureBucket]]
    error: str | None = None


class PortfolioTargetWeight(BaseModel):
    group_type: Literal["asset", "model", "timeframe"]
    group_key: str
    current_weight_pct: float
    target_weight_pct: float
    delta_weight_pct: float
    current_gross_notional: float
    target_gross_notional: float | None = None
    rationale: str = ""


class PortfolioRebalanceRecommendation(BaseModel):
    status: str
    policy_name: str
    generated_at: float
    summary: dict[str, int | float | str | None]
    targets: list[PortfolioTargetWeight]
    constraints: dict[str, int | float | str | None]
    notes: list[str]
    error: str | None = None


class PortfolioRebalanceResponse(BaseModel):
    status: str
    recommendation: PortfolioRebalanceRecommendation | None = None
    error: str | None = None
    sample: dict[str, int | float] = Field(default_factory=dict)
