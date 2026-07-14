from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyRole
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_ranking_keeps_structural_importance_and_current_relevance_separate() -> None:
    config = tracker_config()
    observed = timestamp()
    strong_far = candidate(config, observed, candidate_id="strong-far", reference_price=104.0, quality=0.95, anchor_prefix="far")
    weak_near = candidate(config, observed, candidate_id="weak-near", reference_price=100.0, quality=0.70, anchor_prefix="near")
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(strong_far, weak_near),)),
        config=config,
    ).update(tracker_ohlcv(observed))

    families = {family.members[0].candidate_id: family for family in output.snapshot.active_families}
    assert families["strong-far"].structural_importance > families["weak-near"].structural_importance
    assert families["strong-far"].current_relevance < families["weak-near"].current_relevance
    assert output.ranked_support_families[0] == families["strong-far"].family_id
    assert output.nearest_support_family_id == families["weak-near"].family_id
    assert output.ranked_resistance_families == ()
    assert output.nearest_resistance_family_id is None
    assert all(family.current_role is FamilyRole.SUPPORT for family in families.values())
