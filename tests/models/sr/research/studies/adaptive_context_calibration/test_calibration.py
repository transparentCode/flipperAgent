from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.adaptive_context_calibration.calibration import (
    HistoricalLabel,
    brier_loss,
    calibrate,
    log_loss,
)
from libs.models.sr.research.studies.adaptive_context_calibration.contracts import SalienceBucket


def _label(days: int, asset: str, timeframe: str, bucket: SalienceBucket, value: int) -> HistoricalLabel:
    return HistoricalLabel(
        asset,
        timeframe,
        bucket,
        value,
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=days),
        1.0 if value else -1.0,
    )


def test_hierarchical_beta_counts_and_sqrt_precision() -> None:
    labels = (
        _label(-10, "ETH", "1d", SalienceBucket.Q2, 1),
        _label(-9, "ETH", "12h", SalienceBucket.Q2, 0),
        _label(-8, "TAO", "1d", SalienceBucket.Q2, 1),
        _label(-7, "TAO", "12h", SalienceBucket.Q2, 0),
    )
    result = calibrate(
        target_asset="TAO",
        target_timeframe="12h",
        bucket=SalienceBucket.Q2,
        prediction_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        labels=labels,
    )
    assert result.global_counts == (1, 1)
    assert result.asset_counts == (1, 0)
    assert result.local_counts == (0, 1)
    assert result.null_counts == (2, 2)
    assert result.global_state.alpha == pytest.approx(2**-0.5)
    assert result.global_state.beta == pytest.approx(2**-0.5)
    assert result.final_state.probability == pytest.approx((2**-0.5 + 1) / (2 * 2**-0.5 + 2))


def test_label_availability_is_strict_and_null_ignores_bucket() -> None:
    prediction_at = datetime(2025, 1, 10, tzinfo=timezone.utc)
    labels = (
        _label(-1, "TAO", "12h", SalienceBucket.Q1, 1),
        _label(9, "TAO", "12h", SalienceBucket.Q1, 1),
        _label(10, "TAO", "12h", SalienceBucket.Q1, 1),
        _label(-2, "ETH", "1d", SalienceBucket.Q4, 0),
    )
    result = calibrate(
        target_asset="TAO",
        target_timeframe="12h",
        bucket=SalienceBucket.Q1,
        prediction_at=prediction_at,
        labels=labels,
    )
    assert result.local_counts == (1, 0)
    assert result.null_counts == (1, 1)


def test_losses_are_finite_without_probability_clipping() -> None:
    assert brier_loss(0.25, 1) == pytest.approx(0.5625)
    assert log_loss(0.25, 1) == pytest.approx(-__import__("math").log(0.25))
    with pytest.raises(ContractValidationError):
        brier_loss(0.0, 1)
