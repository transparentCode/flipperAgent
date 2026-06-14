from __future__ import annotations

from apps.portfolio_app.api.models import PortfolioExposureBucket
from apps.portfolio_app.policy import CappedAssetAllocatorPolicy, PortfolioPolicyInput


def _bucket(group_key: str, gross_weight_pct: float, gross_notional: float) -> PortfolioExposureBucket:
    return PortfolioExposureBucket(
        group_key=group_key,
        position_count=1,
        net_notional=gross_notional,
        gross_notional=gross_notional,
        long_notional=max(gross_notional, 0.0),
        short_notional=0.0,
        gross_weight_pct=gross_weight_pct,
    )


def test_policy_returns_empty_recommendation_without_assets() -> None:
    policy = CappedAssetAllocatorPolicy()

    result = policy.recommend(PortfolioPolicyInput(gross_notional=0.0))

    assert result.policy_name == "capped_asset_allocator"
    assert result.targets == []
    assert "No active asset sleeves" in result.notes[0]


def test_policy_flags_single_asset_concentration_without_execution_target() -> None:
    policy = CappedAssetAllocatorPolicy()

    result = policy.recommend(
        PortfolioPolicyInput(
            gross_notional=2500.0,
            asset_views=[_bucket("BTCUSDT", 100.0, 2500.0)],
        )
    )

    assert result.targets == []
    assert "Single-asset concentration" in result.notes[0]
    assert result.summary["overweight_asset_count"] == 1


def test_policy_redistributes_overweight_asset_across_other_assets() -> None:
    policy = CappedAssetAllocatorPolicy(max_asset_weight_pct=40.0, min_rebalance_delta_pct=5.0)

    result = policy.recommend(
        PortfolioPolicyInput(
            gross_notional=10000.0,
            asset_views=[
                _bucket("BTCUSDT", 70.0, 7000.0),
                _bucket("ETHUSDT", 20.0, 2000.0),
                _bucket("SOLUSDT", 10.0, 1000.0),
            ],
        )
    )

    assert len(result.targets) == 3
    targets = {target.group_key: target for target in result.targets}
    assert targets["BTCUSDT"].target_weight_pct == 40.0
    assert targets["BTCUSDT"].delta_weight_pct == -30.0
    assert targets["ETHUSDT"].target_weight_pct == 35.0
    assert targets["SOLUSDT"].target_weight_pct == 25.0


def test_policy_omits_small_deltas_below_threshold() -> None:
    policy = CappedAssetAllocatorPolicy(max_asset_weight_pct=40.0, min_rebalance_delta_pct=15.0)

    result = policy.recommend(
        PortfolioPolicyInput(
            gross_notional=10000.0,
            asset_views=[
                _bucket("BTCUSDT", 50.0, 5000.0),
                _bucket("ETHUSDT", 30.0, 3000.0),
                _bucket("SOLUSDT", 20.0, 2000.0),
            ],
        )
    )

    assert result.targets == []
