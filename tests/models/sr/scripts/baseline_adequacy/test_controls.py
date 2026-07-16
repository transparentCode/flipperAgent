from __future__ import annotations

from libs.models.sr.domain.contracts import ZoneSide
from libs.models.sr.scripts.baseline_adequacy.controls import build_controls


def test_controls_have_complete_accounting_and_two_directional_outcomes(frozen_inputs, adequacy_config):
    tao = frozen_inputs.tao_source
    from libs.models.sr.scripts.cohort_readiness.metrics import replay_asset

    replay = replay_asset(frozen_inputs.v17_config, tao, frozen_inputs.resolved_configs["TAOUSDT"], implementation_commit="a" * 40).replay
    result = build_controls(replay, config=adequacy_config)
    assert result.accounting.total_considered == len(replay.model_bars)
    assert result.accounting.total_considered == result.accounting.total_eligible + sum(count for _, count in result.accounting.rejected)
    assert len(result.outcomes) == result.accounting.total_eligible * 2
    for anchor in (item for item in result.anchors if item.eligible):
        outcomes = tuple(item for item in result.outcomes if item.anchor_id == anchor.anchor_id)
        assert tuple(item.side for item in outcomes) == (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)


def test_inclusive_visible_zone_rejections_are_present(frozen_inputs, adequacy_config):
    tao = frozen_inputs.tao_source
    from libs.models.sr.scripts.cohort_readiness.metrics import replay_asset

    replay = replay_asset(frozen_inputs.v17_config, tao, frozen_inputs.resolved_configs["TAOUSDT"], implementation_commit="a" * 40).replay
    result = build_controls(replay, config=adequacy_config)
    reasons = {item.reason.value for item in result.anchors}
    assert "ENTRY_VISIBLE_ZONE_INTERSECTION" in reasons
    assert "INCOMPLETE_SAME_FOLD_HORIZON" in reasons
