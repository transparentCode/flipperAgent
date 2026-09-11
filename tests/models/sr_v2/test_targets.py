from datetime import timedelta
from decimal import Decimal

import pytest

from libs.models.sr_v2.contracts import ForecastOutcome, ZoneSide
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.zones import lineage_from_candidate
from libs.models.sr_v2.forecast.targets import label_forecast


def test_target_labels_no_touch_and_preserves_censoring(sr_v2_now):
    candidate = Candidate(candidate_key="z", venue="v", instrument_id="i", asset="a", source_timeframe="15m", kernel_id="k", kernel_version="1", side=ZoneSide.SUPPORT, center=Decimal(100), lower=Decimal(99), upper=Decimal(101), formed_at=sr_v2_now, available_at=sr_v2_now, source_evidence_id="e", creation_atr=Decimal(1))
    zone = lineage_from_candidate(candidate, config_fingerprint="c")
    observation = label_forecast(
        zone,
        issued_at=zone.available_at,
        future_bars=(),
        horizon=timedelta(hours=1),
        bounce_excursion_atr=Decimal(1),
        break_buffer_atr=Decimal(".5"),
        break_confirmation_bars=2,
        observation_timeframe="15m",
        observation_duration=timedelta(minutes=15),
    )
    assert observation.outcome is ForecastOutcome.NO_TOUCH
    assert observation.censored is True


def test_target_rejects_non_srbar_future_bars(sr_v2_now):
    candidate = Candidate(candidate_key="z", venue="v", instrument_id="i", asset="a", source_timeframe="15m", kernel_id="k", kernel_version="1", side=ZoneSide.SUPPORT, center=Decimal(100), lower=Decimal(99), upper=Decimal(101), formed_at=sr_v2_now, available_at=sr_v2_now, source_evidence_id="e", creation_atr=Decimal(1))
    zone = lineage_from_candidate(candidate, config_fingerprint="c")
    with pytest.raises(TypeError, match="only SRBar"):
        label_forecast(
            zone,
            issued_at=zone.available_at,
            future_bars=(object(),),
            horizon=timedelta(hours=1),
            bounce_excursion_atr=Decimal(1),
            break_buffer_atr=Decimal(".5"),
            break_confirmation_bars=2,
            observation_timeframe="15m",
            observation_duration=timedelta(minutes=15),
        )
