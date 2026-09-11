from datetime import UTC, datetime, timedelta

from libs.models.sr_v2.research.metrics import _quantile_interval, evaluate_observations
from libs.models.sr_v2.research.observations import canonical_issuance_calendar_block


def test_empty_metrics_are_inconclusive():
    result = evaluate_observations(
        [],
        {},
        bootstrap_repetitions=1,
        bootstrap_seed="fixture",
        bootstrap_block=timedelta(days=7),
        bootstrap_epoch=datetime(1970, 1, 1, tzinfo=UTC),
        ece_bins=10,
        confidence=0.95,
        matching_strata=("asset",),
    )
    assert result.conclusion == "INCONCLUSIVE"


def test_bootstrap_epoch_and_block_are_explicit_inputs():
    issued = datetime(1970, 1, 8, tzinfo=UTC)
    assert canonical_issuance_calendar_block(
        issued,
        block=timedelta(days=7),
        epoch=datetime(1970, 1, 1, tzinfo=UTC),
    ).startswith("1970-01-08")
    assert canonical_issuance_calendar_block(
        issued,
        block=timedelta(days=7),
        epoch=datetime(1970, 1, 2, tzinfo=UTC),
    ).startswith("1970-01-02")


def test_configured_confidence_controls_bootstrap_quantiles():
    samples = list(range(100))
    assert _quantile_interval(samples.copy(), confidence=0.95) == (1, 97)
    assert _quantile_interval(samples.copy(), confidence=0.50) == (24, 75)
