from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import SRStateKey, ZoneSide, ZoneStatus
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.scripts.candidate_reinforcement_audit.config import (
    FOLD_NAMES,
    load_candidate_audit_config,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.contracts import (
    AuditAccounting,
    AuditDecision,
    AuditDisposition,
    CandidateDecisionRecord,
    DecisionCategory,
    FoldAccounting,
    GateResult,
    ReinforcementZoneCount,
    ReplayParity,
    StatusCount,
    ZoneSeedLineage,
    CandidateReinforcementAudit,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
CONFIG_PATH = REPO_ROOT / "configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml"
STATE_KEY = SRStateKey("binance_usdm", "TAOUSDT", "1d")
BASE = datetime(2024, 7, 2, tzinfo=timezone.utc)


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture(scope="session")
def candidate_config():
    return load_candidate_audit_config(CONFIG_PATH)


def make_created(*, seed: str = "seed", side: ZoneSide = ZoneSide.SUPPORT, fold: str | None = "2024_q3") -> CandidateDecisionRecord:
    formed = BASE
    available = BASE + timedelta(days=1)
    candidate_id = digest(f"candidate:{seed}")
    zone_id = digest(f"zone:{seed}")
    return CandidateDecisionRecord(
        candidate_id=candidate_id,
        state_key=STATE_KEY,
        side=side,
        source="PIVOT_HIGH" if side is ZoneSide.RESISTANCE else "PIVOT_LOW",
        formed_at=formed,
        available_at=available,
        formed_bar_id=f"bar:{seed}:formed",
        available_bar_id=f"bar:{seed}:available",
        replay_bar_id=f"bar:{seed}:available",
        replay_closed_at=available,
        center=100.0,
        half_width=1.0,
        lower_bound=99.0,
        upper_bound=101.0,
        atr_at_creation=2.0,
        decision=DecisionCategory.CREATED_ZONE,
        target_zone_id=None,
        created_zone_id=zone_id,
        target_seed_candidate_id=None,
        target_pre_advance_status=None,
        target_post_advance_status=None,
        center_distance=None,
        center_distance_atr=None,
        merge_threshold_price=1.0,
        merge_distance_atr=0.5,
        active_zone_count_before_capacity=0,
        fold=fold,
        eligible_reinforcement=False,
    )


def make_match(seed: CandidateDecisionRecord, *, same_batch: bool = False, eligible: bool = True, side: ZoneSide | None = None) -> CandidateDecisionRecord:
    formed = BASE + timedelta(days=3)
    available = BASE + timedelta(days=4)
    target_side = seed.side if side is None else side
    return CandidateDecisionRecord(
        candidate_id=digest("candidate:match"),
        state_key=STATE_KEY,
        side=target_side,
        source="PIVOT_LOW" if target_side is ZoneSide.SUPPORT else "PIVOT_HIGH",
        formed_at=formed,
        available_at=available,
        formed_bar_id="bar:match:formed",
        available_bar_id="bar:match:available",
        replay_bar_id="bar:match:available",
        replay_closed_at=available,
        center=100.25,
        half_width=1.0,
        lower_bound=99.25,
        upper_bound=101.25,
        atr_at_creation=2.0,
        decision=DecisionCategory.MATCHED_SAME_BATCH_ZONE_SUPPRESSED if same_batch else DecisionCategory.MATCHED_START_ZONE_SUPPRESSED,
        target_zone_id=seed.created_zone_id,
        created_zone_id=None,
        target_seed_candidate_id=seed.candidate_id,
        target_pre_advance_status=None if same_batch else ZoneStatus.ACTIVE,
        target_post_advance_status=ZoneStatus.ACTIVE,
        center_distance=0.25,
        center_distance_atr=0.125,
        merge_threshold_price=1.0,
        merge_distance_atr=0.5,
        active_zone_count_before_capacity=1,
        fold="2024_q3",
        eligible_reinforcement=eligible and not same_batch,
    )


@pytest.fixture
def synthetic_audit(candidate_config):
    seed = make_created()
    match = make_match(seed)
    candidates = (seed, match)
    lineage = (ZoneSeedLineage(seed.created_zone_id, seed.candidate_id, STATE_KEY, seed.side, seed.formed_at, seed.available_at),)
    folds = tuple(
        FoldAccounting(
            fold=fold,
            candidate_count=2 if fold == "2024_q3" else 0,
            created_zone_count=1 if fold == "2024_q3" else 0,
            eligible_match_count=1 if fold == "2024_q3" else 0,
            unique_reinforced_zone_count=1 if fold == "2024_q3" else 0,
        )
        for fold in FOLD_NAMES
    )
    accounting = AuditAccounting(
        source_case_count=36,
        total_candidates=2,
        created_zone_count=1,
        matched_start_zone_suppressed=1,
        matched_same_batch_zone_suppressed=0,
        capacity_suppressed=0,
        eligible_reinforcement_count=1,
        unique_reinforced_zone_count=1,
        one_reinforcement_zone_count=1,
        two_reinforcement_zone_count=0,
        three_or_more_reinforcement_zone_count=0,
        support_candidate_count=2,
        resistance_candidate_count=0,
        out_of_fold_candidate_count=0,
        unmatched_reconciliation_count=0,
        target_post_advance_status_counts=tuple(StatusCount(status, 1 if status is ZoneStatus.ACTIVE else 0) for status in ZoneStatus),
        reinforcement_zone_counts=(ReinforcementZoneCount(seed.created_zone_id, 1),),
        folds=folds,
    )
    gates = (
        GateResult("readiness.unique_reinforced_zones", "readiness", 1, 16, ">=", False, "below threshold"),
        GateResult("readiness.comparable_folds", "readiness", 0, 4, ">=", False, "below threshold"),
        GateResult("readiness.minimum_reinforced_zones_per_comparable_fold", "readiness", 0, 2, ">=", False, "below threshold"),
    )
    decision = AuditDecision(True, AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE, gates, "synthetic")
    parity = ReplayParity(
        passed=True,
        bar_count=2,
        checkpoint_split_index=1,
        state_digest=deterministic_hash("state"),
        snapshot_digest=deterministic_hash("snapshot"),
        event_digest=deterministic_hash("event"),
        candidate_digest=deterministic_hash("candidate"),
        checkpoint_state_digest=deterministic_hash("checkpoint-state"),
        checkpoint_snapshot_digest=deterministic_hash("checkpoint-snapshot"),
        checkpoint_event_digest=deterministic_hash("checkpoint-event"),
        checks=(
            "state_identity_payload_each_bar",
            "snapshot_identity_payload_each_bar",
            "event_order_and_payload_each_bar",
            "candidate_order_each_bar",
            "created_zone_ids",
            "terminal_statuses",
            "final_state",
            "checkpoint_resume",
            "canonical_v1_replay",
        ),
    )
    return CandidateReinforcementAudit(
        implementation_commit="a" * 40,
        config_hash=candidate_config.config_hash,
        v11_bundle_id=candidate_config.v11.bundle_id,
        v11_study_id=candidate_config.v11.study_id,
        v19_bundle_id=candidate_config.v19.bundle_id,
        v19_study_id=candidate_config.v19.study_id,
        v10_bundle_id=candidate_config.v10.bundle_id,
        v10_audit_id=candidate_config.v10.audit_id,
        source_bundle_id=candidate_config.source.source_bundle_id,
        upstream_source_bundle_id=candidate_config.source.upstream_source_bundle_id,
        source_id=candidate_config.source.source_id,
        bars_sha256=candidate_config.source.bars_sha256,
        candidates=candidates,
        lineage=lineage,
        accounting=accounting,
        parity=parity,
        decision=decision,
    )
