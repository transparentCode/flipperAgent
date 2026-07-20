from datetime import datetime, timedelta, timezone

from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    NormalizationStatus,
    SalienceBucket,
)
from libs.models.sr.research.studies.adaptive_context_calibration.normalization import (
    SaliencePoint,
    midrank_percentile,
    normalize_salience,
)


def _point(days: int, value: float, *, asset: str = "TAO", timeframe: str = "12h") -> SaliencePoint:
    return SaliencePoint(
        asset,
        timeframe,
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=days),
        value,
    )


def test_midrank_ties_and_current_exclusion() -> None:
    assert midrank_percentile(2.0, (1.0, 2.0, 2.0, 3.0)) == 0.5
    current = _point(10, 2.0)
    history = (_point(9, 1.0), _point(10, 2.0), _point(8, 3.0))
    result = normalize_salience(current, history)
    assert result.status is NormalizationStatus.READY
    assert result.prior_count == 2
    assert result.percentile == 0.5
    assert result.bucket is SalienceBucket.Q3


def test_365_day_boundary_and_asset_timeframe_isolation() -> None:
    current = _point(365, 2.0)
    exact_boundary = _point(0, 1.0)
    too_old = _point(-1, 4.0)
    other_asset = _point(364, 0.0, asset="ETH")
    other_timeframe = _point(364, 0.0, timeframe="1d")
    result = normalize_salience(current, (exact_boundary, too_old, other_asset, other_timeframe))
    assert result.prior_count == 1
    assert result.percentile == 1.0
    assert result.bucket is SalienceBucket.Q4


def test_empty_history_is_explicit_warmup() -> None:
    result = normalize_salience(_point(0, 1.0), ())
    assert result.status is NormalizationStatus.NORMALIZATION_WARMUP
    assert result.percentile is None
    assert result.bucket is None
