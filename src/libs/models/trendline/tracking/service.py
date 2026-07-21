"""Deterministic single-timeframe Phase-C family tracker."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

import pandas as pd

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..domain.candidates import LineCandidate
from ..domain.enums import FamilyLifecycleState, FamilyRole, FamilyTransitionType
from ..domain.events import FamilyInteractionEvent, FamilyTransition
from ..domain.families import (
    FamilyCorridor,
    FamilyMember,
    FamilySourceGroupAudit,
    LineUncertainty,
    TrendlineFamilyState,
)
from ..domain.identity import deterministic_hash, deterministic_id
from ..domain.interactions import FamilyInteractionObservation
from ..domain.snapshots import (
    TrendlineFamilyOutput,
    TrendlineFamilySnapshot,
    compute_trendline_family_snapshot_id,
)
from ..domain.validation import ContractValidationError, require_utc
from .corridors import build_family_corridors
from ..interaction.lifecycle import (
    EventLifecycleResult,
    advance_interaction_events,
    pending_role_reversal_family_ids,
)
from ..interaction.state import opposite_role
from ..interaction.features import build_interaction_features
from ..interaction.observations import (
    InteractionAtr,
    calculate_interaction_atr,
    evaluate_family_interaction,
    validate_tick_size,
)
from .matching import (
    FamilyCandidateMatch,
    FamilyRailGroupMatch,
    NormalizationAtr,
    calculate_normalization_atr,
    greedy_match_rail_groups,
)
from ..discovery.pivots import confirmed_ohlcv_window
from ..discovery.contracts import CandidateGenerationResult, CandidateGenerationStatus, LineCandidateProvider
from .rails import (
    RailCandidateGroup,
    RailGroupingResult,
    RailMemberMatch,
    group_rail_candidates,
    match_group_members,
    select_representative_member,
    score_member_candidate,
    subset_rail_candidate_group,
)
from .ranking import current_relevance as calculate_current_relevance
from .ranking import nearest_role_id, rank_families, ranked_role_ids
from ..storage.repository import TrendlineFamilyRepository


class TrendlineFamilyUpdateError(ContractValidationError):
    """Raised for a failed-closed Phase-C update before repository persistence."""


_NORMAL_ABSTENTIONS = {
    CandidateGenerationStatus.INSUFFICIENT_DATA,
    CandidateGenerationStatus.NO_CONFIRMED_PIVOTS,
    CandidateGenerationStatus.NO_VALID_FITTED_PATHS,
    CandidateGenerationStatus.REJECTED_LOW_QUALITY,
}


@dataclass
class _FamilyDraft:
    previous: TrendlineFamilyState | None
    state: TrendlineFamilyState | None
    transition_type: FamilyTransitionType
    candidate: LineCandidate | None
    association: FamilyCandidateMatch | FamilyRailGroupMatch | None
    reason_codes: tuple[str, ...]
    is_birth: bool = False
    group: RailCandidateGroup | None = None
    member_matches: tuple[RailMemberMatch, ...] = ()
    representative_changed: bool = False


@dataclass(frozen=True)
class _PreparedUpdatePhase:
    timestamp: datetime
    frame: pd.DataFrame
    tick_size: float | None


@dataclass(frozen=True)
class _PriorStatePhase:
    previous_snapshot: TrendlineFamilySnapshot | None
    previous_events: tuple[FamilyInteractionEvent, ...]
    previous_families: tuple[TrendlineFamilyState, ...]
    scheduled_role_reversals: frozenset[str]
    applied_role_reversals: frozenset[str]


@dataclass(frozen=True)
class _CandidatePhase:
    provider_result: CandidateGenerationResult
    candidates: tuple[LineCandidate, ...]
    current_price: float


@dataclass(frozen=True)
class _AssociationPhase:
    atr: NormalizationAtr | None
    grouping: RailGroupingResult
    groups: tuple[RailCandidateGroup, ...]
    matches: tuple[FamilyRailGroupMatch, ...]


@dataclass(frozen=True)
class _LifecyclePhase:
    drafts: tuple[_FamilyDraft, ...]
    rejected_birth_ids: tuple[str, ...]
    unmatched_active_count: int
    applied_role_reversals: frozenset[str]
    deferred_role_reversals: frozenset[str]


@dataclass(frozen=True)
class _InteractionPhase:
    interaction_atr: InteractionAtr | None
    observations: tuple[FamilyInteractionObservation, ...]
    active_families: tuple[TrendlineFamilyState, ...]
    dormant_families: tuple[TrendlineFamilyState, ...]
    corridors: tuple[FamilyCorridor, ...]
    event_result: EventLifecycleResult


class TrendlineFamilyTracker:
    """Apply one confirmed-bar candidate observation to immutable family state."""

    def __init__(
        self,
        *,
        repository: TrendlineFamilyRepository,
        provider: LineCandidateProvider,
        config: ResolvedTrendlineFamilyConfig,
    ) -> None:
        if not isinstance(config, ResolvedTrendlineFamilyConfig):
            raise TrendlineFamilyUpdateError("tracker requires ResolvedTrendlineFamilyConfig")
        self.repository = repository
        self.provider = provider
        self.config = config

    def update(
        self,
        ohlcv: pd.DataFrame,
        *,
        observed_at: datetime | None = None,
        tick_size: float | None = None,
    ) -> TrendlineFamilyOutput:
        prepared = self._prepare_update_phase(
            ohlcv,
            observed_at=observed_at,
            tick_size=tick_size,
        )
        prior = self._load_prior_state_phase(timestamp=prepared.timestamp)
        candidate_phase = self._generate_candidate_phase(
            frame=prepared.frame,
            timestamp=prepared.timestamp,
        )
        association = self._associate_rails_phase(
            frame=prepared.frame,
            timestamp=prepared.timestamp,
            candidates=candidate_phase.candidates,
            prior=prior,
        )
        lifecycle = self._advance_family_lifecycle_phase(
            timestamp=prepared.timestamp,
            current_price=candidate_phase.current_price,
            candidates=candidate_phase.candidates,
            previous_families=prior.previous_families,
            association=association,
            scheduled_role_reversals=prior.scheduled_role_reversals,
            applied_role_reversals=prior.applied_role_reversals,
        )
        interaction = self._advance_interaction_phase(
            lifecycle=lifecycle,
            frame=prepared.frame,
            timestamp=prepared.timestamp,
            tick_size=prepared.tick_size,
            previous_events=prior.previous_events,
            atr=association.atr,
        )
        snapshot = self._build_snapshot_phase(
            timestamp=prepared.timestamp,
            prior=prior,
            candidate_phase=candidate_phase,
            association=association,
            lifecycle=lifecycle,
            interaction=interaction,
        )
        self._persist_snapshot_phase(snapshot)
        return self._build_output_phase(
            snapshot,
            current_price=candidate_phase.current_price,
            atr=association.atr,
        )

    def _prepare_update_phase(
        self,
        ohlcv: pd.DataFrame,
        *,
        observed_at: datetime | None,
        tick_size: float | None,
    ) -> _PreparedUpdatePhase:
        timestamp, frame = self._prepare_confirmed_frame(
            ohlcv,
            observed_at=observed_at,
        )
        try:
            normalized_tick_size = validate_tick_size(tick_size)
        except ContractValidationError as exc:
            raise TrendlineFamilyUpdateError(str(exc)) from exc
        return _PreparedUpdatePhase(
            timestamp=timestamp,
            frame=frame,
            tick_size=normalized_tick_size,
        )

    def _load_prior_state_phase(self, *, timestamp: datetime) -> _PriorStatePhase:
        previous_snapshot = self.repository.latest_snapshot(
            self.config.asset,
            self.config.timeframe,
        )
        if previous_snapshot is not None:
            self._assert_repository_head_compatible(previous_snapshot)
            if timestamp <= previous_snapshot.timestamp:
                raise TrendlineFamilyUpdateError(
                    "update timestamp must advance beyond repository head"
                )
        previous_events = (
            () if previous_snapshot is None else previous_snapshot.interaction_events
        )
        scheduled_role_reversals = pending_role_reversal_family_ids(previous_events)
        previous_families, applied_role_reversals = (
            ((), frozenset())
            if previous_snapshot is None
            else self._apply_pending_role_reversals(
                previous_snapshot.active_families
                + previous_snapshot.dormant_families,
                scheduled_role_reversals=scheduled_role_reversals,
            )
        )
        return _PriorStatePhase(
            previous_snapshot=previous_snapshot,
            previous_events=previous_events,
            previous_families=previous_families,
            scheduled_role_reversals=scheduled_role_reversals,
            applied_role_reversals=applied_role_reversals,
        )

    def _generate_candidate_phase(
        self,
        *,
        frame: pd.DataFrame,
        timestamp: datetime,
    ) -> _CandidatePhase:
        provider_result = self.provider.generate(
            frame,
            asset=self.config.asset,
            timeframe=self.config.timeframe,
            observed_at=timestamp,
            config=self.config,
        )
        if not isinstance(provider_result, CandidateGenerationResult):
            raise TrendlineFamilyUpdateError(
                "candidate provider returned a non-canonical result"
            )
        if provider_result.status is CandidateGenerationStatus.PROVIDER_CONFIG_ERROR:
            raise TrendlineFamilyUpdateError(
                f"candidate provider failed closed: {', '.join(provider_result.reason_codes)}"
            )
        if provider_result.status not in _NORMAL_ABSTENTIONS | {
            CandidateGenerationStatus.VALID
        }:
            raise TrendlineFamilyUpdateError(
                "candidate provider returned an unsupported status"
            )
        candidates = (
            tuple(
                sorted(
                    provider_result.candidates,
                    key=lambda candidate: candidate.candidate_id,
                )
            )
            if provider_result.status is CandidateGenerationStatus.VALID
            else ()
        )
        self._validate_candidates(candidates, timestamp=timestamp)
        return _CandidatePhase(
            provider_result=provider_result,
            candidates=candidates,
            current_price=float(frame["close"].iloc[-1]),
        )

    def _associate_rails_phase(
        self,
        *,
        frame: pd.DataFrame,
        timestamp: datetime,
        candidates: tuple[LineCandidate, ...],
        prior: _PriorStatePhase,
    ) -> _AssociationPhase:
        eligible_match_families = tuple(
            family
            for family in prior.previous_families
            if family.lifecycle_state is not FamilyLifecycleState.DORMANT
            or family.bars_since_match < self.config.lifecycle.expire_after_bars
        )
        atr = self._normalization_atr(frame, required=bool(candidates))
        if candidates and atr is None:
            raise TrendlineFamilyUpdateError(
                "normalization ATR is required for rail grouping"
            )
        grouping = (
            group_rail_candidates(
                candidates,
                timestamp=timestamp,
                atr=atr,
                config=self.config,
            )
            if candidates
            else RailGroupingResult(groups=(), rejected_pair_reason_codes=())
        )
        groups = grouping.groups
        dormant_ids = (
            set()
            if prior.previous_snapshot is None
            else {
                family.family_id
                for family in prior.previous_snapshot.dormant_families
            }
        )
        matches: tuple[FamilyRailGroupMatch, ...] = ()
        if groups and eligible_match_families:
            if atr is None:
                raise TrendlineFamilyUpdateError(
                    "normalization ATR is required for family matching"
                )
            matches = greedy_match_rail_groups(
                groups,
                eligible_match_families,
                timestamp=timestamp,
                atr=atr,
                config=self.config,
                dormant_family_ids=dormant_ids,
            )
        return _AssociationPhase(
            atr=atr,
            grouping=grouping,
            groups=groups,
            matches=matches,
        )

    def _advance_family_lifecycle_phase(
        self,
        *,
        timestamp: datetime,
        current_price: float,
        candidates: tuple[LineCandidate, ...],
        previous_families: tuple[TrendlineFamilyState, ...],
        association: _AssociationPhase,
        scheduled_role_reversals: frozenset[str],
        applied_role_reversals: frozenset[str],
    ) -> _LifecyclePhase:
        atr = association.atr
        match_by_family = {
            match.family_id: match for match in association.matches
        }
        group_by_id = {group.group_id: group for group in association.groups}
        matched_group_ids = {match.group_id for match in association.matches}
        drafts: list[_FamilyDraft] = []
        unmatched_active_count = 0
        for family in sorted(previous_families, key=lambda item: item.family_id):
            match = match_by_family.get(family.family_id)
            if match is not None:
                drafts.append(
                    self._matched_draft(
                        family,
                        group_by_id[match.group_id],
                        match,
                        timestamp=timestamp,
                        current_price=current_price,
                        atr=atr.value if atr is not None else None,
                    )
                )
                continue
            if family.lifecycle_state is FamilyLifecycleState.ACTIVE:
                unmatched_active_count += 1
            drafts.append(
                self._unmatched_draft(
                    family,
                    timestamp=timestamp,
                    current_price=current_price,
                    atr=atr.value if atr is not None else None,
                )
            )

        rejected_birth_ids: list[str] = []
        reversal_suppressed_candidate_ids = self._reversal_duplicate_candidate_ids(
            candidates,
            drafts,
            timestamp=timestamp,
            atr=atr,
            applied_role_reversals=applied_role_reversals,
        )
        for group in association.groups:
            if group.group_id in matched_group_ids:
                continue
            residual_candidates = tuple(
                candidate
                for candidate in group.candidates
                if candidate.candidate_id not in reversal_suppressed_candidate_ids
            )
            if not residual_candidates:
                continue
            birth_group = (
                group
                if len(residual_candidates) == len(group.candidates)
                else subset_rail_candidate_group(group, residual_candidates)
            )
            if (
                max(
                    candidate.diagnostics.normalized_quality
                    for candidate in birth_group.candidates
                )
                < self.config.candidate.birth_quality_threshold
            ):
                rejected_birth_ids.extend(birth_group.candidate_ids)
                continue
            drafts.append(
                self._birth_draft(
                    birth_group,
                    timestamp=timestamp,
                    current_price=current_price,
                    atr=atr.value if atr is not None else None,
                )
            )

        self._enforce_active_cap(
            drafts,
            timestamp=timestamp,
            current_price=current_price,
            atr=atr.value if atr is not None else None,
            rejected_birth_ids=rejected_birth_ids,
        )
        applied, deferred = self._settle_pending_role_reversal_drafts(
            drafts,
            scheduled_role_reversals=scheduled_role_reversals,
            applied_role_reversals=applied_role_reversals,
        )
        self._mark_role_reversal_drafts(
            drafts,
            applied_role_reversals=applied,
        )
        return _LifecyclePhase(
            drafts=tuple(drafts),
            rejected_birth_ids=tuple(rejected_birth_ids),
            unmatched_active_count=unmatched_active_count,
            applied_role_reversals=applied,
            deferred_role_reversals=deferred,
        )

    def _advance_interaction_phase(
        self,
        *,
        lifecycle: _LifecyclePhase,
        frame: pd.DataFrame,
        timestamp: datetime,
        tick_size: float | None,
        previous_events: tuple[FamilyInteractionEvent, ...],
        atr: NormalizationAtr | None,
    ) -> _InteractionPhase:
        drafts = list(lifecycle.drafts)
        interaction_atr, observations = self._apply_interactions(
            drafts,
            frame=frame,
            timestamp=timestamp,
            tick_size=tick_size,
        )
        active_families = tuple(
            sorted(
                (
                    draft.state
                    for draft in drafts
                    if draft.state is not None
                    and draft.state.lifecycle_state is FamilyLifecycleState.ACTIVE
                ),
                key=lambda family: family.family_id,
            )
        )
        dormant_families = tuple(
            sorted(
                (
                    draft.state
                    for draft in drafts
                    if draft.state is not None
                    and draft.state.lifecycle_state is FamilyLifecycleState.DORMANT
                ),
                key=lambda family: family.family_id,
            )
        )
        published_families = active_families + dormant_families
        if published_families and atr is None:
            raise TrendlineFamilyUpdateError(
                "normalization ATR is required for family corridors"
            )
        corridors = (
            build_family_corridors(
                published_families,
                timestamp=timestamp,
                normalization_atr=atr.value,
                config=self.config,
            )
            if published_families and atr is not None
            else ()
        )
        event_reset_family_ids = frozenset(
            draft.state.family_id
            for draft in drafts
            if draft.state is not None and draft.representative_changed
        )
        try:
            event_result = advance_interaction_events(
                previous_events=tuple(
                    event
                    for event in previous_events
                    if event.family_id not in event_reset_family_ids
                ),
                observations=observations,
                families=published_families,
                timestamp=timestamp,
                config=self.config,
                role_reversed_family_ids=lifecycle.applied_role_reversals,
                deferred_role_reversal_family_ids=(
                    lifecycle.deferred_role_reversals
                ),
            )
        except ContractValidationError as exc:
            raise TrendlineFamilyUpdateError(str(exc)) from exc
        return _InteractionPhase(
            interaction_atr=interaction_atr,
            observations=observations,
            active_families=active_families,
            dormant_families=dormant_families,
            corridors=corridors,
            event_result=event_result,
        )

    def _build_snapshot_phase(
        self,
        *,
        timestamp: datetime,
        prior: _PriorStatePhase,
        candidate_phase: _CandidatePhase,
        association: _AssociationPhase,
        lifecycle: _LifecyclePhase,
        interaction: _InteractionPhase,
    ) -> TrendlineFamilySnapshot:
        source_group_by_group_id = {
            draft.group.group_id: self._source_group_audit(draft.group)
            for draft in lifecycle.drafts
            if draft.group is not None
        }
        transitions = tuple(
            sorted(
                (
                    self._transition_from_draft(
                        draft,
                        timestamp=timestamp,
                        atr=association.atr,
                        source_group=(
                            None
                            if draft.group is None
                            else source_group_by_group_id[draft.group.group_id]
                        ),
                    )
                    for draft in lifecycle.drafts
                    if draft.state is not None
                    or draft.transition_type is FamilyTransitionType.EXPIRE
                ),
                key=lambda transition: transition.transition_id,
            )
        )
        transition_source_group_ids = {
            transition.source_group_id for transition in transitions
        }
        source_group_audits = tuple(
            sorted(
                (
                    audit
                    for audit in source_group_by_group_id.values()
                    if audit.source_group_id in transition_source_group_ids
                ),
                key=lambda audit: audit.source_group_id,
            )
        )
        diagnostics = self._snapshot_diagnostics(
            provider_result=candidate_phase.provider_result,
            candidates=candidate_phase.candidates,
            grouping=association.grouping,
            matches=association.matches,
            drafts=list(lifecycle.drafts),
            rejected_birth_ids=list(lifecycle.rejected_birth_ids),
            unmatched_active_count=lifecycle.unmatched_active_count,
            atr=association.atr,
            previous_family_count=len(prior.previous_families),
            active_families=interaction.active_families,
            dormant_families=interaction.dormant_families,
            corridors=interaction.corridors,
            interaction_atr=interaction.interaction_atr,
            observation_count=len(interaction.observations),
        )
        previous_snapshot_id = (
            None
            if prior.previous_snapshot is None
            else prior.previous_snapshot.snapshot_id
        )
        identity_fields = {
            "asset": self.config.asset,
            "timeframe": self.config.timeframe,
            "timestamp": timestamp,
            "previous_snapshot_id": previous_snapshot_id,
            "model_version": self.config.model_version,
            "config_version": self.config.config_version,
            "resolved_config_hash": self.config.resolved_config_hash,
            "active_families": interaction.active_families,
            "dormant_families": interaction.dormant_families,
            "transitions": transitions,
            "source_group_audits": source_group_audits,
            "corridors": interaction.corridors,
            "observations": interaction.observations,
            "interaction_events": interaction.event_result.events,
            "interaction_event_transitions": interaction.event_result.transitions,
            "diagnostics": diagnostics,
        }
        return TrendlineFamilySnapshot(
            snapshot_id=compute_trendline_family_snapshot_id(**identity_fields),
            **identity_fields,
        )

    def _persist_snapshot_phase(self, snapshot: TrendlineFamilySnapshot) -> None:
        self.repository.save_snapshot(snapshot)

    def _build_output_phase(
        self,
        snapshot: TrendlineFamilySnapshot,
        *,
        current_price: float,
        atr: NormalizationAtr | None,
    ) -> TrendlineFamilyOutput:
        return self._output(
            snapshot,
            current_price=current_price,
            atr=None if atr is None else atr.value,
        )

    def _prepare_confirmed_frame(
        self,
        ohlcv: pd.DataFrame,
        *,
        observed_at: datetime | None,
    ) -> tuple[datetime, pd.DataFrame]:
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
            raise TrendlineFamilyUpdateError("tracker requires a non-empty OHLCV DataFrame")
        if observed_at is None:
            if not isinstance(ohlcv.index, pd.DatetimeIndex):
                raise TrendlineFamilyUpdateError("OHLCV must use a DatetimeIndex")
            observed = require_utc(ohlcv.index[-1].to_pydatetime(), field_name="observed_at")
        else:
            observed = require_utc(observed_at, field_name="observed_at")
        try:
            frame = confirmed_ohlcv_window(
                ohlcv,
                observed_at=observed,
                required_columns=frozenset({"open", "high", "low", "close"}),
            )
        except ContractValidationError as exc:
            raise TrendlineFamilyUpdateError(str(exc)) from exc
        if frame.empty or require_utc(frame.index[-1].to_pydatetime()) != observed:
            raise TrendlineFamilyUpdateError("observed_at must identify the latest confirmed OHLCV bar")
        return observed, frame

    def _apply_pending_role_reversals(
        self,
        families: tuple[TrendlineFamilyState, ...],
        *,
        scheduled_role_reversals: frozenset[str],
    ) -> tuple[tuple[TrendlineFamilyState, ...], frozenset[str]]:
        """Apply only prior active scheduling intents before matching new lines."""

        transformed: list[TrendlineFamilyState] = []
        applied: set[str] = set()
        for family in sorted(families, key=lambda item: item.family_id):
            if family.family_id not in scheduled_role_reversals:
                transformed.append(family)
                continue
            if family.lifecycle_state is FamilyLifecycleState.DORMANT:
                # A dormant snapshot freezes event state; it cannot apply a
                # reversal until a later active lifecycle update.
                transformed.append(family)
                continue
            reversed_role = opposite_role(family.current_role)
            transformed.append(
                replace(
                    family,
                    current_role=reversed_role,
                    members=tuple(
                        replace(member, role=reversed_role)
                        for member in family.members
                    ),
                )
            )
            applied.add(family.family_id)
        return tuple(transformed), frozenset(applied)

    @staticmethod
    def _mark_role_reversal_drafts(
        drafts: list[_FamilyDraft],
        *,
        applied_role_reversals: frozenset[str],
    ) -> None:
        """Keep the one-version family audit transition explicit at reversal."""

        for draft in drafts:
            if draft.previous is None or draft.previous.family_id not in applied_role_reversals:
                continue
            if draft.state is None:
                raise TrendlineFamilyUpdateError("scheduled role reversal cannot expire before persistence")
            draft.transition_type = FamilyTransitionType.ROLE_REVERSED
            draft.reason_codes = ("event_pending_role_reversal",)

    def _settle_pending_role_reversal_drafts(
        self,
        drafts: list[_FamilyDraft],
        *,
        scheduled_role_reversals: frozenset[str],
        applied_role_reversals: frozenset[str],
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Publish only active reversals and freeze their exact prior geometry.

        The matching pass intentionally sees a temporary reversed role.  On
        the reversal snapshot its candidate can prove continuity, but cannot
        refit the exact representative or anchors.  Dormant and reactivated
        pending events defer the intent to their next active update.
        """

        applied = set(applied_role_reversals)
        deferred = set(scheduled_role_reversals - applied)
        for draft in drafts:
            if draft.previous is None or draft.previous.family_id not in applied_role_reversals:
                continue
            family_id = draft.previous.family_id
            if draft.state is None:
                applied.discard(family_id)
                deferred.discard(family_id)
                continue
            if draft.state.lifecycle_state is FamilyLifecycleState.DORMANT:
                old_role = opposite_role(draft.previous.current_role)
                draft.state = replace(
                    draft.state,
                    current_role=old_role,
                    representative=draft.previous.representative,
                    representative_member_id=draft.previous.representative_member_id,
                    members=tuple(
                        replace(member, role=old_role)
                        for member in draft.previous.members
                    ),
                )
                applied.discard(family_id)
                deferred.add(family_id)
                continue
            # Reversal geometry is frozen for this one snapshot.  Member
            # last_seen_at is deliberately retained: the match is continuity
            # evidence, not a new exact-line observation.
            draft.state = replace(
                draft.state,
                representative=draft.previous.representative,
                representative_member_id=draft.previous.representative_member_id,
                members=tuple(
                    replace(member, role=draft.state.current_role)
                    for member in draft.previous.members
                ),
            )
            deferred.discard(family_id)
        for draft in drafts:
            if draft.previous is None:
                continue
            final_representative_changed = bool(
                draft.state is not None
                and draft.previous.representative_member_id
                != draft.state.representative_member_id
            )
            draft.representative_changed = final_representative_changed
            reasons = tuple(
                reason
                for reason in draft.reason_codes
                if reason != "representative_changed"
            )
            if final_representative_changed:
                reasons += ("representative_changed",)
            draft.reason_codes = reasons
        return frozenset(applied), frozenset(deferred)

    def _reversal_duplicate_candidate_ids(
        self,
        candidates: tuple[LineCandidate, ...],
        drafts: list[_FamilyDraft],
        *,
        timestamp: datetime,
        atr: NormalizationAtr | None,
        applied_role_reversals: frozenset[str],
    ) -> frozenset[str]:
        """Avoid birthing the old-role rendering of a line being reversed.

        Candidate matching intentionally sees the new role.  A provider can
        still emit the old-role candidate on that same bar, so suppress only a
        geometry-equivalent contender rather than creating a duplicate lineage.
        """

        if atr is None or not applied_role_reversals:
            return frozenset()
        reversed_drafts = [
            draft
            for draft in drafts
            if draft.previous is not None
            and draft.previous.family_id in applied_role_reversals
            and draft.state is not None
        ]
        suppressed: set[str] = set()
        for candidate in candidates:
            for draft in reversed_drafts:
                previous = draft.previous
                if previous is None:
                    continue
                old_role = opposite_role(previous.current_role)
                if candidate.role is not old_role:
                    continue
                if any(
                    score_member_candidate(
                        replace(member, role=old_role),
                        candidate,
                        timestamp=timestamp,
                        atr=atr,
                        config=self.config,
                    )
                    is not None
                    for member in previous.members
                ):
                    suppressed.add(candidate.candidate_id)
                    break
        return frozenset(suppressed)

    def _normalization_atr(self, frame: pd.DataFrame, *, required: bool) -> NormalizationAtr | None:
        try:
            return calculate_normalization_atr(
                frame,
                window=self.config.matching.normalization_atr_window,
            )
        except ContractValidationError as exc:
            if required:
                raise TrendlineFamilyUpdateError(str(exc)) from exc
            return None

    def _apply_interactions(
        self,
        drafts: list[_FamilyDraft],
        *,
        frame: pd.DataFrame,
        timestamp: datetime,
        tick_size: float | None,
    ) -> tuple[InteractionAtr | None, tuple[FamilyInteractionObservation, ...]]:
        published_drafts = [draft for draft in drafts if draft.state is not None]
        if not published_drafts:
            return None, ()
        try:
            interaction_atr = calculate_interaction_atr(
                frame,
                window=self.config.interaction.atr_window,
            )
        except ContractValidationError as exc:
            raise TrendlineFamilyUpdateError(str(exc)) from exc
        candle = frame.iloc[-1]
        observations: list[FamilyInteractionObservation] = []
        for draft in sorted(published_drafts, key=lambda item: item.state.family_id):
            state = draft.state
            if state is None:  # Defensive narrowing after the published-draft filter.
                continue
            try:
                evaluation = evaluate_family_interaction(
                    state,
                    timestamp=timestamp,
                    open_price=float(candle["open"]),
                    high_price=float(candle["high"]),
                    low_price=float(candle["low"]),
                    close_price=float(candle["close"]),
                    interaction_atr=interaction_atr,
                    config=self.config,
                    tick_size=tick_size,
                )
            except ContractValidationError as exc:
                raise TrendlineFamilyUpdateError(str(exc)) from exc
            draft.state = replace(
                state,
                bars_since_touch=evaluation.bars_since_touch,
                breach_count=state.breach_count + evaluation.breach_increment,
            )
            observations.append(evaluation.observation)
        return interaction_atr, tuple(observations)

    def _validate_candidates(self, candidates: tuple[LineCandidate, ...], *, timestamp: datetime) -> None:
        for candidate in candidates:
            if (
                candidate.asset != self.config.asset
                or candidate.timeframe != self.config.timeframe
                or candidate.observed_at != timestamp
            ):
                raise TrendlineFamilyUpdateError("candidate identity does not match tracker request")
            if (
                candidate.metadata.get("model_version") != self.config.model_version
                or candidate.metadata.get("config_version") != self.config.config_version
                or candidate.metadata.get("resolved_config_hash") != self.config.resolved_config_hash
            ):
                raise TrendlineFamilyUpdateError("candidate config identity does not match tracker request")

    def _assert_repository_head_compatible(self, snapshot: TrendlineFamilySnapshot) -> None:
        expected = {
            "asset": self.config.asset,
            "timeframe": self.config.timeframe,
            "model_version": self.config.model_version,
            "config_version": self.config.config_version,
            "resolved_config_hash": self.config.resolved_config_hash,
        }
        mismatches = tuple(
            field_name
            for field_name, expected_value in expected.items()
            if getattr(snapshot, field_name) != expected_value
        )
        if mismatches:
            raise TrendlineFamilyUpdateError(
                f"repository head identity mismatch: {', '.join(mismatches)}"
            )

    def _birth_draft(
        self,
        group: RailCandidateGroup,
        *,
        timestamp: datetime,
        current_price: float,
        atr: float | None,
    ) -> _FamilyDraft:
        family_id = deterministic_id(
            "family",
            {
                "asset": self.config.asset,
                "timeframe": self.config.timeframe,
                "birth_timestamp": timestamp.isoformat(),
                "group_id": group.group_id,
                "candidate_ids": group.candidate_ids,
            },
        )
        members = tuple(
            sorted(
                (
                    self._member_from_candidate(
                        candidate,
                        member_id=deterministic_id(
                            "family-member",
                            {
                                "family_id": family_id,
                                "candidate_id": candidate.candidate_id,
                                "geometry": candidate.geometry.to_dict(),
                            },
                        ),
                        first_seen_at=timestamp,
                        last_seen_at=timestamp,
                    )
                    for candidate in group.candidates
                ),
                key=lambda member: member.member_id,
            )
        )
        state = self._state_from_members(
            family_id=family_id,
            members=members,
            previous_representative_member_id=None,
            created_at=timestamp,
            last_confirmed_at=timestamp,
            updated_at=timestamp,
            age_bars=1,
            lifecycle_state=FamilyLifecycleState.ACTIVE,
            confidence=max(
                candidate.diagnostics.normalized_quality
                for candidate in group.candidates
            ),
            bars_since_match=0,
            bars_since_touch=0,
            breach_count=0,
            version=1,
            uncertainty=LineUncertainty(),
            current_price=current_price,
            atr=atr,
        )
        return _FamilyDraft(
            previous=None,
            state=state,
            transition_type=FamilyTransitionType.BIRTH,
            candidate=self._group_candidate(group),
            association=None,
            reason_codes=("birth_quality_passed",),
            is_birth=True,
            group=group,
        )

    def _matched_draft(
        self,
        family: TrendlineFamilyState,
        group: RailCandidateGroup,
        association: FamilyRailGroupMatch,
        *,
        timestamp: datetime,
        current_price: float,
        atr: float | None,
    ) -> _FamilyDraft:
        if atr is None:
            raise TrendlineFamilyUpdateError("normalization ATR is required for rail continuation")
        member_matches = match_group_members(
            family,
            group,
            timestamp=timestamp,
            atr=NormalizationAtr(
                value=atr,
                method="tracker_normalization_atr",
                sample_count=1,
            ),
            config=self.config,
        )
        matched_candidate_by_member = {
            match.member_id: match.candidate_id for match in member_matches
        }
        candidate_by_id = {candidate.candidate_id: candidate for candidate in group.candidates}
        old_member_by_id = {member.member_id: member for member in family.members}
        members: list[FamilyMember] = []
        matched_candidate_ids = set(matched_candidate_by_member.values())
        for member_id, candidate_id in sorted(matched_candidate_by_member.items()):
            prior = old_member_by_id[member_id]
            members.append(
                self._member_from_candidate(
                    candidate_by_id[candidate_id],
                    member_id=prior.member_id,
                    first_seen_at=prior.first_seen_at,
                    last_seen_at=timestamp,
                )
            )
        for candidate in group.candidates:
            if candidate.candidate_id in matched_candidate_ids:
                continue
            members.append(
                self._member_from_candidate(
                    candidate,
                    member_id=deterministic_id(
                        "family-member",
                        {
                            "family_id": family.family_id,
                            "candidate_id": candidate.candidate_id,
                            "first_seen_at": timestamp,
                            "geometry": candidate.geometry.to_dict(),
                        },
                    ),
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                )
            )
        canonical_members = tuple(sorted(members, key=lambda member: member.member_id))
        if not canonical_members:
            raise TrendlineFamilyUpdateError("matched rail group must produce at least one member")
        confidence = max(member.diagnostics.normalized_quality for member in canonical_members)
        transition_type = (
            FamilyTransitionType.REACTIVATE
            if family.lifecycle_state is FamilyLifecycleState.DORMANT
            else FamilyTransitionType.STRENGTHEN
            if confidence > family.confidence
            else FamilyTransitionType.WEAKEN
            if confidence < family.confidence
            else FamilyTransitionType.CONTINUE
        )
        state = self._state_from_members(
            family_id=family.family_id,
            members=canonical_members,
            previous_representative_member_id=family.representative_member_id,
            created_at=family.created_at,
            last_confirmed_at=timestamp,
            updated_at=timestamp,
            age_bars=family.age_bars + 1,
            lifecycle_state=FamilyLifecycleState.ACTIVE,
            confidence=confidence,
            bars_since_match=0,
            bars_since_touch=family.bars_since_touch,
            breach_count=family.breach_count,
            version=family.version + 1,
            uncertainty=replace(family.uncertainty, projection_horizon_bars=0),
            current_price=current_price,
            atr=atr,
        )
        return _FamilyDraft(
            previous=family,
            state=state,
            transition_type=transition_type,
            candidate=candidate_by_id[association.representative_candidate_id],
            association=association,
            reason_codes=(
                "matched",
                *(
                    ("representative_changed",)
                    if state.representative_member_id != family.representative_member_id
                    else ()
                ),
            ),
            group=group,
            member_matches=member_matches,
            representative_changed=(
                state.representative_member_id != family.representative_member_id
            ),
        )

    def _unmatched_draft(
        self,
        family: TrendlineFamilyState,
        *,
        timestamp: datetime,
        current_price: float,
        atr: float | None,
    ) -> _FamilyDraft:
        bars_since_match = family.bars_since_match + 1
        lifecycle = family.lifecycle_state
        transition_type = FamilyTransitionType.WEAKEN
        confidence = family.confidence
        if lifecycle is FamilyLifecycleState.ACTIVE:
            if bars_since_match <= self.config.lifecycle.active_grace_bars:
                lifecycle = FamilyLifecycleState.ACTIVE
            elif bars_since_match < self.config.lifecycle.dormant_after_bars:
                confidence = self._decayed_confidence(confidence)
            elif bars_since_match == self.config.lifecycle.dormant_after_bars:
                confidence = self._decayed_confidence(confidence)
                lifecycle = FamilyLifecycleState.DORMANT
                transition_type = FamilyTransitionType.DORMANT
            else:
                confidence = self._decayed_confidence(confidence)
                lifecycle = FamilyLifecycleState.DORMANT
                transition_type = FamilyTransitionType.DORMANT
        elif bars_since_match >= self.config.lifecycle.expire_after_bars:
            return _FamilyDraft(
                previous=family,
                state=None,
                transition_type=FamilyTransitionType.EXPIRE,
                candidate=None,
                association=None,
                reason_codes=("expiry_horizon_reached",),
            )
        else:
            confidence = self._decayed_confidence(confidence)

        state = self._state_from_members(
            family_id=family.family_id,
            members=family.members,
            previous_representative_member_id=family.representative_member_id,
            created_at=family.created_at,
            last_confirmed_at=family.last_confirmed_at,
            updated_at=timestamp,
            age_bars=family.age_bars + 1,
            lifecycle_state=lifecycle,
            confidence=confidence,
            bars_since_match=bars_since_match,
            bars_since_touch=family.bars_since_touch,
            breach_count=family.breach_count,
            version=family.version + 1,
            uncertainty=replace(
                family.uncertainty,
                projection_horizon_bars=family.uncertainty.projection_horizon_bars + 1,
            ),
            current_price=current_price,
            atr=atr,
        )
        return _FamilyDraft(
            previous=family,
            state=state,
            transition_type=transition_type,
            candidate=None,
            association=None,
            reason_codes=("unmatched",),
        )

    def _enforce_active_cap(
        self,
        drafts: list[_FamilyDraft],
        *,
        timestamp: datetime,
        current_price: float,
        atr: float | None,
        rejected_birth_ids: list[str],
    ) -> None:
        for role in (FamilyRole.SUPPORT, FamilyRole.RESISTANCE):
            active = [
                draft
                for draft in drafts
                if draft.state is not None
                and draft.state.lifecycle_state is FamilyLifecycleState.ACTIVE
                and draft.state.current_role is role
            ]
            active.sort(
                key=lambda draft: (
                    -draft.state.structural_importance,
                    -draft.state.current_relevance,
                    draft.state.family_id,
                )
            )
            for draft in active[self.config.lifecycle.max_active_families_per_role :]:
                if draft.is_birth:
                    if draft.candidate is not None:
                        rejected_birth_ids.append(draft.candidate.candidate_id)
                    draft.state = None
                    continue
                state = draft.state
                if state is None:
                    continue
                draft.state = self._state_from_members(
                    family_id=state.family_id,
                    members=state.members,
                    previous_representative_member_id=state.representative_member_id,
                    created_at=state.created_at,
                    last_confirmed_at=state.last_confirmed_at,
                    updated_at=timestamp,
                    age_bars=state.age_bars,
                    lifecycle_state=FamilyLifecycleState.DORMANT,
                    confidence=state.confidence,
                    bars_since_match=state.bars_since_match,
                    bars_since_touch=state.bars_since_touch,
                    breach_count=state.breach_count,
                    version=state.version,
                    uncertainty=state.uncertainty,
                    current_price=current_price,
                    atr=atr,
                )
                draft.transition_type = FamilyTransitionType.DORMANT
                draft.reason_codes = ("active_family_cap",)

    def _member_from_candidate(
        self,
        candidate: LineCandidate,
        *,
        member_id: str,
        first_seen_at: datetime,
        last_seen_at: datetime,
    ) -> FamilyMember:
        return FamilyMember(
            member_id=member_id,
            candidate_id=candidate.candidate_id,
            geometry=candidate.geometry,
            role=candidate.role,
            diagnostics=candidate.diagnostics,
            anchors=candidate.anchors,
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
        )

    @staticmethod
    def _group_candidate(group: RailCandidateGroup) -> LineCandidate:
        """Choose a stable audit candidate without changing representative policy."""

        return min(
            group.candidates,
            key=lambda candidate: (
                -candidate.diagnostics.normalized_quality,
                candidate.candidate_id,
            ),
        )

    def _state_from_members(
        self,
        *,
        family_id: str,
        members: tuple[FamilyMember, ...],
        previous_representative_member_id: str | None,
        created_at: datetime,
        last_confirmed_at: datetime,
        updated_at: datetime,
        age_bars: int,
        lifecycle_state: FamilyLifecycleState,
        confidence: float,
        bars_since_match: int,
        bars_since_touch: int,
        breach_count: int,
        version: int,
        uncertainty: LineUncertainty,
        current_price: float,
        atr: float | None,
    ) -> TrendlineFamilyState:
        confidence = min(max(float(confidence), 0.0), 1.0)
        canonical_members = tuple(sorted(members, key=lambda member: member.member_id))
        representative_member = select_representative_member(
            canonical_members,
            timestamp=updated_at,
            atr=atr,
            previous_representative_member_id=previous_representative_member_id,
        )
        provisional = TrendlineFamilyState(
            family_id=family_id,
            asset=self.config.asset,
            timeframe=self.config.timeframe,
            created_at=created_at,
            updated_at=updated_at,
            last_confirmed_at=last_confirmed_at,
            age_bars=age_bars,
            representative=representative_member.geometry,
            representative_member_id=representative_member.member_id,
            members=canonical_members,
            current_role=representative_member.role,
            lifecycle_state=lifecycle_state,
            confidence=confidence,
            structural_importance=confidence,
            current_relevance=0.0,
            touch_count=representative_member.diagnostics.touch_count,
            effective_touch_count=representative_member.diagnostics.effective_touch_count,
            breach_count=breach_count,
            bars_since_touch=bars_since_touch,
            bars_since_match=bars_since_match,
            uncertainty=uncertainty,
            version=version,
        )
        relevance, _ = calculate_current_relevance(
            provisional,
            timestamp=updated_at,
            current_price=current_price,
            atr=atr,
        )
        return TrendlineFamilyState(
            family_id=provisional.family_id,
            asset=provisional.asset,
            timeframe=provisional.timeframe,
            created_at=provisional.created_at,
            updated_at=provisional.updated_at,
            last_confirmed_at=provisional.last_confirmed_at,
            age_bars=provisional.age_bars,
            representative=provisional.representative,
            representative_member_id=provisional.representative_member_id,
            members=provisional.members,
            current_role=provisional.current_role,
            lifecycle_state=provisional.lifecycle_state,
            confidence=provisional.confidence,
            structural_importance=provisional.confidence,
            current_relevance=relevance,
            touch_count=provisional.touch_count,
            effective_touch_count=provisional.effective_touch_count,
            breach_count=provisional.breach_count,
            bars_since_touch=provisional.bars_since_touch,
            bars_since_match=provisional.bars_since_match,
            uncertainty=provisional.uncertainty,
            version=provisional.version,
        )

    def _transition_from_draft(
        self,
        draft: _FamilyDraft,
        *,
        timestamp: datetime,
        atr: NormalizationAtr | None,
        source_group: FamilySourceGroupAudit | None,
    ) -> FamilyTransition:
        if draft.previous is None and draft.state is None:
            raise TrendlineFamilyUpdateError("suppressed birth cannot emit a transition")
        family_id = draft.previous.family_id if draft.previous is not None else draft.state.family_id
        previous_version = None if draft.previous is None else draft.previous.version
        new_version = draft.state.version if draft.state is not None else draft.previous.version + 1
        if (draft.group is None) is not (source_group is None):
            raise TrendlineFamilyUpdateError("transition source group audit must match draft group")
        source_group_candidate_ids = (
            () if source_group is None else source_group.candidate_ids
        )
        previous_member_ids = (
            frozenset() if draft.previous is None else frozenset(
                member.member_id for member in draft.previous.members
            )
        )
        current_member_ids = (
            frozenset() if draft.state is None else frozenset(
                member.member_id for member in draft.state.members
            )
        )
        current_candidate_ids = (
            ()
            if draft.state is None
            else tuple(sorted(member.candidate_id for member in draft.state.members))
        )
        matched_candidate_ids = (
            current_candidate_ids
            if draft.transition_type is FamilyTransitionType.ROLE_REVERSED
            or draft.association is not None
            or draft.is_birth
            else ()
        )
        metrics = {
            "confidence": 0.0 if draft.state is None else draft.state.confidence,
            "association_score": 0.0 if draft.association is None else draft.association.score,
            "normalization_atr": 0.0 if atr is None else atr.value,
            "previous_rail_count": float(len(previous_member_ids)),
            "current_rail_count": float(len(current_member_ids)),
        }
        transition_payload = {
            "family_id": family_id,
            "timestamp": timestamp,
            "transition_type": draft.transition_type,
            "previous_version": previous_version,
            "new_version": new_version,
            "matched_candidate_ids": matched_candidate_ids,
            "association_score": None if draft.association is None else draft.association.score,
            "reason_codes": draft.reason_codes,
            "metrics": metrics,
            "model_version": self.config.model_version,
            "config_version": self.config.config_version,
            "resolved_config_hash": self.config.resolved_config_hash,
            "added_member_ids": tuple(sorted(current_member_ids - previous_member_ids)),
            "continued_member_ids": tuple(sorted(current_member_ids & previous_member_ids)),
            "removed_member_ids": tuple(sorted(previous_member_ids - current_member_ids)),
            "previous_representative_member_id": (
                None if draft.previous is None else draft.previous.representative_member_id
            ),
            "current_representative_member_id": (
                None if draft.state is None else draft.state.representative_member_id
            ),
            "representative_changed": draft.representative_changed,
            "previous_rail_count": len(previous_member_ids),
            "current_rail_count": len(current_member_ids),
            "source_group_id": None if source_group is None else source_group.source_group_id,
            "source_group_candidate_ids": source_group_candidate_ids,
        }
        transition_id = deterministic_id(
            "family-transition",
            {
                "transition": transition_payload,
                "resulting_family_state": None if draft.state is None else draft.state.to_dict(),
            },
        )
        return FamilyTransition(
            transition_id=transition_id,
            **transition_payload,
        )

    def _source_group_audit(self, group: RailCandidateGroup) -> FamilySourceGroupAudit:
        candidate_ids = group.candidate_ids
        candidate_content_hashes = tuple(
            deterministic_hash(candidate.to_dict()) for candidate in group.candidates
        )
        identity_payload = {
            "asset": group.asset,
            "timeframe": group.timeframe,
            "role": group.role.value,
            "observed_at": group.observed_at,
            "candidate_ids": candidate_ids,
            "candidate_content_hashes": candidate_content_hashes,
            "model_version": self.config.model_version,
            "config_version": self.config.config_version,
            "resolved_config_hash": self.config.resolved_config_hash,
        }
        return FamilySourceGroupAudit(
            source_group_id=deterministic_id("family-source-group-audit", identity_payload),
            asset=group.asset,
            timeframe=group.timeframe,
            role=group.role,
            observed_at=group.observed_at,
            candidate_ids=candidate_ids,
            candidates=group.candidates,
            candidate_content_hashes=candidate_content_hashes,
            model_version=self.config.model_version,
            config_version=self.config.config_version,
            resolved_config_hash=self.config.resolved_config_hash,
        )

    def _snapshot_diagnostics(
        self,
        *,
        provider_result: CandidateGenerationResult,
        candidates: tuple[LineCandidate, ...],
        grouping: RailGroupingResult,
        matches: tuple[FamilyRailGroupMatch, ...],
        drafts: list[_FamilyDraft],
        rejected_birth_ids: list[str],
        unmatched_active_count: int,
        atr: NormalizationAtr | None,
        previous_family_count: int,
        active_families: tuple[TrendlineFamilyState, ...],
        dormant_families: tuple[TrendlineFamilyState, ...],
        corridors: tuple[Any, ...],
        interaction_atr: InteractionAtr | None = None,
        observation_count: int = 0,
    ) -> Mapping[str, Any]:
        births = sum(1 for draft in drafts if draft.is_birth and draft.state is not None)
        reactivated = sum(1 for draft in drafts if draft.transition_type is FamilyTransitionType.REACTIVATE)
        expired = sum(1 for draft in drafts if draft.transition_type is FamilyTransitionType.EXPIRE)
        dormant = sum(1 for draft in drafts if draft.transition_type is FamilyTransitionType.DORMANT)
        churn_count = births + reactivated + expired + dormant
        churn_denominator = max(previous_family_count + births, 1)
        return {
            "generated_candidate_count": len(candidates),
            "rail_grouping_enabled": True,
            "rail_group_count": len(grouping.groups),
            "rail_grouping_rejection_reasons": grouping.rejected_pair_reason_codes,
            "matched_count": len(matches),
            "birth_count": births,
            "rejected_birth_count": len(rejected_birth_ids),
            "rejected_birth_candidate_ids": tuple(sorted(rejected_birth_ids)),
            "unmatched_active_count": unmatched_active_count,
            "dormant_count": len(dormant_families),
            "reactivated_count": reactivated,
            "expired_count": expired,
            "active_family_count_by_role": {
                FamilyRole.SUPPORT.value: sum(
                    family.current_role is FamilyRole.SUPPORT for family in active_families
                ),
                FamilyRole.RESISTANCE.value: sum(
                    family.current_role is FamilyRole.RESISTANCE for family in active_families
                ),
            },
            "family_churn_count": churn_count,
            "family_churn_rate": churn_count / churn_denominator,
            "provider_status": provider_result.status.value,
            "provider_reason_codes": provider_result.reason_codes,
            "normalization_atr": None if atr is None else atr.value,
            "normalization_atr_method": None if atr is None else atr.method,
            "normalization_atr_sample_count": None if atr is None else atr.sample_count,
            "interaction_atr": None if interaction_atr is None else interaction_atr.value,
            "interaction_atr_method": None if interaction_atr is None else interaction_atr.method,
            "interaction_atr_sample_count": None if interaction_atr is None else interaction_atr.sample_count,
            "interaction_observation_count": observation_count,
            "family_corridor_count": len(corridors),
            "singleton_family_count": sum(corridor.rail_count == 1 for corridor in corridors),
            "multi_rail_family_count": sum(corridor.rail_count > 1 for corridor in corridors),
            "total_rail_count": sum(corridor.rail_count for corridor in corridors),
            "representative_change_count": sum(
                draft.representative_changed for draft in drafts
            ),
        }

    def _output(
        self,
        snapshot: TrendlineFamilySnapshot,
        *,
        current_price: float,
        atr: float | None,
    ) -> TrendlineFamilyOutput:
        ranks = rank_families(
            snapshot.active_families,
            timestamp=snapshot.timestamp,
            current_price=current_price,
            atr=atr,
        )
        nearest_support = nearest_role_id(ranks, FamilyRole.SUPPORT)
        nearest_resistance = nearest_role_id(ranks, FamilyRole.RESISTANCE)
        return TrendlineFamilyOutput(
            snapshot=snapshot,
            ranked_support_families=ranked_role_ids(ranks, FamilyRole.SUPPORT),
            ranked_resistance_families=ranked_role_ids(ranks, FamilyRole.RESISTANCE),
            nearest_support_family_id=nearest_support,
            nearest_resistance_family_id=nearest_resistance,
            features={
                "trendline_family_valid": True,
                "provider_status": snapshot.diagnostics["provider_status"],
                "normalization_atr": snapshot.diagnostics["normalization_atr"],
                "interaction_atr": snapshot.diagnostics["interaction_atr"],
                **build_interaction_features(
                    snapshot,
                    nearest_support_family_id=nearest_support,
                    nearest_resistance_family_id=nearest_resistance,
                    current_price=current_price,
                ),
            },
        )

    def _decayed_confidence(self, confidence: float) -> float:
        return min(max(confidence - self.config.lifecycle.confidence_decay_per_unmatched_bar, 0.0), 1.0)
