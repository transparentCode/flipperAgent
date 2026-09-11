"""The single causal SR v2 structural step."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from .config.resolver import ResolvedSRV2Config
from .contracts import FrozenMapping, LifecycleState, require_utc
from .domain.bars import SRBar
from .domain.candidates import Candidate
from .domain.identity import (
    bar_content_fingerprint,
    canonical_json,
    fingerprint_sequence_hash,
    window_fingerprint,
)
from .domain.state import SRState
from .domain.zones import ZoneRecord
from .features.time import grid_for
from .kernels.registry import KernelEvaluation, KernelSpec
from .lifecycle.engine import advance_zone, apply_candidates_with_replacements
from .lifecycle.rules import LifecycleRules
from .lifecycle.transitions import LifecycleTransition, TransitionType, make_transition


@dataclass(frozen=True, slots=True, kw_only=True)
class SRStepRequest:
    """One immutable closed-bar request for the semantic core."""

    venue: str
    instrument_id: str
    asset: str
    market_as_of: datetime
    state: SRState
    windows: Mapping[str, Sequence[SRBar]]

    def __post_init__(self) -> None:
        for name in ("venue", "instrument_id", "asset"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty runtime identity")
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.state, SRState):
            raise TypeError("state must be SRState")
        if not isinstance(self.windows, Mapping):
            raise TypeError("windows must be a mapping")
        normalized: dict[str, tuple[SRBar, ...]] = {}
        for timeframe, values in self.windows.items():
            if not isinstance(timeframe, str) or not timeframe.strip():
                raise TypeError("window keys must be non-empty strings")
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                raise TypeError(f"window must be a sequence: {timeframe}")
            normalized[timeframe] = tuple(values)
        object.__setattr__(self, "windows", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class SRStepResult:
    """Immutable output of one structural step."""

    venue: str
    instrument_id: str
    asset: str
    market_as_of: datetime
    config_fingerprint: str
    current_price: Decimal
    source_cutoffs: Mapping[str, datetime]
    source_fingerprints: Mapping[str, str]
    source_fingerprint_sequences: Mapping[str, tuple[str, ...]]
    evaluated_timeframes: tuple[str, ...]
    candidates_by_timeframe: Mapping[str, tuple[Candidate, ...]]
    feature_rows: tuple[Mapping[str, object], ...]
    duplicate_delivery: bool
    transitions: tuple[LifecycleTransition, ...]
    state: SRState
    lineage_registry: Mapping[str, ZoneRecord]

    def __post_init__(self) -> None:
        for name in ("venue", "instrument_id", "asset", "config_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.current_price, Decimal) or not self.current_price.is_finite():
            raise TypeError("current_price must be a finite Decimal")
        evaluated = tuple(self.evaluated_timeframes)
        if any(not isinstance(item, str) or not item.strip() for item in evaluated):
            raise ValueError("evaluated_timeframes must contain non-empty strings")
        if len(evaluated) != len(set(evaluated)):
            raise ValueError("evaluated_timeframes must be unique")
        candidates = {key: tuple(value) for key, value in self.candidates_by_timeframe.items()}
        if set(candidates) != set(evaluated):
            raise ValueError("candidate output keys must equal evaluated_timeframes")
        if any(not isinstance(item, Candidate) for values in candidates.values() for item in values):
            raise TypeError("candidates_by_timeframe must contain Candidate values")
        if any(not isinstance(item, LifecycleTransition) for item in self.transitions):
            raise TypeError("transitions must contain LifecycleTransition values")
        if not isinstance(self.state, SRState):
            raise TypeError("state must be SRState")
        if any(not isinstance(item, ZoneRecord) for item in self.lineage_registry.values()):
            raise TypeError("lineage_registry must contain ZoneRecord values")
        cutoffs = dict(self.source_cutoffs)
        fingerprints = dict(self.source_fingerprints)
        if set(cutoffs) != set(fingerprints):
            raise ValueError("result source cutoffs and fingerprints must cover the same timeframes")
        object.__setattr__(self, "source_cutoffs", FrozenMapping(dict(sorted(cutoffs.items()))))
        object.__setattr__(self, "source_fingerprints", FrozenMapping(dict(sorted(fingerprints.items()))))
        sequences = {
            key: tuple(value) for key, value in self.source_fingerprint_sequences.items()
        }
        if set(sequences) != set(self.source_fingerprints):
            raise ValueError("result source fingerprints and sequences must cover the same timeframes")
        if any(
            fingerprint_sequence_hash(values) != self.source_fingerprints[key]
            for key, values in sequences.items()
        ):
            raise ValueError("result source fingerprint aggregate does not match its sequence")
        object.__setattr__(self, "source_fingerprint_sequences", FrozenMapping(sequences))
        object.__setattr__(self, "evaluated_timeframes", evaluated)
        object.__setattr__(
            self,
            "candidates_by_timeframe",
            MappingProxyType({key: candidates[key] for key in sorted(candidates)}),
        )
        object.__setattr__(self, "feature_rows", tuple(MappingProxyType(dict(row)) for row in self.feature_rows))
        object.__setattr__(self, "transitions", tuple(self.transitions))
        object.__setattr__(self, "lineage_registry", MappingProxyType(dict(sorted(self.lineage_registry.items()))))


class SRModel:
    """Deterministic closed-bar structural processor."""

    def __init__(self, config: ResolvedSRV2Config) -> None:
        if not isinstance(config, ResolvedSRV2Config):
            raise TypeError("config must be ResolvedSRV2Config")
        self.config = config
        self._lifecycle_rules = LifecycleRules(
            break_buffer_atr=config.break_buffer_atr,
            break_confirmation_bars=config.break_confirmation_bars,
            expiry=config.expiry,
        )

    def step(self, request: SRStepRequest) -> SRStepResult:
        if not isinstance(request, SRStepRequest):
            raise TypeError("request must be SRStepRequest")
        state = request.state
        if state.config_fingerprint != self.config.config_fingerprint:
            raise ValueError("state/config fingerprint mismatch")
        if (state.venue, state.instrument_id, state.asset) != (
            request.venue,
            request.instrument_id,
            request.asset,
        ):
            raise ValueError("state identity does not match runtime context")
        bars, incoming_cutoffs, incoming_fingerprints, incoming_sequences = self._normalize_windows(request)
        duplicate = state.last_trigger_at == request.market_as_of
        if duplicate and state.last_trigger_at is not None:
            trigger = self.config.trigger_timeframe
            if state.source_fingerprints.get(trigger) != incoming_fingerprints[trigger]:
                raise ValueError("SR v2 duplicate delivery conflicts with committed source content")
            if state.source_fingerprint_sequences.get(trigger) != incoming_sequences[trigger]:
                raise ValueError("SR v2 duplicate delivery conflicts with committed source sequence")
        if state.last_trigger_at is not None and not duplicate:
            expected = state.last_trigger_at + self.config.trigger_duration
            if request.market_as_of != expected:
                raise ValueError("SR v2 non-duplicate trigger must advance exactly one trigger duration")

        current_price = bars[self.config.trigger_timeframe][-1].close
        if duplicate:
            return SRStepResult(
                venue=request.venue,
                instrument_id=request.instrument_id,
                asset=request.asset,
                market_as_of=request.market_as_of,
                config_fingerprint=self.config.config_fingerprint,
                current_price=current_price,
                source_cutoffs=incoming_cutoffs,
                source_fingerprints=incoming_fingerprints,
                source_fingerprint_sequences=incoming_sequences,
                evaluated_timeframes=(),
                candidates_by_timeframe={},
                feature_rows=(),
                duplicate_delivery=True,
                transitions=(),
                state=state,
                lineage_registry={
                    item.lineage.zone_id: item
                    for item in state.active_lineages + state.terminal_tombstones
                },
            )

        trigger_bars = tuple(
            bar
            for bar in bars[self.config.trigger_timeframe]
            if state.last_trigger_at is None or bar.bar_close_at > state.last_trigger_at
        )
        active_records = list(state.active_lineages)
        terminal_records = list(state.terminal_tombstones)
        transitions: list[LifecycleTransition] = []
        for record in tuple(active_records):
            updated = record
            for bar in trigger_bars:
                updated, emitted = advance_zone(updated, bar, rules=self._lifecycle_rules)
                transitions.extend(emitted)
            active_records.remove(record)
            if updated.lifecycle in {
                LifecycleState.BROKEN,
                LifecycleState.EXPIRED,
                LifecycleState.SUPERSEDED,
            }:
                if updated.lineage.zone_id not in {item.lineage.zone_id for item in terminal_records}:
                    terminal_records.append(updated)
            else:
                active_records.append(updated)

        detected: dict[str, tuple[Candidate, ...]] = {}
        feature_rows: list[Mapping[str, object]] = []
        market_identity = {
            "venue": request.venue,
            "instrument_id": request.instrument_id,
            "asset": request.asset,
        }
        for timeframe in self.config.ladder:
            if timeframe not in bars:
                continue
            cutoff = incoming_cutoffs[timeframe]
            candidates: list[Candidate] = []
            for kernel in self.config.kernels:
                params = kernel.parameters_for(timeframe)
                if not kernel.enabled_for(timeframe):
                    continue
                kernel_required = int(kernel.spec.history_required(params))
                kernel_window = bars[timeframe][-kernel_required:]
                evaluation: KernelEvaluation = kernel.spec.evaluate(
                    kernel_window,
                    market_identity=market_identity,
                    parameters=params,
                )
                self._validate_kernel_output(kernel.spec, evaluation)
                candidates.extend(evaluation.candidates)
                feature_rows.extend(
                    {
                        **dict(row),
                        "cutoff": request.market_as_of,
                        "source_cutoff": cutoff,
                    }
                    for row in evaluation.consumed_feature_rows
                )
                active, terminal, emitted = apply_candidates_with_replacements(
                    active_records,
                    terminal_records,
                    evaluation.candidates,
                    config_fingerprint=self.config.config_fingerprint,
                    now=cutoff,
                    replacement_policy=kernel.spec.replacement_policy,
                )
                active_records = list(active)
                terminal_records = list(terminal)
                transitions.extend(emitted)
            detected[timeframe] = tuple(candidates)

        active_records, terminal_records = self._deduplicate_records(active_records, terminal_records)
        registry = {item.lineage.zone_id: item for item in active_records + terminal_records}
        active_records, terminal_records, pruned = self._bound_state(
            active_records,
            terminal_records,
            event_at=request.market_as_of,
        )
        transitions.extend(pruned)
        next_state = replace(
            state,
            generation=state.generation + 1,
            last_trigger_at=request.market_as_of,
            source_cutoffs=incoming_cutoffs,
            source_fingerprints=incoming_fingerprints,
            source_fingerprint_sequences=incoming_sequences,
            active_lineages=tuple(active_records),
            terminal_tombstones=tuple(terminal_records),
        )
        normalized = tuple(item.with_ordinal(index) for index, item in enumerate(transitions))
        return SRStepResult(
            venue=request.venue,
            instrument_id=request.instrument_id,
            asset=request.asset,
            market_as_of=request.market_as_of,
            config_fingerprint=self.config.config_fingerprint,
            current_price=current_price,
            source_cutoffs=incoming_cutoffs,
            source_fingerprints=incoming_fingerprints,
            source_fingerprint_sequences=incoming_sequences,
            evaluated_timeframes=tuple(timeframe for timeframe in self.config.ladder if timeframe in detected),
            candidates_by_timeframe=detected,
            feature_rows=tuple(feature_rows),
            duplicate_delivery=False,
            transitions=normalized,
            state=next_state,
            lineage_registry=registry,
        )

    def _normalize_windows(
        self,
        request: SRStepRequest,
    ) -> tuple[
        dict[str, tuple[SRBar, ...]],
        dict[str, datetime],
        dict[str, str],
        dict[str, tuple[str, ...]],
    ]:
        state = request.state
        expected_cutoffs = {
            timeframe: grid_for(timeframe).expected_closed_cutoff(request.market_as_of)
            for timeframe in self.config.ladder
        }
        trigger = self.config.trigger_timeframe
        if expected_cutoffs[trigger] != request.market_as_of:
            raise ValueError("SR v2 market_as_of must equal the closed trigger cutoff")
        genesis = state.last_trigger_at is None
        if genesis:
            if state.source_cutoffs or state.source_fingerprints:
                raise ValueError("genesis state must not contain committed source identity")
            required_keys = set(self.config.ladder)
        else:
            if set(state.source_cutoffs) != set(self.config.ladder):
                raise ValueError("state source cutoffs must cover exactly the configured ladder")
            if set(state.source_fingerprints) != set(self.config.ladder):
                raise ValueError("state source fingerprints must cover exactly the configured ladder")
            if set(state.source_fingerprint_sequences) != set(self.config.ladder):
                raise ValueError("state source fingerprint sequences must cover exactly the configured ladder")
            for timeframe, previous in state.source_cutoffs.items():
                state_expected = grid_for(timeframe).expected_closed_cutoff(state.last_trigger_at)
                if previous != state_expected:
                    raise ValueError(f"state source cutoff is inconsistent: {timeframe}")
                if expected_cutoffs[timeframe] < previous:
                    raise ValueError(f"SR v2 source cutoff regressed: {timeframe}")
            required_keys = {trigger}
            required_keys.update(
                timeframe
                for timeframe in self.config.ladder
                if expected_cutoffs[timeframe] > state.source_cutoffs[timeframe]
            )
        supplied_keys = set(request.windows)
        if supplied_keys != required_keys:
            missing = sorted(required_keys - supplied_keys)
            extra = sorted(supplied_keys - required_keys)
            details = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if extra:
                details.append(f"extra={','.join(extra)}")
            raise ValueError("SR v2 sparse window keys are invalid: " + " ".join(details))

        requirements = dict(self.config.history_requirements())
        result: dict[str, tuple[SRBar, ...]] = {}
        cutoffs = dict(state.source_cutoffs)
        fingerprints = dict(state.source_fingerprints)
        sequences = dict(state.source_fingerprint_sequences)
        for timeframe in self.config.ladder:
            if timeframe not in request.windows:
                continue
            values = tuple(request.windows[timeframe])
            if not values:
                raise ValueError(f"missing required SR v2 history: {timeframe}")
            if any(not isinstance(item, SRBar) for item in values):
                raise TypeError(f"{timeframe} history must contain SRBar values")
            if any(item.timeframe != timeframe for item in values):
                raise ValueError(f"history timeframe mismatch: {timeframe}")
            grid_for(timeframe).validate_contiguous(
                tuple(item.bar_open_at for item in values),
                tuple(item.bar_close_at for item in values),
            )
            required = requirements[timeframe]
            if len(values) < required:
                raise ValueError(f"short SR v2 history: {timeframe}")
            if values[-1].bar_close_at != expected_cutoffs[timeframe]:
                raise ValueError(f"stale or misaligned latest {timeframe} history")
            selected = values[-required:]
            result[timeframe] = selected
            incoming_cutoff = selected[-1].bar_close_at
            incoming_sequence = tuple(bar_content_fingerprint(bar) for bar in selected)
            incoming_fingerprint = window_fingerprint(selected)
            if (
                not genesis
                and incoming_cutoff == state.source_cutoffs[timeframe]
                and incoming_fingerprint != state.source_fingerprints[timeframe]
            ):
                raise ValueError(f"SR v2 source content conflict at committed cutoff: {timeframe}")
            if not genesis:
                previous_sequence = state.source_fingerprint_sequences[timeframe]
                advance = int(
                    (incoming_cutoff - state.source_cutoffs[timeframe])
                    / grid_for(timeframe).duration
                )
                overlap = max(0, min(len(previous_sequence), len(incoming_sequence)) - advance)
                if overlap and previous_sequence[-overlap:] != incoming_sequence[:overlap]:
                    raise ValueError(
                        f"SR v2 source content conflict in committed overlap: {timeframe}"
                    )
            cutoffs[timeframe] = incoming_cutoff
            fingerprints[timeframe] = incoming_fingerprint
            sequences[timeframe] = incoming_sequence
        if genesis and set(cutoffs) != set(self.config.ladder):
            raise ValueError("genesis requires every configured timeframe window")
        return result, cutoffs, fingerprints, sequences

    @staticmethod
    def _validate_kernel_output(spec: KernelSpec, evaluation: KernelEvaluation) -> None:
        if not isinstance(evaluation, KernelEvaluation):
            raise TypeError(f"kernel evaluator must return KernelEvaluation: {spec.identifier}")
        if len(evaluation.candidates) > spec.max_candidates:
            raise ValueError(f"kernel candidate bound exceeded: {spec.identifier}")
        if len(evaluation.consumed_feature_rows) > spec.max_evidence_rows:
            raise ValueError(f"kernel evidence-row bound exceeded: {spec.identifier}")
        try:
            encoded_size = len(canonical_json(evaluation.consumed_feature_rows).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"kernel evidence is not canonically encodable: {spec.identifier}") from exc
        if encoded_size > spec.max_evidence_bytes:
            raise ValueError(f"kernel evidence-byte bound exceeded: {spec.identifier}")

    @staticmethod
    def _deduplicate_records(
        active: Sequence[ZoneRecord],
        terminal: Sequence[ZoneRecord],
    ) -> tuple[list[ZoneRecord], list[ZoneRecord]]:
        active_by_id = {record.lineage.zone_id: record for record in active}
        terminal_by_id = {record.lineage.zone_id: record for record in terminal}
        for zone_id in tuple(active_by_id):
            if zone_id in terminal_by_id:
                active_by_id.pop(zone_id)
        return list(active_by_id.values()), list(terminal_by_id.values())

    def _bound_state(
        self,
        active: Sequence[ZoneRecord],
        terminal: Sequence[ZoneRecord],
        *,
        event_at: datetime,
    ) -> tuple[list[ZoneRecord], list[ZoneRecord], list[LifecycleTransition]]:
        if len(active) > self.config.max_active_lineages:
            raise ValueError("SR v2 active lineage bound exceeded")
        ordered = sorted(
            terminal,
            key=lambda item: (item.last_transition_at or item.lineage.available_at, item.lineage.zone_id),
        )
        pruned = ordered[: max(0, len(ordered) - self.config.max_terminal_tombstones)]
        kept = ordered[len(pruned):]
        transitions = [
            make_transition(
                transition_type=TransitionType.TOMBSTONE_PRUNED,
                event_at=event_at,
                zone_id=record.lineage.zone_id,
                before_lifecycle=record.lifecycle,
                after_lifecycle=record.lifecycle,
                before_overlapping=record.was_overlapping,
                after_overlapping=record.was_overlapping,
                before_touch_count=record.touch_count,
                after_touch_count=record.touch_count,
                before_break_pending_count=record.break_pending_count,
                after_break_pending_count=record.break_pending_count,
                retention_state="TOMBSTONE_TO_PRUNED",
                predecessor_id=record.lineage.predecessor_id,
            )
            for record in pruned
        ]
        return list(active), list(kept), transitions


__all__ = ["LifecycleTransition", "SRModel", "SRStepRequest", "SRStepResult", "TransitionType"]
