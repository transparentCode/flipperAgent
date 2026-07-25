from __future__ import annotations

from app.trendlines.boundary import QualityMetrics, Ray


def _ray(level: float, *, is_support: bool) -> Ray:
    return Ray(
        start_time=0,
        end_time=1,
        start_price=level,
        end_price=level,
        slope=0.0,
        intercept=level,
        touch_count=3,
        is_support=is_support,
        score=0.8,
        metadata={"normalized_quality_score": 0.8},
    )


def test_quality_metrics_reports_absolute_hull_width_atr():
    metrics = QualityMetrics.from_result(
        support_rays=[_ray(110.0, is_support=True)],
        resistance_rays=[_ray(100.0, is_support=False)],
        hull_floor=110.0,
        hull_ceiling=100.0,
        mean_atr=2.0,
    )

    assert metrics.hull_width_atr == 5.0
