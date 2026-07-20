from datetime import datetime, timedelta, timezone

import pytest
import numpy as np

from libs.models.sr.domain import CandidateLevel, ContractValidationError, SRStateKey, ZoneGeometry, ZoneSide
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.studies.relative_salience_rank_utility.config import load_relative_salience_rank_config
from libs.models.sr.research.studies.relative_salience_rank_utility.contracts import CaseStatus, ControlRecord, RankCase, RankDisposition
from libs.models.sr.research.studies.relative_salience_rank_utility.metrics import (
    SaliencePoint,
    assess,
    hierarchical_bootstrap,
    quartile,
    relative_salience_rank,
)
from libs.models.sr.research.studies.relative_salience_rank_utility import metrics as metrics_module


UTC = timezone.utc


def _point(asset: str, timeframe: str, day: int, value: float, identity: str) -> SaliencePoint:
    return SaliencePoint(asset, timeframe, datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day), value, identity)


def test_rank_is_same_cohort_point_in_time_and_tie_deterministic() -> None:
    current = _point("TAOUSDT", "1d", 366, 4.0, "current")
    history = (
        _point("TAOUSDT", "1d", 1, 1.0, "old"),
        _point("TAOUSDT", "1d", 2, 4.0, "tie"),
        _point("ETHUSDT", "1d", 365, 0.0, "other-asset"),
        _point("TAOUSDT", "12h", 365, 0.0, "other-timeframe"),
        _point("TAOUSDT", "1d", 367, 0.0, "future"),
    )
    rank, count = relative_salience_rank(current, history)
    assert (rank, count) == (0.75, 2)
    assert relative_salience_rank(current, tuple(reversed(history))) == (rank, count)
    assert quartile(rank).value == "Q4"


def test_rank_requires_prior_causal_history() -> None:
    current = _point("TAOUSDT", "1d", 1, 1.0, "current")
    with pytest.raises(ContractValidationError, match="causal same-cohort"):
        relative_salience_rank(current, ())


def _outcome(candidate: CandidateLevel, quality: float) -> FirstTouchOutcome:
    favorable = max(quality, 0.0)
    adverse = max(-quality, 0.0)
    return FirstTouchOutcome(candidate.candidate_id, candidate.side, candidate.available_at, candidate.candidate_id, 100.0, 1.0, True, False, candidate.available_at + timedelta(days=10), favorable, adverse, quality, False)


def _case(index: int, *, quality: float) -> RankCase:
    asset, timeframe = (("TAOUSDT", "1d"), ("ETHUSDT", "1d"), ("SOLUSDT", "1d"), ("TAOUSDT", "12h"), ("ETHUSDT", "12h"), ("SOLUSDT", "12h"))[index % 6]
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    key = SRStateKey("binance_usdm", asset, timeframe)
    side = ZoneSide.SUPPORT
    candidate = CandidateLevel(key, side, ZoneGeometry(100.0 + index, 1.0), "test", timestamp, timestamp, 1.0)
    real = _outcome(candidate, quality)
    controls = []
    for control_side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
        control = CandidateLevel(key, control_side, ZoneGeometry(99.0 + index, 1.0), "control", timestamp, timestamp, 1.0)
        controls.append(ControlRecord(control_side, control, CaseStatus.COMPLETED, _outcome(control, 0.0)))
    rank = (0.125, 0.375, 0.625, 0.875)[index % 4]
    return RankCase(asset, timeframe, index + 1, candidate, rank, rank, 10, quartile(rank), CaseStatus.COMPLETED, real, tuple(controls), controls[0].outcome, quality, "2026-01")


def test_readiness_boundary_and_bootstrap_are_deterministic(monkeypatch) -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    insufficient = tuple(_case(index, quality=1.0 if index % 4 == 3 else -1.0) for index in range(349))
    _, _, disposition = assess(insufficient, config=config)
    assert disposition is RankDisposition.INSUFFICIENT_SOURCE_DENSITY
    class _DeterministicGenerator:
        def integers(self, _low, high, *, size):
            return np.arange(size) % high

    monkeypatch.setattr(metrics_module.np.random, "Generator", lambda _bit_generator: _DeterministicGenerator())
    completed = tuple(_case(index, quality=1.0 if index % 4 == 3 else -1.0) for index in range(24))
    intervals = hierarchical_bootstrap(completed)
    assert tuple(intervals) == (
        "median_cohort_rank_lift",
        "q4_mean_paired_excess_quality_atr",
        "q4_success_lift",
        "rank_auc",
    )
    assert all(lower <= upper for lower, upper in intervals.values())
    assert intervals == hierarchical_bootstrap(completed)
