"""Immutable single-timeframe snapshots, outputs, and aggregate identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Mapping

from .enums import FamilyLifecycleState, FamilyTransitionType, InteractionEventState
from .events import FamilyInteractionEvent, FamilyInteractionEventTransition, FamilyTransition
from .families import FamilyCorridor, FamilySourceGroupAudit, TrendlineFamilyState
from .identity import deterministic_id
from .interactions import FamilyInteractionObservation
from .validation import (
    ContractValidationError,
    _PHASE_G_DIAGNOSTIC_KEYS,
    _decode,
    _freeze_mapping,
    _hash,
    _integer,
    _interaction_close,
    _mapping,
    _number,
    _optional_string,
    _primitive,
    _required,
    _string,
    _tuple_of_strings,
    parse_utc_isoformat,
    require_utc,
)

@dataclass(frozen=True)
class TrendlineFamilySnapshot:
    snapshot_id: str
    asset: str
    timeframe: str
    timestamp: datetime
    previous_snapshot_id: str | None
    model_version: str
    config_version: str
    resolved_config_hash: str
    active_families: tuple[TrendlineFamilyState, ...]
    dormant_families: tuple[TrendlineFamilyState, ...]
    transitions: tuple[FamilyTransition, ...]
    source_group_audits: tuple[FamilySourceGroupAudit, ...] = ()
    corridors: tuple[FamilyCorridor, ...] = ()
    observations: tuple[FamilyInteractionObservation, ...] = ()
    interaction_events: tuple[FamilyInteractionEvent, ...] = ()
    interaction_event_transitions: tuple[FamilyInteractionEventTransition, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "asset", "timeframe", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "previous_snapshot_id", _optional_string(self.previous_snapshot_id, field_name="previous_snapshot_id"))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        active_families, dormant_families, transitions = tuple(self.active_families), tuple(self.dormant_families), tuple(self.transitions)
        source_group_audits = tuple(self.source_group_audits)
        corridors = tuple(self.corridors)
        observations = tuple(self.observations)
        interaction_events = tuple(self.interaction_events)
        interaction_event_transitions = tuple(self.interaction_event_transitions)
        if any(not isinstance(family, TrendlineFamilyState) for family in active_families + dormant_families):
            raise ContractValidationError("snapshot families must use TrendlineFamilyState")
        if any(family.lifecycle_state is not FamilyLifecycleState.ACTIVE for family in active_families):
            raise ContractValidationError("active snapshot bucket may contain only ACTIVE families")
        if any(family.lifecycle_state is not FamilyLifecycleState.DORMANT for family in dormant_families):
            raise ContractValidationError("dormant snapshot bucket may contain only DORMANT families")
        if any(family.updated_at > self.timestamp or family.last_confirmed_at > self.timestamp for family in active_families + dormant_families):
            raise ContractValidationError("family timestamps cannot exceed snapshot timestamp")
        family_ids = [family.family_id for family in active_families + dormant_families]
        if len(family_ids) != len(set(family_ids)):
            raise ContractValidationError("a snapshot cannot contain duplicate family IDs")
        if any(family.asset != self.asset or family.timeframe != self.timeframe for family in active_families + dormant_families):
            raise ContractValidationError("snapshot family asset/timeframe mismatch")
        if any(not isinstance(transition, FamilyTransition) for transition in transitions):
            raise ContractValidationError("snapshot transitions must use FamilyTransition")
        if len({transition.transition_id for transition in transitions}) != len(transitions):
            raise ContractValidationError("snapshot transition IDs must be unique")
        if any(transition.timestamp > self.timestamp for transition in transitions):
            raise ContractValidationError("transition timestamp cannot exceed snapshot timestamp")
        if any(transition.model_version != self.model_version or transition.config_version != self.config_version or transition.resolved_config_hash != self.resolved_config_hash for transition in transitions):
            raise ContractValidationError("transition metadata must match the containing snapshot")
        present_families = {family.family_id: family for family in active_families + dormant_families}
        if any(not isinstance(audit, FamilySourceGroupAudit) for audit in source_group_audits):
            raise ContractValidationError("snapshot source_group_audits must use FamilySourceGroupAudit")
        if len({audit.source_group_id for audit in source_group_audits}) != len(source_group_audits):
            raise ContractValidationError("snapshot source group audit IDs must be unique")
        if source_group_audits and tuple(
            sorted(source_group_audits, key=lambda item: item.source_group_id)
        ) != source_group_audits:
            raise ContractValidationError("snapshot source group audits must have deterministic ordering")
        for transition in transitions:
            family = present_families.get(transition.family_id)
            if transition.transition_type is FamilyTransitionType.EXPIRE:
                if (
                    transition.current_rail_count != 0
                    or transition.current_representative_member_id is not None
                    or transition.added_member_ids
                    or transition.continued_member_ids
                ):
                    raise ContractValidationError("EXPIRE transition cannot retain current rail evidence")
                continue
            if family is None:
                raise ContractValidationError("non-EXPIRE transition must reference a published family")
            if transition.new_version != family.version:
                raise ContractValidationError("transition new_version must match its published family version")
        if any(not isinstance(corridor, FamilyCorridor) for corridor in corridors):
            raise ContractValidationError("snapshot corridors must use FamilyCorridor")
        if len({corridor.corridor_id for corridor in corridors}) != len(corridors):
            raise ContractValidationError("snapshot corridor IDs must be unique")
        if len({corridor.family_id for corridor in corridors}) != len(corridors):
            raise ContractValidationError("snapshot must contain one corridor per family")
        if corridors and tuple(sorted(corridors, key=lambda item: (item.family_id, item.corridor_id))) != corridors:
            raise ContractValidationError("snapshot corridors must have deterministic family ordering")
        phase_g_marker = _mapping(self.diagnostics, field_name="diagnostics").get("rail_grouping_enabled") is True
        if phase_g_marker and set(corridor.family_id for corridor in corridors) != set(present_families):
            raise ContractValidationError("Phase-G snapshot corridors must cover every published family")
        for corridor in corridors:
            family = present_families.get(corridor.family_id)
            if family is None:
                raise ContractValidationError("snapshot corridor must reference a published family")
            if (
                corridor.asset != self.asset
                or corridor.timeframe != self.timeframe
                or corridor.timestamp != self.timestamp
                or corridor.role is not family.current_role
                or corridor.model_version != self.model_version
                or corridor.config_version != self.config_version
                or corridor.resolved_config_hash != self.resolved_config_hash
            ):
                raise ContractValidationError("snapshot corridor identity must match its family and snapshot")
            if corridor.representative_member_id != family.representative_member_id:
                raise ContractValidationError("snapshot corridor representative must match its family")
            if not _interaction_close(
                corridor.representative_slope_per_second,
                family.representative.slope_per_second,
            ):
                raise ContractValidationError("snapshot corridor representative slope must match its exact rail")
            if set(corridor.ordered_member_ids) != {member.member_id for member in family.members}:
                raise ContractValidationError("snapshot corridor member IDs must match its family exactly")
            member_by_id = {member.member_id: member for member in family.members}
            expected_rails = tuple(
                sorted(
                    (
                        (
                            member.geometry.value_at(self.timestamp),
                            member.member_id,
                        )
                        for member in family.members
                    ),
                    key=lambda item: item,
                )
            )
            if tuple(corridor.ordered_member_ids) != tuple(item[1] for item in expected_rails):
                raise ContractValidationError("snapshot corridor rail ordering must match exact geometry")
            normalization_atr = _number(
                _mapping(self.diagnostics, field_name="diagnostics").get("normalization_atr"),
                field_name="diagnostics.normalization_atr",
                minimum=0.0,
            )
            if normalization_atr <= 0.0:
                raise ContractValidationError("snapshot corridor requires positive normalization ATR")
            for rail, (price, member_id) in zip(corridor.rails, expected_rails, strict=True):
                if rail.member_id != member_id or not _interaction_close(rail.projected_price, price):
                    raise ContractValidationError("snapshot corridor projected rail must match exact member geometry")
                expected_offset = (
                    rail.projected_price - corridor.center_price
                ) / normalization_atr
                if not _interaction_close(rail.offset_from_representative_atr, expected_offset):
                    raise ContractValidationError("snapshot corridor rail offset must match normalization ATR")
            if not _interaction_close(
                corridor.center_price,
                member_by_id[corridor.representative_member_id].geometry.value_at(self.timestamp),
            ):
                raise ContractValidationError("snapshot corridor center must use the exact representative rail")
            if not _interaction_close(corridor.lower_price, corridor.rails[0].projected_price):
                raise ContractValidationError("snapshot corridor lower bound must match its first rail")
            if not _interaction_close(corridor.upper_price, corridor.rails[-1].projected_price):
                raise ContractValidationError("snapshot corridor upper bound must match its last rail")
            if not _interaction_close(
                corridor.width_atr,
                corridor.width_absolute / normalization_atr,
            ):
                raise ContractValidationError("snapshot corridor width_atr must match normalization ATR")
            gaps = tuple(
                (corridor.rails[index + 1].projected_price - corridor.rails[index].projected_price)
                / normalization_atr
                for index in range(corridor.rail_count - 1)
            )
            if gaps:
                expected_max = max(gaps)
                expected_median = sorted(gaps)[len(gaps) // 2] if len(gaps) % 2 else (
                    sorted(gaps)[len(gaps) // 2 - 1] + sorted(gaps)[len(gaps) // 2]
                ) / 2.0
                mean_gap = sum(gaps) / len(gaps)
                variance = sum((gap - mean_gap) ** 2 for gap in gaps) / len(gaps)
                expected_stability = 1.0 / (
                    1.0 + math.sqrt(variance) / expected_median
                )
                if (
                    not _interaction_close(corridor.max_adjacent_gap_atr or 0.0, expected_max)
                    or not _interaction_close(corridor.median_adjacent_gap_atr or 0.0, expected_median)
                    or not _interaction_close(corridor.spacing_stability or 0.0, expected_stability)
                ):
                    raise ContractValidationError("snapshot corridor spacing diagnostics must match rail projections")
        if phase_g_marker:
            transition_by_family_id: dict[str, FamilyTransition] = {}
            for transition in transitions:
                if transition.family_id in transition_by_family_id:
                    raise ContractValidationError("Phase-G snapshot requires at most one transition per family")
                transition_by_family_id[transition.family_id] = transition
            published_family_ids = set(present_families)
            current_transition_family_ids = {
                transition.family_id
                for transition in transitions
                if transition.transition_type is not FamilyTransitionType.EXPIRE
            }
            if current_transition_family_ids != published_family_ids:
                raise ContractValidationError(
                    "Phase-G snapshot requires one current family transition per published family"
                )
            if any(transition.timestamp != self.timestamp for transition in transitions):
                raise ContractValidationError("Phase-G transition timestamp must match snapshot timestamp")
            if any(
                transition.source_group_id is None
                and transition.source_group_candidate_ids
                for transition in transitions
            ):
                raise ContractValidationError(
                    "Phase-G source group candidates require a source group audit"
                )
            source_group_by_id = {
                audit.source_group_id: audit for audit in source_group_audits
            }
            referenced_source_group_ids = {
                transition.source_group_id
                for transition in transitions
                if transition.source_group_id is not None
            }
            if set(source_group_by_id) != referenced_source_group_ids:
                raise ContractValidationError(
                    "Phase-G source group audits must exactly cover transition provenance"
                )
            for transition in transitions:
                family = present_families.get(transition.family_id)
                if transition.transition_type is FamilyTransitionType.EXPIRE:
                    if (
                        transition.current_rail_count != 0
                        or transition.current_representative_member_id is not None
                        or transition.added_member_ids
                        or transition.continued_member_ids
                    ):
                        raise ContractValidationError("EXPIRE transition cannot retain current rail evidence")
                    resulting_family_state = None
                else:
                    if family is None:  # Defensive: the generic boundary already rejects this.
                        raise ContractValidationError("Phase-G transition must reference a published family")
                    current_member_ids = {member.member_id for member in family.members}
                    audited_current_member_ids = set(transition.added_member_ids) | set(
                        transition.continued_member_ids
                    )
                    if transition.current_rail_count != len(family.members):
                        raise ContractValidationError("Phase-G transition current_rail_count must match its family")
                    if audited_current_member_ids != current_member_ids:
                        raise ContractValidationError("Phase-G transition membership audit must match its family")
                    if transition.current_representative_member_id != family.representative_member_id:
                        raise ContractValidationError("Phase-G transition representative must match its family")
                    if transition.transition_type is FamilyTransitionType.BIRTH:
                        if (
                            transition.previous_rail_count != 0
                            or transition.previous_representative_member_id is not None
                            or transition.continued_member_ids
                            or transition.removed_member_ids
                            or set(transition.added_member_ids) != current_member_ids
                        ):
                            raise ContractValidationError("Phase-G BIRTH transition audit must contain only added rails")
                    elif (
                        transition.previous_representative_member_id is None
                        or transition.current_representative_member_id is None
                    ):
                        raise ContractValidationError("Phase-G continuation transition requires representative evidence")
                    resulting_family_state = family.to_dict()
                    if transition.source_group_id is not None:
                        audit = source_group_by_id.get(transition.source_group_id)
                        if audit is None:
                            raise ContractValidationError("Phase-G transition source group audit is missing")
                        if (
                            audit.asset != self.asset
                            or audit.timeframe != self.timeframe
                            or audit.observed_at != self.timestamp
                            or audit.role is not family.current_role
                            or audit.model_version != self.model_version
                            or audit.config_version != self.config_version
                            or audit.resolved_config_hash != self.resolved_config_hash
                        ):
                            raise ContractValidationError(
                                "Phase-G source group audit identity must match snapshot and family"
                            )
                        if audit.candidate_ids != transition.source_group_candidate_ids:
                            raise ContractValidationError(
                                "Phase-G source group candidates must match transition provenance"
                            )
                    elif transition.source_group_candidate_ids:
                        raise ContractValidationError(
                            "Phase-G source group candidates require a source group audit"
                        )
                transition_payload = transition.to_dict()
                transition_payload.pop("transition_id")
                expected_transition_id = deterministic_id(
                    "family-transition",
                    {
                        "transition": transition_payload,
                        "resulting_family_state": resulting_family_state,
                    },
                )
                if transition.transition_id != expected_transition_id:
                    raise ContractValidationError("Phase-G transition_id must bind the audit and resulting family")
        if any(not isinstance(observation, FamilyInteractionObservation) for observation in observations):
            raise ContractValidationError("snapshot observations must use FamilyInteractionObservation")
        if len({observation.observation_id for observation in observations}) != len(observations):
            raise ContractValidationError("snapshot observation IDs must be unique")
        if len({observation.family_id for observation in observations}) != len(observations):
            raise ContractValidationError("snapshot observations must contain exactly one observation per family")
        if observations and tuple(sorted(observations, key=lambda item: (item.family_id, item.observation_id))) != observations:
            raise ContractValidationError("snapshot observations must have deterministic family ordering")
        if any(observation.timestamp != self.timestamp for observation in observations):
            raise ContractValidationError("snapshot observations must use the snapshot timestamp")
        if any(observation.family_id not in present_families for observation in observations):
            raise ContractValidationError("snapshot observations must reference published families")
        if observations and len(observations) != len(present_families):
            raise ContractValidationError("non-empty snapshot observations must cover every published family exactly once")
        if observations and {observation.family_id for observation in observations} != set(present_families):
            raise ContractValidationError("non-empty snapshot observations must cover every published family")
        for observation in observations:
            family = present_families[observation.family_id]
            exact_center = family.representative.value_at(self.timestamp)
            if observation.role is not family.current_role:
                raise ContractValidationError("snapshot observation role must match the published family role")
            if not _interaction_close(observation.exact_line_price, exact_center):
                raise ContractValidationError("snapshot observation exact line price must match the published representative")
            if not _interaction_close(observation.zone.center_price, exact_center):
                raise ContractValidationError("snapshot observation zone center must match the published representative")
            if observation.zone.line_id != family.family_id:
                raise ContractValidationError("snapshot observation zone must identify the published family")
        observation_by_id = {
            observation.observation_id: observation for observation in observations
        }
        if any(not isinstance(event, FamilyInteractionEvent) for event in interaction_events):
            raise ContractValidationError("snapshot interaction_events must use FamilyInteractionEvent")
        if len({event.event_id for event in interaction_events}) != len(interaction_events):
            raise ContractValidationError("snapshot interaction event IDs must be unique")
        if len({event.family_id for event in interaction_events}) != len(interaction_events):
            raise ContractValidationError("snapshot contains more than one interaction event per family")
        if interaction_events and tuple(sorted(interaction_events, key=lambda item: (item.family_id, item.event_id))) != interaction_events:
            raise ContractValidationError("snapshot interaction events must have deterministic family ordering")
        for event in interaction_events:
            family = present_families.get(event.family_id)
            if family is None:
                raise ContractValidationError("snapshot interaction event must reference a published family")
            if event.asset != self.asset or event.timeframe != self.timeframe:
                raise ContractValidationError("snapshot interaction event asset/timeframe mismatch")
            if event.model_version != self.model_version or event.config_version != self.config_version or event.resolved_config_hash != self.resolved_config_hash:
                raise ContractValidationError("snapshot interaction event metadata must match the snapshot")
            if event.updated_at > self.timestamp:
                raise ContractValidationError("snapshot interaction event timestamp cannot exceed snapshot timestamp")
            if event.current_event_role is not family.current_role:
                raise ContractValidationError("snapshot interaction event role must match the published family")
            if (
                family.lifecycle_state is FamilyLifecycleState.DORMANT
                and event.state is InteractionEventState.ROLE_REVERSED
            ):
                raise ContractValidationError(
                    "dormant family cannot retain a ROLE_REVERSED interaction event"
                )
            if (
                family.lifecycle_state is FamilyLifecycleState.ACTIVE
                and event.updated_at == self.timestamp
            ):
                observation = observation_by_id.get(event.last_observation_id)
                if observation is None or observation.family_id != event.family_id:
                    raise ContractValidationError(
                        "active current event must reference its current family observation"
                    )
        if any(not isinstance(transition, FamilyInteractionEventTransition) for transition in interaction_event_transitions):
            raise ContractValidationError("snapshot interaction event transitions must use canonical contracts")
        if len({transition.transition_id for transition in interaction_event_transitions}) != len(interaction_event_transitions):
            raise ContractValidationError("snapshot interaction event transition IDs must be unique")
        if interaction_event_transitions and tuple(sorted(interaction_event_transitions, key=lambda item: (item.event_id, item.transition_id))) != interaction_event_transitions:
            raise ContractValidationError("snapshot interaction event transitions must have deterministic ordering")
        event_by_id = {event.event_id: event for event in interaction_events}
        transitions_by_event_id: dict[str, list[FamilyInteractionEventTransition]] = {}
        for transition in interaction_event_transitions:
            transitions_by_event_id.setdefault(transition.event_id, []).append(transition)
        for event in interaction_events:
            event_transitions = transitions_by_event_id.get(event.event_id, [])
            if event.updated_at != self.timestamp:
                if event_transitions:
                    raise ContractValidationError(
                        "frozen interaction event cannot include a current transition"
                    )
                continue
            if event.previous_state is None:
                if event_transitions:
                    raise ContractValidationError(
                        "new interaction episode cannot include a transition"
                    )
                continue
            if event.previous_state is event.state:
                if event_transitions:
                    raise ContractValidationError(
                        "unchanged interaction event cannot include a transition"
                    )
                continue
            if len(event_transitions) != 1:
                raise ContractValidationError(
                    "changed interaction event requires exactly one transition"
                )
        for transition in interaction_event_transitions:
            event = event_by_id.get(transition.event_id)
            if event is None:
                raise ContractValidationError("snapshot interaction event transition must reference a persisted event")
            if transition.family_id != event.family_id:
                raise ContractValidationError("event transition family must match its event")
            observation = observation_by_id.get(transition.trigger_observation_id)
            if observation is None or observation.family_id != event.family_id:
                raise ContractValidationError("event transition must reference an observation for the same family")
            if observation.close_price is None:
                raise ContractValidationError(
                    "event transition requires persisted close_price evidence"
                )
            if transition.timestamp > self.timestamp:
                raise ContractValidationError("event transition timestamp cannot exceed snapshot timestamp")
            if transition.model_version != self.model_version or transition.config_version != self.config_version or transition.resolved_config_hash != self.resolved_config_hash:
                raise ContractValidationError("event transition metadata must match the containing snapshot")
            if transition.to_state is not event.state:
                raise ContractValidationError("event transition target must match the persisted event state")
            if transition.from_state is not event.previous_state:
                raise ContractValidationError("event transition source must match the persisted previous state")
            if transition.timestamp != event.updated_at:
                raise ContractValidationError("event transition timestamp must match the persisted event update")
            if transition.trigger_observation_id != event.last_observation_id:
                raise ContractValidationError("event transition observation must match the persisted event")
            from .events import is_allowed_event_transition

            if not is_allowed_event_transition(transition.from_state, transition.to_state):
                raise ContractValidationError(
                    "snapshot contains a forbidden interaction event transition: "
                    f"{transition.from_state.value}->{transition.to_state.value}"
                )
        for event in interaction_events:
            family = present_families[event.family_id]
            if (
                family.lifecycle_state is FamilyLifecycleState.ACTIVE
                and event.updated_at == self.timestamp
            ):
                observation = observation_by_id[event.last_observation_id]
                if observation.close_price is None:
                    raise ContractValidationError(
                        "active current interaction event requires persisted close_price evidence"
                    )
        diagnostics = _freeze_mapping(self.diagnostics, field_name="diagnostics")
        interaction_diagnostic_keys = (
            "interaction_atr",
            "interaction_atr_method",
            "interaction_atr_sample_count",
            "interaction_observation_count",
        )
        present_interaction_diagnostic_keys = tuple(
            key for key in interaction_diagnostic_keys if key in diagnostics
        )
        if observations:
            reference_observation = observations[0]
            for observation in observations[1:]:
                if not _interaction_close(observation.interaction_atr, reference_observation.interaction_atr):
                    raise ContractValidationError("snapshot observations must use one interaction ATR value")
                if observation.interaction_atr_method != reference_observation.interaction_atr_method:
                    raise ContractValidationError("snapshot observations must use one interaction ATR method")
                if observation.interaction_atr_sample_count != reference_observation.interaction_atr_sample_count:
                    raise ContractValidationError("snapshot observations must use one interaction ATR sample count")
            diagnostic_atr = _number(diagnostics.get("interaction_atr"), field_name="diagnostics.interaction_atr", minimum=0.0)
            if diagnostic_atr <= 0.0 or not _interaction_close(diagnostic_atr, reference_observation.interaction_atr):
                raise ContractValidationError("snapshot interaction_atr diagnostic must match observations")
            if diagnostics.get("interaction_atr_method") != reference_observation.interaction_atr_method:
                raise ContractValidationError("snapshot interaction_atr_method diagnostic must match observations")
            if _integer(
                diagnostics.get("interaction_atr_sample_count"),
                field_name="diagnostics.interaction_atr_sample_count",
                minimum=1,
            ) != reference_observation.interaction_atr_sample_count:
                raise ContractValidationError("snapshot interaction_atr_sample_count diagnostic must match observations")
            if _integer(
                diagnostics.get("interaction_observation_count"),
                field_name="diagnostics.interaction_observation_count",
            ) != len(observations):
                raise ContractValidationError("snapshot interaction_observation_count diagnostic must match observations")
        elif present_interaction_diagnostic_keys:
            if set(present_interaction_diagnostic_keys) != set(interaction_diagnostic_keys):
                raise ContractValidationError(
                    "empty snapshot observations require either no interaction diagnostics or the complete empty set"
                )
            if _integer(
                diagnostics["interaction_observation_count"],
                field_name="diagnostics.interaction_observation_count",
            ) != 0:
                raise ContractValidationError(
                    "empty snapshot observations require interaction_observation_count equal to zero"
                )
            if any(
                diagnostics[key] is not None
                for key in (
                    "interaction_atr",
                    "interaction_atr_method",
                    "interaction_atr_sample_count",
                )
            ):
                raise ContractValidationError(
                    "empty snapshot observations require null interaction ATR diagnostics"
                )
        object.__setattr__(self, "active_families", active_families)
        object.__setattr__(self, "dormant_families", dormant_families)
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "source_group_audits", source_group_audits)
        object.__setattr__(self, "corridors", corridors)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "interaction_events", interaction_events)
        object.__setattr__(self, "interaction_event_transitions", interaction_event_transitions)
        object.__setattr__(self, "diagnostics", diagnostics)
        validate_trendline_family_snapshot_identity(self)

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineFamilySnapshot":
        return _decode("TrendlineFamilySnapshot", value, lambda item: cls(
            snapshot_id=_required(item, "snapshot_id", owner="TrendlineFamilySnapshot"), asset=_required(item, "asset", owner="TrendlineFamilySnapshot"),
            timeframe=_required(item, "timeframe", owner="TrendlineFamilySnapshot"), timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="TrendlineFamilySnapshot")),
            previous_snapshot_id=item.get("previous_snapshot_id"), model_version=_required(item, "model_version", owner="TrendlineFamilySnapshot"),
            config_version=_required(item, "config_version", owner="TrendlineFamilySnapshot"), resolved_config_hash=_required(item, "resolved_config_hash", owner="TrendlineFamilySnapshot"),
            active_families=tuple(TrendlineFamilyState.from_dict(family) for family in _required(item, "active_families", owner="TrendlineFamilySnapshot")),
            dormant_families=tuple(TrendlineFamilyState.from_dict(family) for family in _required(item, "dormant_families", owner="TrendlineFamilySnapshot")),
            transitions=tuple(FamilyTransition.from_dict(transition) for transition in _required(item, "transitions", owner="TrendlineFamilySnapshot")),
            source_group_audits=tuple(
                FamilySourceGroupAudit.from_dict(audit)
                for audit in item.get("source_group_audits", ())
            ),
            corridors=tuple(FamilyCorridor.from_dict(corridor) for corridor in item.get("corridors", ())),
            observations=tuple(FamilyInteractionObservation.from_dict(observation) for observation in item.get("observations", ())),
            interaction_events=tuple(FamilyInteractionEvent.from_dict(event) for event in item.get("interaction_events", ())),
            interaction_event_transitions=tuple(FamilyInteractionEventTransition.from_dict(transition) for transition in item.get("interaction_event_transitions", ())),
            diagnostics=item.get("diagnostics", {}),
        ))


def trendline_family_snapshot_identity_payload(
    *,
    asset: str,
    timeframe: str,
    timestamp: datetime,
    previous_snapshot_id: str | None,
    model_version: str,
    config_version: str,
    resolved_config_hash: str,
    active_families: tuple[TrendlineFamilyState, ...],
    dormant_families: tuple[TrendlineFamilyState, ...],
    transitions: tuple[FamilyTransition, ...],
    source_group_audits: tuple[FamilySourceGroupAudit, ...],
    corridors: tuple[FamilyCorridor, ...],
    observations: tuple[FamilyInteractionObservation, ...],
    interaction_events: tuple[FamilyInteractionEvent, ...],
    interaction_event_transitions: tuple[FamilyInteractionEventTransition, ...],
    diagnostics: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return canonical Phase-G snapshot identity inputs, excluding snapshot_id."""

    return {
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "previous_snapshot_id": previous_snapshot_id,
        "model_version": model_version,
        "config_version": config_version,
        "resolved_config_hash": resolved_config_hash,
        "active_families": active_families,
        "dormant_families": dormant_families,
        "transitions": transitions,
        "source_group_audits": source_group_audits,
        "corridors": corridors,
        "observations": observations,
        "interaction_events": interaction_events,
        "interaction_event_transitions": interaction_event_transitions,
        "diagnostics": diagnostics,
    }


def compute_trendline_family_snapshot_id(
    **identity_inputs: Any,
) -> str:
    """Compute canonical content-addressed identity for a complete Phase-G snapshot."""

    return deterministic_id(
        "family-snapshot",
        trendline_family_snapshot_identity_payload(**identity_inputs),
    )


def trendline_family_snapshot_has_phase_g_evidence(
    snapshot: TrendlineFamilySnapshot,
) -> bool:
    """Classify Phase-G payloads from immutable structural evidence and marker."""

    diagnostics = snapshot.diagnostics
    if diagnostics.get("rail_grouping_enabled") is True:
        return True
    if snapshot.source_group_audits or snapshot.corridors:
        return True
    if any(
        len(family.members) > 1
        for family in snapshot.active_families + snapshot.dormant_families
    ):
        return True
    if any(
        transition.added_member_ids
        or transition.continued_member_ids
        or transition.removed_member_ids
        or transition.previous_representative_member_id is not None
        or transition.current_representative_member_id is not None
        or transition.previous_rail_count > 0
        or transition.current_rail_count > 0
        or transition.source_group_id is not None
        or transition.source_group_candidate_ids
        for transition in snapshot.transitions
    ):
        return True
    return any(key in diagnostics for key in _PHASE_G_DIAGNOSTIC_KEYS)


def validate_trendline_family_snapshot_identity(snapshot: TrendlineFamilySnapshot) -> None:
    """Require a canonical aggregate ID only for Phase-G snapshot payloads."""

    if not trendline_family_snapshot_has_phase_g_evidence(snapshot):
        return
    if snapshot.diagnostics.get("rail_grouping_enabled") is not True:
        raise ContractValidationError(
            "Phase-G evidence requires diagnostics.rail_grouping_enabled=True"
        )
    expected_snapshot_id = compute_trendline_family_snapshot_id(
        asset=snapshot.asset,
        timeframe=snapshot.timeframe,
        timestamp=snapshot.timestamp,
        previous_snapshot_id=snapshot.previous_snapshot_id,
        model_version=snapshot.model_version,
        config_version=snapshot.config_version,
        resolved_config_hash=snapshot.resolved_config_hash,
        active_families=snapshot.active_families,
        dormant_families=snapshot.dormant_families,
        transitions=snapshot.transitions,
        source_group_audits=snapshot.source_group_audits,
        corridors=snapshot.corridors,
        observations=snapshot.observations,
        interaction_events=snapshot.interaction_events,
        interaction_event_transitions=snapshot.interaction_event_transitions,
        diagnostics=snapshot.diagnostics,
    )
    if snapshot.snapshot_id != expected_snapshot_id:
        raise ContractValidationError(
            "Phase-G snapshot_id must bind the complete snapshot payload"
        )


@dataclass(frozen=True)
class TrendlineFamilyOutput:
    snapshot: TrendlineFamilySnapshot
    ranked_support_families: tuple[str, ...]
    ranked_resistance_families: tuple[str, ...]
    nearest_support_family_id: str | None
    nearest_resistance_family_id: str | None
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, TrendlineFamilySnapshot):
            raise ContractValidationError("output snapshot must use TrendlineFamilySnapshot")
        object.__setattr__(self, "ranked_support_families", _tuple_of_strings(self.ranked_support_families, field_name="ranked_support_families"))
        object.__setattr__(self, "ranked_resistance_families", _tuple_of_strings(self.ranked_resistance_families, field_name="ranked_resistance_families"))
        object.__setattr__(self, "nearest_support_family_id", _optional_string(self.nearest_support_family_id, field_name="nearest_support_family_id"))
        object.__setattr__(self, "nearest_resistance_family_id", _optional_string(self.nearest_resistance_family_id, field_name="nearest_resistance_family_id"))
        object.__setattr__(self, "features", _freeze_mapping(self.features, field_name="features"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrendlineFamilyOutput":
        return _decode("TrendlineFamilyOutput", value, lambda item: cls(
            snapshot=TrendlineFamilySnapshot.from_dict(_required(item, "snapshot", owner="TrendlineFamilyOutput")),
            ranked_support_families=tuple(_required(item, "ranked_support_families", owner="TrendlineFamilyOutput")),
            ranked_resistance_families=tuple(_required(item, "ranked_resistance_families", owner="TrendlineFamilyOutput")),
            nearest_support_family_id=item.get("nearest_support_family_id"), nearest_resistance_family_id=item.get("nearest_resistance_family_id"), features=item.get("features", {}),
        ))
