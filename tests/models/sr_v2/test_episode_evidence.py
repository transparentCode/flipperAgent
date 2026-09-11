from __future__ import annotations

import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from libs.models.sr_v2.contracts import ForecastOutcome, LifecycleState, ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.identity import (
    canonical_hash,
    canonical_json,
    fingerprint_sequence_hash,
)
from libs.models.sr_v2.domain.state import SRState
from libs.models.sr_v2.domain.zones import ZoneRecord, lineage_from_candidate
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.forecast.targets import (
    ResolvedTargetSpec,
    ScientificReaction,
    TwoStageTargetView,
    label_scientific_target,
    label_scientific_target_indexed,
    scientific_target_fingerprint,
)
from libs.models.sr_v2.lifecycle.transitions import TransitionType
from libs.models.sr_v2.research.optimizer import (
    FixtureTargetIdentificationInput,
    TargetTuple,
    TargetTupleDiagnostic,
    TargetTupleStatus,
    _target_choice_id_for_tuple,
    _target_report,
    identify_target_from_compiled_fixture,
    identify_target_streaming,
    resolve_optimizer_config,
)
from libs.models.sr_v2.research.placebos import build_feasible_random_price_null
from libs.models.sr_v2.research.source import SourceBarRecord
from libs.models.sr_v2.research_lab import episode_evidence
from libs.models.sr_v2.research_lab.data import AuthenticatedSourceSlice
from libs.models.sr_v2.research_lab.episode_evidence import (
    COMMON_RISK_RECEIPT_SCHEMA,
    EPISODE_EVIDENCE_SCHEMA,
    TARGET_OUTCOME_ROW_SCHEMA,
    CompactEpisodeRecord,
    EpisodeArtifact,
    EpisodeArtifactWriter,
    EpisodeEvidenceCollector,
    EpisodeIssuance,
    StreamingEvidenceResult,
    StreamingStructuralReceipt,
    _artifact_identity_from_manifest_v2,
    _authenticated_slice_fingerprint,
    _sequence_digest,
    _structural_receipt_hash_from_manifest,
    iter_episode_records,
    iter_fixture_indexed_targets,
    iter_indexed_target_outcomes,
    load_episode_artifact,
    materialize_fixture_indexed_target,
    prepare_authenticated_target_plan,
    prepare_fixture_indexed_target_materialization,
    run_streaming_episode_artifact,
    write_episode_artifact,
)
from libs.models.sr_v2.research_lab.scientific_compiler import (
    ScientificGroupKey,
    ScientificObservation,
)
from libs.models.sr_v2.structural import SRStepResult

UTC_START = datetime(2024, 1, 1, tzinfo=UTC)


def _bar(timeframe: str, opened: datetime, duration: timedelta, index: int) -> SRBar:
    base = Decimal(100) + Decimal(index) / Decimal(100)
    return SRBar(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=base,
        high=base + Decimal(1),
        low=base - Decimal(1),
        close=base + Decimal(".2"),
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
    )


def _fixture() -> tuple[
    StreamingEvidenceResult,
    dict[str, tuple[SRBar, ...]],
    EpisodeIssuance,
    ResolvedTargetSpec,
    ScientificGroupKey,
]:
    issued_at = UTC_START + timedelta(hours=4)
    source = tuple(
        _bar("1h", UTC_START + timedelta(hours=index), timedelta(hours=1), index)
        for index in range(4)
    )
    future = tuple(
        _bar(
            "15m",
            issued_at + timedelta(minutes=15 * index),
            timedelta(minutes=15),
            index,
        )
        for index in range(8)
    )
    candidate = Candidate(
        candidate_key="candidate-1",
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        source_timeframe="1h",
        kernel_id="kernel",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=issued_at - timedelta(hours=1),
        available_at=issued_at,
        source_evidence_id="evidence-1",
        creation_atr=Decimal(1),
    )
    zone = lineage_from_candidate(candidate, config_fingerprint="c" * 64)
    null = build_feasible_random_price_null(
        zone,
        kernel_bars=source,
        active_zones=(),
        seed="fixture-seed",
    )
    group = ScientificGroupKey(
        asset="asset",
        timeframe="1h",
        kernel_id="kernel",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
    )
    episode = EpisodeIssuance(
        observation_id=zone.zone_id,
        group=group,
        zone=zone,
        issuance_cutoff=issued_at,
        source_close_index=3,
        source_close_identity=source[3].identity,
        first_subsequent_trigger_index=0,
        first_subsequent_trigger_identity=future[0].identity,
        feasible_null=null,
        cluster_identity=canonical_hash(
            {
                "issuance_cutoff": issued_at,
                "side": zone.side,
                "center": zone.center,
                "lower": zone.lower,
                "upper": zone.upper,
            }
        ),
    )
    records = {
        timeframe: tuple(
            SourceBarRecord(
                venue="venue",
                instrument_id="instrument",
                asset="asset",
                bar=bar,
                source_identity=bar.identity,
            )
            for bar in values
        )
        for timeframe, values in {"1h": source, "15m": future}.items()
    }
    bounds = tuple(
        (
            timeframe,
            values[0].bar.bar_open_at,
            values[-1].bar.bar_close_at,
        )
        for timeframe, values in records.items()
    )
    acquisition = tuple(
        (
            timeframe,
            "CACHE_ONLY",
            UTC_START,
            "d" * 64,
        )
        for timeframe in records
    )
    slice_fingerprint = _authenticated_slice_fingerprint(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=bounds,
        records_by_timeframe=records,
        acquisition_evidence=acquisition,
    )
    semantic = {
        "schema": EPISODE_EVIDENCE_SCHEMA,
        "source_manifest_id": "manifest",
        "source_sha256": "b" * 64,
        "source_slice_fingerprint": slice_fingerprint,
        "asset": "asset",
        "venue": "venue",
        "instrument_id": "instrument",
        "analysis_start": UTC_START,
        "knowledge_cutoff": issued_at + timedelta(hours=2),
        "config_fingerprint": "c" * 64,
        "steps": 1,
        "candidates": 1,
        "transitions": 1,
        "created_transitions": 1,
        "tombstone_pruned_transitions": 0,
        "semantic_stream_sha256": "f" * 64,
        "final_state_sha256": "e" * 64,
        "state_generation": 1,
        "serialized_state_bytes": 1,
        "peak_active_lineages": 1,
        "peak_terminal_tombstones": 0,
        "expected_groups": (group,),
        "present_groups": (group,),
        "issuance_digest_algorithm": "length_prefixed_canonical_sha256@1",
        "issuance_count": 1,
        "issuance_sha256": _sequence_digest(iter((episode.observation_id,))),
    }
    evidence = StreamingEvidenceResult(
        receipt=StreamingStructuralReceipt(
            **semantic,
            wall_duration_seconds=1.0,
            peak_rss_bytes=1,
            semantic_hash=canonical_hash(semantic),
        ),
        episodes=(episode,),
        source_records_by_timeframe=records,
        acquisition_evidence=acquisition,
        full_bounds=bounds,
    )
    spec = ResolvedTargetSpec(
        source_timeframe="1h",
        source_horizon_bars=2,
        reference_lookback=2,
        barrier_multiplier=Decimal("0.5"),
        observation_timeframe="15m",
        observation_duration=timedelta(minutes=15),
    )
    return evidence, {"1h": source, "15m": future}, episode, spec, group


def _authenticated_target_plan_fixture(tmp_path):
    evidence, _bars, episode, target_spec, group = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    records = evidence.source_records_by_timeframe
    source_slice = AuthenticatedSourceSlice(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=evidence.full_bounds,
        records_by_timeframe=records,
        record_identities=tuple(
            sorted(
                (timeframe, tuple(item.source_identity for item in values))
                for timeframe, values in records.items()
            )
        ),
        record_counts=tuple(
            sorted((timeframe, len(values)) for timeframe, values in records.items())
        ),
        acquisition_evidence=evidence.acquisition_evidence,
        slice_fingerprint=evidence.receipt.source_slice_fingerprint,
    )
    plan = prepare_authenticated_target_plan(
        artifact,
        source_slice=source_slice,
        target_choices=(
            (
                _target_choice_id_for_tuple(
                    TargetTuple(
                        source_horizon_bars=target_spec.source_horizon_bars,
                        reference_lookback=target_spec.reference_lookback,
                        barrier_multiplier=target_spec.barrier_multiplier,
                    )
                ),
                {"1h": target_spec},
            ),
        ),
    )
    return plan, source_slice, target_spec, episode, group


def test_authenticated_target_plan_emits_field_exact_actual_and_null_rows(tmp_path):
    plan, _source_slice, target_spec, episode, group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    choice_id = plan.target_specs[0][0]
    rows = tuple(iter_indexed_target_outcomes(plan, target_choice_id=choice_id))
    assert len(rows) == 1
    row = rows[0]
    expected_actual = label_scientific_target(
        episode.zone,
        issued_at=episode.issuance_cutoff,
        future_bars=plan.bars_by_timeframe[plan.observation_timeframe],
        target_spec=target_spec,
        reference_bars=plan.bars_by_timeframe["1h"][1:],
    )
    assert row.group == group
    assert row.observation_id == episode.observation_id
    assert row.actual.to_mapping() == {
        "complete": expected_actual.complete,
        "touch": expected_actual.view.touch,
        "reaction": (
            None
            if expected_actual.view.reaction is None
            else expected_actual.view.reaction.value
        ),
        "reaction_eligible": expected_actual.view.reaction_eligible,
        "censored": expected_actual.view.censored,
        "ambiguous": expected_actual.view.ambiguous,
        "touch_at": expected_actual.view.touch_at,
        "reaction_at": expected_actual.view.reaction_at,
        "observation_end_at": expected_actual.observation_end_at,
        "last_observed_cutoff": expected_actual.last_observed_cutoff,
        "outcome": expected_actual.event_observation.outcome.value,
        "favorable_excursion_atr": expected_actual.event_observation.favorable_excursion_atr,
        "adverse_excursion_atr": expected_actual.event_observation.adverse_excursion_atr,
    }
    assert row.null_available is True
    assert row.null is not None
    assert row.null_fingerprint == canonical_hash(episode.feasible_null.provenance)

    fixture_materialization = prepare_fixture_indexed_target_materialization(
        _fixture()[0],
        target_specs=(
            (
                "fixture-choice",
                {"1h": target_spec},
            ),
        ),
        bars_by_timeframe=_fixture()[1],
    )
    fixture_observation = materialize_fixture_indexed_target(
        fixture_materialization,
        tuple_id="fixture-choice",
    ).compiled.observations[0]
    assert (
        row.actual.to_mapping()
        == episode_evidence._target_outcome_from_result(
            fixture_observation.target
        ).to_mapping()
    )
    assert (
        row.null.to_mapping()
        == episode_evidence._target_outcome_from_result(
            fixture_observation.null_target
        ).to_mapping()
    )


def test_incomplete_feasible_null_preserves_opaque_identity_and_availability(
    tmp_path, monkeypatch
):
    plan, _source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    row = next(iter_episode_records(plan.artifact))
    incomplete_null = replace(
        row.feasible_null,
        complete=False,
        reason="fixture null unavailable",
        zone=None,
    )
    monkeypatch.setattr(
        episode_evidence,
        "_iter_validated_artifact_rows",
        lambda _artifact: iter((replace(row, feasible_null=incomplete_null),)),
    )
    outcome = next(
        iter_indexed_target_outcomes(
            plan,
            target_choice_id=plan.target_specs[0][0],
        )
    )
    assert outcome.null_available is False
    assert outcome.null is None
    assert outcome.null_fingerprint == row.feasible_null.null_fingerprint


def test_target_outcome_row_schema_is_a_fingerprint_authority(tmp_path, monkeypatch):
    plan, _source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    row = next(
        iter_indexed_target_outcomes(plan, target_choice_id=plan.target_specs[0][0])
    )
    assert row.to_mapping()["schema"] == TARGET_OUTCOME_ROW_SCHEMA
    original = row.fingerprint
    monkeypatch.setattr(
        episode_evidence,
        "TARGET_OUTCOME_ROW_SCHEMA",
        "sr_v2.target_outcome_row@test-schema",
    )
    assert row.to_mapping()["schema"] != TARGET_OUTCOME_ROW_SCHEMA
    assert row.fingerprint != original


def test_authenticated_target_plan_rejects_descriptive_choice_id(tmp_path):
    plan, source_slice, target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    with pytest.raises(ValueError, match="target choice ID"):
        prepare_authenticated_target_plan(
            plan.artifact,
            source_slice=source_slice,
            target_choices=(("choice-a", {"1h": target_spec}),),
        )


def test_authenticated_target_plan_reauthenticates_disk_manifest(tmp_path):
    plan, source_slice, target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    manifest_path = plan.artifact.directory / "manifest.json"
    original = manifest_path.read_bytes()
    manifest_path.write_bytes(
        original.replace(b'"code_policy_id":"policy"', b'"code_policy_id":"forged"')
    )
    with pytest.raises(ValueError, match="manifest|stale|identity"):
        prepare_authenticated_target_plan(
            plan.artifact,
            source_slice=source_slice,
            target_choices=((plan.target_specs[0][0], {"1h": target_spec}),),
        )


def test_authenticated_target_plan_common_risk_is_shared_and_fingerprinted(tmp_path):
    plan, source_slice, target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    shallow = replace(
        target_spec,
        reference_lookback=4,
    )
    shallow_plan = prepare_authenticated_target_plan(
        plan.artifact,
        source_slice=source_slice,
        target_choices=((plan.target_specs[0][0], {"1h": shallow}),),
    )
    assert plan.common_risk_receipt.schema == COMMON_RISK_RECEIPT_SCHEMA
    assert plan.common_risk_receipt.included_count == 1
    assert shallow_plan.common_risk_receipt.included_count == 0
    assert shallow_plan.common_risk_receipt.excluded_count == 1
    assert shallow_plan.common_risk_receipt.excluded_reason_counts == (
        ("insufficient_source_history", 1),
    )
    assert (
        tuple(
            iter_indexed_target_outcomes(
                shallow_plan, target_choice_id=plan.target_specs[0][0]
            )
        )
        == ()
    )
    assert (
        plan.common_risk_receipt.receipt_fingerprint
        == prepare_authenticated_target_plan(
            plan.artifact,
            source_slice=source_slice,
            target_choices=((plan.target_specs[0][0], {"1h": target_spec}),),
        ).common_risk_receipt.receipt_fingerprint
    )
    repeated = prepare_authenticated_target_plan(
        plan.artifact,
        source_slice=source_slice,
        target_choices=((plan.target_specs[0][0], {"1h": target_spec}),),
    )
    assert plan.compiler_receipts == repeated.compiler_receipts
    assert tuple(
        iter_indexed_target_outcomes(plan, target_choice_id=plan.target_specs[0][0])
    ) == tuple(
        iter_indexed_target_outcomes(repeated, target_choice_id=plan.target_specs[0][0])
    )


def test_real_and_fixture_common_risk_reason_counts_match(tmp_path):
    evidence, bars, _episode, target_spec, _group = _fixture()
    plan, source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    cases = (
        (
            replace(target_spec, reference_lookback=4),
            "insufficient_source_history",
        ),
        (
            replace(target_spec, source_horizon_bars=3),
            "right_edge_horizon",
        ),
    )
    for spec, reason in cases:
        target_tuple = TargetTuple(
            source_horizon_bars=spec.source_horizon_bars,
            reference_lookback=spec.reference_lookback,
            barrier_multiplier=spec.barrier_multiplier,
        )
        choice_id = _target_choice_id_for_tuple(target_tuple)
        real_plan = prepare_authenticated_target_plan(
            plan.artifact,
            source_slice=source_slice,
            target_choices=((choice_id, {"1h": spec}),),
        )
        fixture_plan = prepare_fixture_indexed_target_materialization(
            evidence,
            target_specs=(("fixture-choice", {"1h": spec}),),
            bars_by_timeframe=bars,
        )
        assert real_plan.common_risk_receipt.included_count == len(
            fixture_plan.risk_observation_ids
        )
        assert real_plan.common_risk_receipt.excluded_count == len(
            fixture_plan.excluded_observation_ids
        )
        assert dict(real_plan.common_risk_receipt.excluded_reason_counts) == dict(
            Counter(reason_value for _, reason_value in fixture_plan.excluded_reasons)
        )
        assert dict(real_plan.common_risk_receipt.excluded_reason_counts) == {reason: 1}


def test_common_risk_receipt_rejects_unknown_materialization_policy(tmp_path):
    plan, _source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    common = plan.common_risk_receipt
    semantic = dict(common.semantic_mapping())
    semantic["materialization_policy_id"] = "unapproved-policy"
    with pytest.raises(ValueError, match="materialization policy"):
        replace(
            common,
            materialization_policy_id="unapproved-policy",
            receipt_fingerprint=canonical_hash(semantic),
        )


def test_authenticated_target_plan_is_digest_only_and_real_path_skips_legacy_sets(
    tmp_path, monkeypatch
):
    plan, source_slice, target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    assert not hasattr(plan, "episodes")
    assert not hasattr(plan, "risk_observation_ids")
    monkeypatch.setattr(
        episode_evidence,
        "ScientificObservation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy path")),
    )
    fresh = prepare_authenticated_target_plan(
        plan.artifact,
        source_slice=source_slice,
        target_choices=((plan.target_specs[0][0], {"1h": target_spec}),),
    )
    assert (
        len(
            tuple(
                iter_indexed_target_outcomes(
                    fresh, target_choice_id=plan.target_specs[0][0]
                )
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("source_close_identity", "source close"),
        ("first_subsequent_trigger_identity", "trigger"),
    ],
)
def test_authenticated_target_plan_rejects_index_identity_contradictions(
    tmp_path, field, message
):
    plan, _source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    row = next(iter_episode_records(plan.artifact))
    forged = replace(row, **{field: "forged-identity"})
    with pytest.raises(ValueError, match=message):
        episode_evidence._target_row_source_checks(
            forged,
            plan=plan,
            specs=plan.specs_for(plan.target_specs[0][0]),
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("source_close_identity", "source close"),
        ("first_subsequent_trigger_identity", "trigger"),
    ],
)
def test_authenticated_target_outcome_api_rejects_index_identity_contradictions(
    tmp_path, monkeypatch, field, message
):
    plan, _source_slice, _target_spec, _episode, _group = (
        _authenticated_target_plan_fixture(tmp_path)
    )
    row = next(iter_episode_records(plan.artifact))
    forged = replace(row, **{field: "forged-identity"})
    monkeypatch.setattr(
        episode_evidence,
        "_iter_validated_artifact_rows",
        lambda _artifact: iter((forged,)),
    )
    with pytest.raises(ValueError, match=message):
        tuple(
            iter_indexed_target_outcomes(plan, target_choice_id=plan.target_specs[0][0])
        )


def _authenticated_two_cutoff_run_fixture(config):
    """Build a tiny authenticated source slice and two synthetic run steps."""

    first_cutoff = UTC_START + timedelta(hours=15)
    second_cutoff = UTC_START + timedelta(hours=16)
    records = {}
    bounds = []
    for index, timeframe in enumerate(config.ladder):
        grid = grid_for(timeframe)
        if timeframe == "1h":
            bars = tuple(
                _bar(
                    timeframe,
                    UTC_START + timedelta(hours=bar_index),
                    grid.duration,
                    bar_index,
                )
                for bar_index in range(16)
            )
        elif timeframe == config.trigger_timeframe:
            bars = tuple(
                _bar(
                    timeframe,
                    first_cutoff + grid.duration * bar_index,
                    grid.duration,
                    bar_index,
                )
                for bar_index in range(5)
            )
        else:
            end = grid.expected_closed_cutoff(second_cutoff)
            bars = (_bar(timeframe, end - grid.duration, grid.duration, index),)
        records[timeframe] = tuple(
            SourceBarRecord(
                venue="venue",
                instrument_id="instrument",
                asset="asset",
                bar=bar,
                source_identity=bar.identity,
            )
            for bar in bars
        )
        bounds.append((timeframe, bars[0].bar_open_at, bars[-1].bar_close_at))
    acquisition = tuple(
        (timeframe, "CACHE_ONLY", UTC_START, "d" * 64) for timeframe in records
    )
    source_fingerprint = _authenticated_slice_fingerprint(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=tuple(bounds),
        records_by_timeframe=records,
        acquisition_evidence=acquisition,
    )
    source_slice = AuthenticatedSourceSlice(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=tuple(bounds),
        records_by_timeframe=records,
        record_identities=tuple(
            sorted(
                (timeframe, tuple(item.source_identity for item in values))
                for timeframe, values in records.items()
            )
        ),
        record_counts=tuple(
            sorted((timeframe, len(values)) for timeframe, values in records.items())
        ),
        acquisition_evidence=acquisition,
        slice_fingerprint=source_fingerprint,
    )

    def state_for(cutoff, zone, generation):
        source_cutoffs = {}
        source_sequences = {}
        for timeframe, values in records.items():
            source_sequences[timeframe] = tuple(item.source_identity for item in values)
            eligible = [
                item.bar.bar_close_at
                for item in values
                if item.bar.bar_close_at <= cutoff
            ]
            source_cutoffs[timeframe] = max(
                eligible, default=values[0].bar.bar_close_at
            )
        source_fingerprints = {
            timeframe: fingerprint_sequence_hash(values)
            for timeframe, values in source_sequences.items()
        }
        return SRState(
            config_fingerprint=config.config_fingerprint,
            generation=generation,
            last_trigger_at=cutoff,
            venue="venue",
            instrument_id="instrument",
            asset="asset",
            source_cutoffs=source_cutoffs,
            source_fingerprints=source_fingerprints,
            source_fingerprint_sequences=source_sequences,
            terminal_tombstones=(
                ZoneRecord(lineage=zone, lifecycle=LifecycleState.BROKEN),
            ),
        )

    steps = []
    states = []
    for step_index, cutoff in enumerate((first_cutoff, second_cutoff), 1):
        source_bar = next(
            item.bar for item in records["1h"] if item.bar.bar_close_at == cutoff
        )
        candidate = Candidate(
            candidate_key=f"fixture-{cutoff.isoformat()}",
            venue="venue",
            instrument_id="instrument",
            asset="asset",
            source_timeframe="1h",
            kernel_id="previous_period_anchor",
            kernel_version="1",
            side=ZoneSide.SUPPORT,
            center=source_bar.low,
            lower=source_bar.low - Decimal(1),
            upper=source_bar.low + Decimal(1),
            formed_at=cutoff,
            available_at=cutoff,
            source_evidence_id=source_bar.identity,
            creation_atr=Decimal(1),
        )
        zone = lineage_from_candidate(
            candidate, config_fingerprint=config.config_fingerprint
        )
        state = state_for(cutoff, zone, step_index)
        states.append(state)
        step = object.__new__(SRStepResult)
        for name, value in {
            "asset": "asset",
            "config_fingerprint": config.config_fingerprint,
            "market_as_of": cutoff,
            "candidates_by_timeframe": {},
            "transitions": (
                SimpleNamespace(
                    transition_type=TransitionType.CREATED,
                    zone_id=zone.zone_id,
                    transition_id=f"transition-{step_index}",
                ),
            ),
            "state": state,
            "source_cutoffs": {},
            "source_fingerprints": {},
            "lineage_registry": {
                zone.zone_id: ZoneRecord(
                    lineage=zone,
                    lifecycle=LifecycleState.BROKEN,
                )
            },
        }.items():
            object.__setattr__(step, name, value)
        steps.append(step)
    return source_slice, tuple(steps), tuple(states)


def test_indexed_label_matches_sequence_authority_without_future_copy():
    evidence, bars, episode, spec, _ = _fixture()
    reference = bars["1h"][1:]
    sequence = label_scientific_target(
        episode.zone,
        issued_at=episode.issuance_cutoff,
        future_bars=bars["15m"],
        target_spec=spec,
        reference_bars=reference,
    )
    indexed = label_scientific_target_indexed(
        episode.zone,
        issued_at=episode.issuance_cutoff,
        future_bars=bars["15m"],
        future_start_index=0,
        future_end_index=len(bars["15m"]),
        target_spec=spec,
        reference_bars=reference,
    )
    assert indexed == sequence
    plan = prepare_fixture_indexed_target_materialization(
        evidence,
        target_specs=(("tuple-a", {"1h": spec}), ("tuple-b", {"1h": spec})),
        bars_by_timeframe=bars,
    )
    assert not hasattr(plan, "compiled_by_tuple")
    assert not hasattr(plan, "tuples")
    result = materialize_fixture_indexed_target(plan, tuple_id="tuple-a")
    assert tuple(item.observation_id for item in result.compiled.observations) == (
        episode.observation_id,
    )
    assert [
        item.tuple_id
        for item in iter_fixture_indexed_targets(
            evidence,
            target_specs=(("tuple-a", {"1h": spec}), ("tuple-b", {"1h": spec})),
            bars_by_timeframe=bars,
        )
    ] == ["tuple-a", "tuple-b"]


def test_indexed_materialization_builds_one_lookup_without_linear_scans(monkeypatch):
    evidence, bars, _, spec, _ = _fixture()
    plan = prepare_fixture_indexed_target_materialization(
        evidence,
        target_specs=(("tuple-a", {"1h": spec}),),
        bars_by_timeframe=bars,
    )
    calls = 0
    original_lookup = episode_evidence._episode_index_lookup

    def counted_lookup(materialization):
        nonlocal calls
        calls += 1
        return original_lookup(materialization)

    monkeypatch.setattr(episode_evidence, "_episode_index_lookup", counted_lookup)
    result = materialize_fixture_indexed_target(plan, tuple_id="tuple-a")
    assert calls == 1
    assert not hasattr(plan, "index_for")
    assert len(result.compiled.observations) == len(plan.risk_observation_ids)


def test_on_step_reuses_one_committed_record_lookup_for_created_transitions(
    monkeypatch,
):
    collector = object.__new__(EpisodeEvidenceCollector)
    collector.asset = "asset"
    collector.analysis_start = UTC_START
    collector.config = SimpleNamespace(config_fingerprint="config")
    collector._stream = hashlib.sha256()
    collector.steps = 0
    collector.candidates = 0
    collector.transitions = 0
    collector.created_transitions = 0
    collector.tombstone_pruned_transitions = 0
    collector.peak_active_lineages = 0
    collector.peak_terminal_tombstones = 0

    committed = tuple(
        SimpleNamespace(lineage=SimpleNamespace(zone_id=zone_id))
        for zone_id in ("zone-a", "zone-b")
    )
    state = SimpleNamespace(
        generation=1,
        last_trigger_at=UTC_START,
        source_cutoffs={},
        source_fingerprints={},
        active_lineages=committed,
        terminal_tombstones=(),
    )
    transitions = tuple(
        SimpleNamespace(
            transition_type=TransitionType.CREATED,
            zone_id=zone_id,
            transition_id=f"transition-{zone_id}",
        )
        for zone_id in ("zone-a", "zone-b")
    )
    result = object.__new__(SRStepResult)
    object.__setattr__(result, "asset", "asset")
    object.__setattr__(result, "config_fingerprint", "config")
    object.__setattr__(result, "market_as_of", UTC_START)
    object.__setattr__(result, "candidates_by_timeframe", {})
    object.__setattr__(result, "transitions", transitions)
    object.__setattr__(result, "state", state)
    object.__setattr__(result, "source_cutoffs", {})
    object.__setattr__(result, "source_fingerprints", {})
    object.__setattr__(result, "lineage_registry", {})

    lookup_calls = 0
    original_lookup = EpisodeEvidenceCollector._committed_records

    def counted_lookup(step_result):
        nonlocal lookup_calls
        lookup_calls += 1
        return original_lookup(step_result)

    received = []

    def capture_created(self, transition, step_result, *, committed_records=None):
        received.append(committed_records)

    monkeypatch.setattr(
        EpisodeEvidenceCollector,
        "_committed_records",
        staticmethod(counted_lookup),
    )
    monkeypatch.setattr(EpisodeEvidenceCollector, "_record_created", capture_created)
    collector.on_step(result)

    assert lookup_calls == 1
    assert len(received) == 2
    assert received[0] is received[1]
    assert set(received[0]) == {"zone-a", "zone-b"}


def test_indexed_materialization_excludes_common_insufficient_history_once():
    evidence, bars, episode, spec, _ = _fixture()
    shallow_spec = ResolvedTargetSpec(
        source_timeframe=spec.source_timeframe,
        source_horizon_bars=spec.source_horizon_bars,
        reference_lookback=4,
        barrier_multiplier=spec.barrier_multiplier,
        observation_timeframe=spec.observation_timeframe,
        observation_duration=spec.observation_duration,
    )
    plan = prepare_fixture_indexed_target_materialization(
        evidence,
        target_specs=(
            ("tuple-a", {"1h": shallow_spec}),
            ("tuple-b", {"1h": shallow_spec}),
        ),
        bars_by_timeframe=bars,
    )
    assert plan.risk_observation_ids == ()
    assert plan.excluded_observation_ids == (episode.observation_id,)
    assert plan.excluded_reasons == (
        (episode.observation_id, "insufficient_source_history"),
    )
    assert plan.risk_set_fingerprint != canonical_hash(
        {
            "risk_observation_ids": (),
            "excluded_observation_ids": (episode.observation_id,),
            "excluded_reasons": ((episode.observation_id, "other"),),
            "target_family_fingerprint": plan.target_family_fingerprint,
        }
    )


def test_indexed_materialization_rejects_stale_trigger_identity():
    evidence, bars, episode, spec, _ = _fixture()
    stale = EpisodeIssuance(
        observation_id=episode.observation_id,
        group=episode.group,
        zone=episode.zone,
        issuance_cutoff=episode.issuance_cutoff,
        source_close_index=episode.source_close_index,
        source_close_identity=episode.source_close_identity,
        first_subsequent_trigger_index=episode.first_subsequent_trigger_index,
        first_subsequent_trigger_identity="not-authenticated",
        feasible_null=episode.feasible_null,
        cluster_identity=episode.cluster_identity,
    )
    stale_evidence = replace(evidence, episodes=(stale,))
    with pytest.raises(ValueError, match="trigger identity"):
        prepare_fixture_indexed_target_materialization(
            stale_evidence,
            target_specs=(("tuple-a", {"1h": spec}),),
            bars_by_timeframe=bars,
        )


def test_committed_same_step_supersede_is_not_an_issuance():
    issued_at = UTC_START + timedelta(hours=4)
    candidate = Candidate(
        candidate_key="superseded",
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        source_timeframe="1h",
        kernel_id="kernel",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=issued_at - timedelta(hours=1),
        available_at=issued_at,
        source_evidence_id="superseded-evidence",
        creation_atr=Decimal(1),
    )
    zone = lineage_from_candidate(candidate, config_fingerprint="config")
    collector = object.__new__(EpisodeEvidenceCollector)
    collector.analysis_start = issued_at
    collector._episodes = []
    collector._episode_ids = set()
    collector._cluster_counts = {}
    result = SimpleNamespace(
        market_as_of=issued_at,
        state=SimpleNamespace(
            active_lineages=(),
            terminal_tombstones=(
                ZoneRecord(lineage=zone, lifecycle=LifecycleState.SUPERSEDED),
            ),
        ),
    )
    collector._record_created(SimpleNamespace(zone_id=zone.zone_id), result)
    assert collector._episodes == []


def test_invalid_stream_reason_changes_report_identity():
    target_tuple = TargetTuple(
        source_horizon_bars=1,
        reference_lookback=1,
        barrier_multiplier=Decimal("0.5"),
    )
    diagnostic = TargetTupleDiagnostic(
        target_tuple=target_tuple,
        status=TargetTupleStatus.INVALID,
        groups=(),
        reason="invalid fixture",
        tuple_fingerprint="a" * 64,
    )
    duplicate = _target_report(
        (diagnostic,),
        input_invalid=True,
        identity_invalid=True,
        invalid_reasons=("duplicate target tuple",),
    )
    unexpected = _target_report(
        (diagnostic,),
        input_invalid=True,
        identity_invalid=True,
        invalid_reasons=("unexpected target tuple",),
    )
    assert duplicate.status is unexpected.status
    assert duplicate.report_fingerprint != unexpected.report_fingerprint


def test_streaming_optimizer_report_matches_strict_without_retaining_panel(
    tmp_path,
):
    from tests.models.sr_v2.test_optimizer import (
        _empty_compiled,
        _raw,
        _real_stream_payload,
    )

    config = resolve_optimizer_config(_raw(tmp_path))
    compiled = {
        target_tuple: _empty_compiled(config)
        for target_tuple in config.target_identification.tuples
    }
    strict = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple=compiled,
            source_manifest_id="manifest",
            source_sha256="source",
        ),
    )
    fixture_stream = tuple(
        (target_tuple, compiled[target_tuple])
        for target_tuple in config.target_identification.tuples
    )
    assert (
        identify_target_from_compiled_fixture(
            config,
            FixtureTargetIdentificationInput(
                compiled_by_tuple=dict(fixture_stream),
                source_manifest_id="manifest",
                source_sha256="source",
            ),
        )
        == strict
    )
    target_tuple = config.target_identification.tuples[0]
    choice_id, common_risk, compiler_receipt = _real_stream_payload(
        config,
        target_tuple,
        (),
    )
    streaming = identify_target_streaming(
        config,
        {
            "BTCUSDT": (
                common_risk,
                {choice_id: (compiler_receipt, iter(()))},
            )
        },
    )
    assert streaming.status is strict.status
    assert streaming.selected_tuple == strict.selected_tuple
    assert len(streaming.tuple_diagnostics) == len(strict.tuple_diagnostics)
    for streaming_tuple, strict_tuple in zip(
        streaming.tuple_diagnostics,
        strict.tuple_diagnostics,
        strict=True,
    ):
        assert streaming_tuple.target_tuple == strict_tuple.target_tuple
        assert streaming_tuple.status is strict_tuple.status
        assert streaming_tuple.reason == strict_tuple.reason
        assert len(streaming_tuple.groups) == len(strict_tuple.groups)
        scalar_fields = (
            "observation_count",
            "actual_available_count",
            "null_available_count",
            "uncensored_count",
            "touched_count",
            "untouched_count",
            "censored_count",
            "unresolved_count",
            "bounce_count",
            "break_count",
            "null_bounce_count",
            "null_break_count",
            "null_unresolved_count",
            "actual_censoring_rate",
            "null_censoring_rate",
            "actual_unresolved_reaction_rate",
            "null_unresolved_reaction_rate",
            "actual_ambiguity_rate",
            "null_ambiguity_rate",
            "null_unavailable_rate",
        )
        for streaming_group, strict_group in zip(
            streaming_tuple.groups,
            strict_tuple.groups,
            strict=True,
        ):
            assert streaming_group.group == strict_group.group
            for field in scalar_fields:
                assert getattr(streaming_group, field) == pytest.approx(
                    getattr(strict_group, field)
                )


def test_streaming_optimizer_nonempty_multi_group_matches_fixture_evaluator(
    tmp_path,
):
    """The one-pass row accumulator agrees with the fixture evaluator."""

    from libs.models.sr_v2.research.optimizer import (
        _target_spec_for,
    )
    from tests.models.sr_v2.test_optimizer import (
        _groups,
        _NoMissingCompiledSet,
        _raw,
        _real_stream_payload,
    )

    _evidence, bars, _episode, _fixture_spec, _fixture_group = _fixture()
    config = resolve_optimizer_config(_raw(tmp_path))
    target_tuple = config.target_identification.tuples[0]
    target_spec = _target_spec_for(config, target_tuple, "1h")
    expected_groups = _groups(config)
    groups_by_side = {
        group.side: group
        for group in expected_groups
        if group.timeframe == "1h" and group.kernel_id == "previous_period_anchor"
    }
    issued_at = UTC_START + timedelta(hours=4)
    reference_bars = bars["1h"][1:]
    future_bars = bars["15m"]

    def with_outcome(result, reaction):
        if reaction is None:
            view = TwoStageTargetView(
                touch=False,
                reaction=None,
                reaction_eligible=False,
                censored=False,
                ambiguous=False,
                touch_at=None,
                reaction_at=None,
            )
            event = replace(
                result.event_observation,
                complete=True,
                outcome=ForecastOutcome.NO_TOUCH,
                touch_at=None,
                censored=False,
                ambiguous=False,
                favorable_excursion_atr=Decimal(0),
                adverse_excursion_atr=Decimal(0),
                last_observed_cutoff=result.observation_end_at,
            )
        else:
            touch_at = issued_at + timedelta(minutes=15)
            reaction_at = issued_at + timedelta(minutes=30)
            view = TwoStageTargetView(
                touch=True,
                reaction=reaction,
                reaction_eligible=True,
                censored=False,
                ambiguous=False,
                touch_at=touch_at,
                reaction_at=reaction_at,
            )
            event = replace(
                result.event_observation,
                complete=True,
                outcome=(
                    ForecastOutcome.TOUCH_THEN_BOUNCE
                    if reaction is ScientificReaction.BOUNCE
                    else ForecastOutcome.TOUCH_THEN_BREAK
                ),
                touch_at=touch_at,
                censored=False,
                ambiguous=False,
                favorable_excursion_atr=Decimal("0.5"),
                adverse_excursion_atr=Decimal(0),
                last_observed_cutoff=result.observation_end_at,
            )
        return replace(
            result,
            complete=True,
            last_observed_cutoff=result.observation_end_at,
            view=view,
            event_observation=event,
        )

    observations = []
    rows = []
    outcomes = (
        (ZoneSide.SUPPORT, ScientificReaction.BOUNCE),
        (ZoneSide.RESISTANCE, ScientificReaction.BREAK),
        (ZoneSide.SUPPORT, None),
    )
    for index, (side, reaction) in enumerate(outcomes, 1):
        group = groups_by_side[side]
        candidate = Candidate(
            candidate_key=f"parity-candidate-{index}",
            venue="venue",
            instrument_id="instrument",
            asset="BTCUSDT",
            source_timeframe="1h",
            kernel_id=group.kernel_id,
            kernel_version=group.kernel_version,
            side=side,
            center=Decimal(100),
            lower=Decimal(99),
            upper=Decimal(101),
            formed_at=issued_at - timedelta(hours=1),
            available_at=issued_at,
            source_evidence_id=f"parity-evidence-{index}",
            creation_atr=Decimal(1),
        )
        zone = lineage_from_candidate(candidate, config_fingerprint="c" * 64)
        feasible_null = build_feasible_random_price_null(
            zone,
            kernel_bars=bars["1h"],
            active_zones=(),
            seed=f"parity-seed-{index}",
        )
        actual = with_outcome(
            label_scientific_target(
                zone,
                issued_at=issued_at,
                future_bars=future_bars,
                target_spec=target_spec,
                reference_bars=reference_bars,
            ),
            reaction,
        )
        null_target = None
        if feasible_null.zone is not None:
            null_target = with_outcome(
                label_scientific_target(
                    feasible_null.zone,
                    issued_at=issued_at,
                    future_bars=future_bars,
                    target_spec=target_spec,
                    reference_bars=reference_bars,
                ),
                reaction,
            )
        observation = ScientificObservation(
            observation_id=zone.zone_id,
            group=group,
            zone=zone,
            target=actual,
            feasible_null=feasible_null,
            null_target=null_target,
            source_manifest_id="manifest",
            source_sha256="b" * 64,
            target_fingerprint=scientific_target_fingerprint(target_spec),
            null_fingerprint=canonical_hash(feasible_null.provenance),
        )
        observations.append(observation)
        rows.append(
            episode_evidence.TargetOutcomeRow(
                observation_id=observation.observation_id,
                group=group,
                issuance_cutoff=issued_at,
                cluster_identity=canonical_hash(
                    {
                        "issued_at": issued_at,
                        "side": group.side,
                        "center": zone.center,
                        "lower": zone.lower,
                        "upper": zone.upper,
                    }
                ),
                target_fingerprint=scientific_target_fingerprint(target_spec),
                null_fingerprint=canonical_hash(feasible_null.provenance),
                null_available=feasible_null.complete
                and feasible_null.zone is not None
                and null_target is not None,
                actual=episode_evidence._target_outcome_from_result(actual),
                null=(
                    None
                    if null_target is None
                    else episode_evidence._target_outcome_from_result(null_target)
                ),
            )
        )

    compiled = _NoMissingCompiledSet(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        expected_groups=expected_groups,
        observations=tuple(observations),
        compiler_fingerprint="compiler",
        knowledge_cutoff=config.source.start,
    )
    strict = identify_target_from_compiled_fixture(
        config,
        FixtureTargetIdentificationInput(
            compiled_by_tuple={target_tuple: compiled},
            source_manifest_id="manifest",
            source_sha256="b" * 64,
        ),
    )
    choice_id, common_risk, compiler_receipt = _real_stream_payload(
        config, target_tuple, tuple(rows)
    )
    streaming = identify_target_streaming(
        config,
        {
            "BTCUSDT": (
                common_risk,
                {choice_id: (compiler_receipt, iter(rows))},
            )
        },
    )

    assert strict.status is streaming.status
    assert strict.selected_tuple == streaming.selected_tuple
    strict_diagnostic = strict.tuple_diagnostics[0]
    streaming_diagnostic = streaming.tuple_diagnostics[0]
    assert strict_diagnostic.status is streaming_diagnostic.status
    assert strict_diagnostic.reason == streaming_diagnostic.reason
    scalar_fields = (
        "observation_count",
        "actual_available_count",
        "null_available_count",
        "uncensored_count",
        "touched_count",
        "untouched_count",
        "censored_count",
        "unresolved_count",
        "actual_touch_count",
        "null_touch_count",
        "bounce_count",
        "break_count",
        "null_untouched_count",
        "null_censored_count",
        "null_unresolved_count",
        "null_bounce_count",
        "null_break_count",
        "null_censored_reaction_count",
        "null_ambiguous_reaction_count",
        "censored_reaction_count",
        "ambiguous_reaction_count",
        "observation_coverage",
        "null_unavailable_rate",
        "actual_censoring_rate",
        "null_censoring_rate",
        "actual_unresolved_reaction_rate",
        "null_unresolved_reaction_rate",
        "actual_ambiguity_rate",
        "null_ambiguity_rate",
    )
    strict_groups = {item.group: item for item in strict_diagnostic.groups}
    streaming_groups = {item.group: item for item in streaming_diagnostic.groups}
    assert set(strict_groups) == set(streaming_groups)
    for group, strict_group in strict_groups.items():
        streaming_group = streaming_groups[group]
        for field in scalar_fields:
            assert getattr(streaming_group, field) == pytest.approx(
                getattr(strict_group, field)
            )
        assert streaming_group.unique_issuance_cutoff_count == (
            len(strict_group.unique_issuance_cutoffs)
        )
        assert streaming_group.joint_utc_block_count == len(
            strict_group.joint_utc_blocks
        )


def test_artifact_writer_is_authenticated_streaming_and_resumable(tmp_path):
    _, bars, episode, _spec, group = _fixture()
    records = {
        timeframe: tuple(
            SourceBarRecord(
                venue="venue",
                instrument_id="instrument",
                asset="asset",
                bar=bar,
                source_identity=bar.identity,
            )
            for bar in values
        )
        for timeframe, values in bars.items()
    }
    bounds = tuple(
        (timeframe, values[0].bar.bar_open_at, values[-1].bar.bar_close_at)
        for timeframe, values in records.items()
    )
    acquisition = tuple(
        (timeframe, "CACHE_ONLY", UTC_START, "d" * 64) for timeframe in records
    )
    source_slice = _authenticated_slice_fingerprint(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=bounds,
        records_by_timeframe=records,
        acquisition_evidence=acquisition,
    )
    semantic = {
        "schema": EPISODE_EVIDENCE_SCHEMA,
        "source_manifest_id": "manifest",
        "source_sha256": "b" * 64,
        "source_slice_fingerprint": source_slice,
        "asset": "asset",
        "venue": "venue",
        "instrument_id": "instrument",
        "analysis_start": UTC_START,
        "knowledge_cutoff": UTC_START + timedelta(hours=6),
        "config_fingerprint": "c" * 64,
        "steps": 1,
        "candidates": 1,
        "transitions": 1,
        "created_transitions": 1,
        "tombstone_pruned_transitions": 0,
        "semantic_stream_sha256": "f" * 64,
        "final_state_sha256": "e" * 64,
        "state_generation": 1,
        "serialized_state_bytes": 1,
        "peak_active_lineages": 1,
        "peak_terminal_tombstones": 0,
        "expected_groups": (group,),
        "present_groups": (group,),
        "issuance_digest_algorithm": "length_prefixed_canonical_sha256@1",
        "issuance_count": 1,
        "issuance_sha256": _sequence_digest(iter((episode.observation_id,))),
    }
    from libs.models.sr_v2.research_lab.episode_evidence import (
        StreamingEvidenceResult,
        StreamingStructuralReceipt,
    )

    evidence = StreamingEvidenceResult(
        receipt=StreamingStructuralReceipt(
            **semantic,
            wall_duration_seconds=1.0,
            peak_rss_bytes=1,
            semantic_hash=canonical_hash(semantic),
        ),
        episodes=(episode,),
        source_records_by_timeframe=records,
        acquisition_evidence=acquisition,
        full_bounds=bounds,
    )
    first = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    second = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    assert first.artifact_id == second.artifact_id
    loaded = load_episode_artifact(first.directory)
    assert loaded.artifact_id == first.artifact_id
    assert not hasattr(loaded, "episodes")
    loaded_rows = tuple(iter_episode_records(loaded))
    assert len(loaded_rows) == 1
    assert loaded_rows[0].observation_id == episode.observation_id
    forged = EpisodeArtifact(
        artifact_id=loaded.artifact_id,
        directory=loaded.directory,
        manifest={**loaded.manifest, "asset": "forged"},
    )
    with pytest.raises(ValueError, match="stale or forged"):
        tuple(iter_episode_records(forged))
    episodes_path = first.directory / "episodes.jsonl"
    rows = [json.loads(line) for line in episodes_path.read_text().splitlines()]
    assert len(rows) == 1
    assert "future_bars" not in rows[0]
    assert "target" not in rows[0]
    manifest_path = first.directory / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_path.write_bytes(manifest_bytes + b"x")
    with pytest.raises(ValueError, match="manifest"):
        load_episode_artifact(first.directory)
    manifest_path.write_bytes(manifest_bytes)
    episodes_path.write_bytes(episodes_path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="episodes JSONL|SHA-256"):
        load_episode_artifact(first.directory)


def test_iter_episode_records_scans_jsonl_once(tmp_path, monkeypatch):
    evidence, _, _, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    calls = 0
    original = episode_evidence._iter_validated_artifact_rows

    def counted(handle):
        nonlocal calls
        calls += 1
        yield from original(handle)

    monkeypatch.setattr(episode_evidence, "_iter_validated_artifact_rows", counted)
    assert len(tuple(iter_episode_records(artifact))) == 1
    assert calls == 1


def test_compact_rows_preserve_null_receipt_and_manifest_is_deeply_immutable(tmp_path):
    evidence, _, episode, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    rows = tuple(iter_episode_records(artifact))
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, CompactEpisodeRecord)
    assert row.zone.zone_id == episode.zone.zone_id
    assert row.zone.center == episode.zone.center
    assert row.feasible_null.complete == episode.feasible_null.complete
    assert row.feasible_null.null_fingerprint == canonical_hash(
        episode.feasible_null.provenance
    )
    assert row.feasible_null.opportunity.sha256 == canonical_hash(
        tuple(episode.feasible_null.provenance["opportunity_bar_ids"])
    )
    persisted = json.loads((artifact.directory / "episodes.jsonl").read_text())
    assert "venue" not in persisted["zone"]
    assert "asset" not in persisted["zone"]
    assert "source_manifest_id" not in persisted
    with pytest.raises(TypeError):
        artifact.manifest["expected_groups"][0]["asset"] = "changed"


def test_compact_writer_rejects_same_cutoff_duplicate_identity():
    _evidence, _, episode, _, _ = _fixture()
    writer = object.__new__(EpisodeArtifactWriter)
    writer._finished = False
    writer._current_cutoff = episode.issuance_cutoff
    writer._current_ids = {episode.observation_id}
    writer._current_rows = []
    writer.baseline_config_fingerprint = "c" * 64
    with pytest.raises(ValueError, match="duplicate"):
        writer._accept_episode(episode)


def test_compact_writer_rejects_actual_null_cross_row_collision():
    evidence, _, episode, _, _ = _fixture()
    null_zone = episode.feasible_null.zone
    assert null_zone is not None
    kernel_bars = tuple(item.bar for item in evidence.source_records_by_timeframe["1h"])
    second_null = build_feasible_random_price_null(
        null_zone,
        kernel_bars=kernel_bars,
        active_zones=(),
        seed="fixture-seed",
    )
    second = replace(
        episode,
        observation_id=null_zone.zone_id,
        zone=null_zone,
        feasible_null=second_null,
        cluster_identity=canonical_hash(
            {
                "issuance_cutoff": episode.issuance_cutoff,
                "side": null_zone.side,
                "center": null_zone.center,
                "lower": null_zone.lower,
                "upper": null_zone.upper,
            }
        ),
    )
    writer = object.__new__(EpisodeArtifactWriter)
    writer._finished = False
    writer._current_cutoff = episode.issuance_cutoff
    writer._current_ids = {episode.observation_id, null_zone.zone_id}
    writer._current_rows = []
    writer.baseline_config_fingerprint = "c" * 64
    with pytest.raises(ValueError, match="duplicate|collision"):
        writer._accept_episode(second)


def test_loader_rejects_legacy_artifact_schema(tmp_path):
    evidence, _, _, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    manifest_path = artifact.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema"] = "sr_v2.episode_artifact@1"
    manifest_path.write_text(canonical_json(manifest) + "\n")
    with pytest.raises(ValueError, match="manifest"):
        load_episode_artifact(artifact.directory)


def test_loader_rejects_partial_and_symlink_artifacts(tmp_path):
    evidence, _, _, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path / "source",
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "manifest.json").write_bytes(
        (artifact.directory / "manifest.json").read_bytes()
    )
    with pytest.raises(ValueError, match="partial|symlinked"):
        load_episode_artifact(partial)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(artifact.directory, target_is_directory=True)
    with pytest.raises(ValueError, match="regular|symlink"):
        load_episode_artifact(symlink)


def test_loader_rejects_resealed_same_cutoff_duplicate_row(tmp_path):
    evidence, _, episode, _, group = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    episodes_path = artifact.directory / "episodes.jsonl"
    original_rows = episodes_path.read_bytes()
    resealed_rows = original_rows + original_rows
    episodes_path.write_bytes(resealed_rows)

    manifest_path = artifact.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = json.loads(original_rows)
    manifest.update(
        {
            "episode_sha256": hashlib.sha256(resealed_rows).hexdigest(),
            "episode_bytes": len(resealed_rows),
            "episode_count": 2,
            "issuance_count": 2,
            "issuance_sha256": _sequence_digest(
                iter((episode.observation_id, episode.observation_id))
            ),
            "group_counts": [[group.key, 2]],
            "cluster_count": 1,
        }
    )
    cluster_payload = (
        row["issuance_cutoff"],
        [[row["cluster_identity"], 2]],
    )
    cluster_bytes = canonical_json(cluster_payload).encode("utf-8")
    cluster_digest = hashlib.sha256()
    cluster_digest.update(len(cluster_bytes).to_bytes(8, "big"))
    cluster_digest.update(cluster_bytes)
    manifest["cluster_multiplicity_sha256"] = cluster_digest.hexdigest()
    manifest["structural_receipt_hash"] = _structural_receipt_hash_from_manifest(
        manifest
    )
    manifest["artifact_id"] = canonical_hash(
        _artifact_identity_from_manifest_v2(manifest)
    )
    manifest_path.write_text(canonical_json(manifest) + "\n")
    resealed_directory = artifact.directory.parent / manifest["artifact_id"]
    artifact.directory.rename(resealed_directory)
    with pytest.raises(ValueError, match="duplicate|canonical order"):
        load_episode_artifact(resealed_directory)


def _reseal_compact_artifact(artifact, *, row=None, manifest_updates=None):
    """Re-address a fixture artifact so loader checks reach the tampered field."""

    episodes_path = artifact.directory / "episodes.jsonl"
    rows = [json.loads(line) for line in episodes_path.read_text().splitlines()]
    if row is not None:
        rows[0] = row
    rows_bytes = b"".join(
        (canonical_json(value) + "\n").encode("utf-8") for value in rows
    )
    episodes_path.write_bytes(rows_bytes)
    manifest_path = artifact.directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(
        {
            "episode_sha256": hashlib.sha256(rows_bytes).hexdigest(),
            "episode_bytes": len(rows_bytes),
            "episode_count": len(rows),
        }
    )
    if rows:
        issuance_values = tuple(value["observation_id"] for value in rows)
        manifest["issuance_count"] = len(rows)
        manifest["issuance_sha256"] = _sequence_digest(iter(issuance_values))
        cluster_digest = hashlib.sha256()
        current_cutoff = None
        current_clusters = Counter()
        for value in rows:
            cutoff = value["issuance_cutoff"]
            if current_cutoff is not None and cutoff != current_cutoff:
                payload = (current_cutoff, tuple(sorted(current_clusters.items())))
                encoded = canonical_json(payload).encode("utf-8")
                cluster_digest.update(len(encoded).to_bytes(8, "big"))
                cluster_digest.update(encoded)
                current_clusters = Counter()
            current_cutoff = cutoff
            current_clusters[value["cluster_identity"]] += 1
        if current_cutoff is not None:
            payload = (current_cutoff, tuple(sorted(current_clusters.items())))
            encoded = canonical_json(payload).encode("utf-8")
            cluster_digest.update(len(encoded).to_bytes(8, "big"))
            cluster_digest.update(encoded)
        manifest["cluster_count"] = len(
            {
                (canonical_json(value["issuance_cutoff"]), value["cluster_identity"])
                for value in rows
            }
        )
        manifest["cluster_multiplicity_sha256"] = cluster_digest.hexdigest()
    if manifest_updates:
        manifest.update(manifest_updates)
    manifest["artifact_id"] = canonical_hash(
        _artifact_identity_from_manifest_v2(manifest)
    )
    manifest_path.write_text(canonical_json(manifest) + "\n")
    directory = artifact.directory.parent / manifest["artifact_id"]
    artifact.directory.rename(directory)
    return directory


def test_loader_rejects_structural_pit_index_cluster_and_timeframe_contradictions(
    tmp_path,
):
    tamper_cases = (
        ("structural", None, {"semantic_stream_sha256": "a" * 64}, "manifest"),
        (
            "baseline mismatch",
            None,
            {"baseline_config_fingerprint": "d" * 64},
            "manifest",
        ),
        (
            "pit",
            None,
            {"analysis_start": UTC_START + timedelta(hours=5)},
            "compact episode issuance",
        ),
        ("source index", {"source_close_index": 4}, None, "source close index"),
        (
            "trigger index",
            {"first_subsequent_trigger_index": 8},
            None,
            "trigger index",
        ),
        ("cluster", {"cluster_identity": "a" * 64}, None, "cluster identity"),
        (
            "timeframe set",
            None,
            {"source_record_counts": [["1h", 4]]},
            "manifest",
        ),
    )
    for case, row_updates, manifest_updates, message in tamper_cases:
        evidence, _, _, _, _ = _fixture()
        artifact = write_episode_artifact(
            evidence,
            artifact_root=tmp_path / case.replace(" ", "-"),
            baseline_config_fingerprint="c" * 64,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
            null_seed="fixture-seed",
        )
        row = None
        if row_updates:
            row = json.loads(
                (artifact.directory / "episodes.jsonl").read_text().splitlines()[0]
            )
            row.update(row_updates)
        if manifest_updates and case == "pit":
            merged = json.loads((artifact.directory / "manifest.json").read_text())
            merged.update(manifest_updates)
            merged["structural_receipt_hash"] = _structural_receipt_hash_from_manifest(
                merged
            )
            manifest_updates = merged
        directory = _reseal_compact_artifact(
            artifact, row=row, manifest_updates=manifest_updates
        )
        with pytest.raises(ValueError, match=message):
            load_episode_artifact(directory)


def test_authenticated_entrypoint_uses_nonretaining_collector(
    monkeypatch, tmp_path, sr_v2_config
):
    cutoff = datetime(2024, 1, 2, 5, 15, tzinfo=UTC)
    records = {}
    bounds = []
    for index, timeframe in enumerate(sr_v2_config.ladder):
        grid = grid_for(timeframe)
        end = grid.expected_closed_cutoff(cutoff)
        bar = _bar(timeframe, end - grid.duration, grid.duration, index)
        records[timeframe] = (
            SourceBarRecord(
                venue="venue",
                instrument_id="instrument",
                asset="asset",
                bar=bar,
                source_identity=bar.identity,
            ),
        )
        bounds.append((timeframe, bar.bar_open_at, bar.bar_close_at))
    acquisition = tuple(
        (timeframe, "CACHE_ONLY", UTC_START, "d" * 64) for timeframe in records
    )
    source_fingerprint = _authenticated_slice_fingerprint(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=tuple(bounds),
        records_by_timeframe=records,
        acquisition_evidence=acquisition,
    )
    source_slice = AuthenticatedSourceSlice(
        source_manifest_id="manifest",
        source_sha256="b" * 64,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        bounds=tuple(bounds),
        records_by_timeframe=records,
        record_identities=tuple(
            sorted(
                (timeframe, (values[0].source_identity,))
                for timeframe, values in records.items()
            )
        ),
        record_counts=tuple(sorted((timeframe, 1) for timeframe in records)),
        acquisition_evidence=acquisition,
        slice_fingerprint=source_fingerprint,
    )
    mismatch_root = tmp_path / "config-mismatch"
    with pytest.raises(ValueError, match="baseline_config_fingerprint"):
        EpisodeArtifactWriter(
            source_slice=source_slice,
            config=sr_v2_config,
            analysis_start=cutoff,
            knowledge_cutoff=cutoff,
            null_seed="seed",
            artifact_root=mismatch_root,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
            baseline_config_fingerprint="d" * 64,
        )
    assert not mismatch_root.exists()
    captured = {}
    original = EpisodeEvidenceCollector.from_authenticated_slice

    def wrapped(source_slice_value, **kwargs):
        collector = original(source_slice_value, **kwargs)
        captured["collector"] = collector
        captured["kwargs"] = kwargs
        return collector

    monkeypatch.setattr(
        EpisodeEvidenceCollector,
        "from_authenticated_slice",
        staticmethod(wrapped),
    )

    state = SRState(
        config_fingerprint=sr_v2_config.config_fingerprint,
        generation=1,
        last_trigger_at=cutoff,
        venue="venue",
        instrument_id="instrument",
        asset="asset",
        source_cutoffs={
            timeframe: values[0].bar.bar_close_at
            for timeframe, values in records.items()
        },
        source_fingerprints={
            timeframe: fingerprint_sequence_hash((values[0].source_identity,))
            for timeframe, values in records.items()
        },
        source_fingerprint_sequences={
            timeframe: (values[0].source_identity,)
            for timeframe, values in records.items()
        },
    )
    step = object.__new__(SRStepResult)
    for name, value in {
        "asset": "asset",
        "config_fingerprint": sr_v2_config.config_fingerprint,
        "market_as_of": cutoff,
        "candidates_by_timeframe": {},
        "transitions": (),
        "state": state,
        "source_cutoffs": {},
        "source_fingerprints": {},
        "lineage_registry": {},
    }.items():
        object.__setattr__(step, name, value)

    def fake_run(self, dataset, *args, **kwargs):
        kwargs["on_step"](step)
        return SimpleNamespace(state=state)

    monkeypatch.setattr(episode_evidence.OfflineCompute, "run", fake_run)
    artifact = run_streaming_episode_artifact(
        config=sr_v2_config,
        source_slice=source_slice,
        analysis_start=cutoff,
        knowledge_cutoff=cutoff,
        null_seed="seed",
        artifact_root=tmp_path,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
    )
    assert captured["kwargs"]["retain_episodes"] is False
    collector = captured["collector"]
    assert collector._episodes is None
    assert collector._episode_ids is None
    assert collector._cluster_counts is None
    assert load_episode_artifact(artifact.directory).manifest["episode_count"] == 0


def test_authenticated_entrypoint_streams_nonzero_rows_across_cutoffs(
    monkeypatch, tmp_path, sr_v2_config
):
    source_slice, steps, states = _authenticated_two_cutoff_run_fixture(sr_v2_config)
    captured = {}
    original = EpisodeEvidenceCollector.from_authenticated_slice

    def wrapped(source_slice_value, **kwargs):
        collector = original(source_slice_value, **kwargs)
        captured["collector"] = collector
        return collector

    monkeypatch.setattr(
        EpisodeEvidenceCollector,
        "from_authenticated_slice",
        staticmethod(wrapped),
    )

    def fake_run(self, dataset, *args, **kwargs):
        for step in steps:
            kwargs["on_step"](step)
        return SimpleNamespace(state=states[-1])

    monkeypatch.setattr(episode_evidence.OfflineCompute, "run", fake_run)
    artifact = run_streaming_episode_artifact(
        config=sr_v2_config,
        source_slice=source_slice,
        analysis_start=steps[0].market_as_of,
        knowledge_cutoff=steps[-1].market_as_of,
        null_seed="seed",
        artifact_root=tmp_path,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
    )
    rows = tuple(iter_episode_records(artifact))
    assert len(rows) == 2
    assert tuple(row.issuance_cutoff for row in rows) == tuple(
        sorted(row.issuance_cutoff for row in rows)
    )
    assert tuple(row.observation_id for row in rows) == tuple(
        sorted(
            (row.observation_id for row in rows),
            key=lambda value: next(
                row.issuance_cutoff for row in rows if row.observation_id == value
            ),
        )
    )
    manifest = artifact.manifest
    assert manifest["episode_count"] == manifest["issuance_count"] == 2
    assert manifest["issuance_sha256"] == _sequence_digest(
        iter(row.observation_id for row in rows)
    )
    collector = captured["collector"]
    assert collector._episodes is None
    assert collector._episode_ids is None
    assert collector._cluster_counts is None


def test_compact_roundtrip_preserves_lineages_and_all_null_receipts(tmp_path):
    evidence, _, episode, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    row = next(iter(iter_episode_records(artifact)))
    assert row.zone == episode.zone
    assert row.feasible_null.zone == episode.feasible_null.zone
    assert row.feasible_null.null_fingerprint == canonical_hash(
        episode.feasible_null.provenance
    )
    for receipt_name, provenance_name in (
        ("source_window", "source_window_bar_ids"),
        ("opportunity", "opportunity_bar_ids"),
        ("feasible_opportunity", "feasible_opportunity_bar_ids"),
        ("excluded_active_zone", "excluded_active_zone_ids"),
        ("selected_bar", "selected_bar_ids"),
    ):
        receipt = getattr(row.feasible_null, receipt_name)
        values = tuple(episode.feasible_null.provenance.get(provenance_name, ()))
        assert receipt.count == len(values)
        assert receipt.sha256 == canonical_hash(values)


def test_compact_roundtrip_preserves_incomplete_null_receipt(tmp_path):
    evidence, _, episode, _, _ = _fixture()
    incomplete = build_feasible_random_price_null(
        episode.zone,
        kernel_bars=tuple(
            item.bar for item in evidence.source_records_by_timeframe["1h"]
        ),
        active_zones=(episode.zone,),
        seed="fixture-seed",
    )
    assert not incomplete.complete
    assert incomplete.zone is None
    assert incomplete.reason
    incomplete_episode = replace(episode, feasible_null=incomplete)
    incomplete_evidence = replace(evidence, episodes=(incomplete_episode,))
    artifact = write_episode_artifact(
        incomplete_evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    row = next(iter(iter_episode_records(artifact)))
    assert not row.feasible_null.complete
    assert row.feasible_null.zone is None
    assert row.feasible_null.reason == incomplete.reason
    assert row.feasible_null.null_fingerprint == canonical_hash(incomplete.provenance)


def _assert_no_artifact_temporary_directories(root):
    asset_root = root / "asset"
    assert not tuple(asset_root.glob(".episode-v2-*"))


def test_artifact_replay_failure_removes_only_local_temporary_directory(
    monkeypatch, tmp_path, sr_v2_config
):
    source_slice, _, _ = _authenticated_two_cutoff_run_fixture(sr_v2_config)

    def fail_run(self, dataset, *args, **kwargs):
        raise RuntimeError("synthetic replay failure")

    monkeypatch.setattr(episode_evidence.OfflineCompute, "run", fail_run)
    with pytest.raises(RuntimeError, match="synthetic replay failure"):
        run_streaming_episode_artifact(
            config=sr_v2_config,
            source_slice=source_slice,
            analysis_start=UTC_START + timedelta(hours=15),
            knowledge_cutoff=UTC_START + timedelta(hours=16),
            null_seed="seed",
            artifact_root=tmp_path,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
        )
    _assert_no_artifact_temporary_directories(tmp_path)


def test_artifact_collector_finish_failure_removes_only_local_temporary_directory(
    monkeypatch, tmp_path, sr_v2_config
):
    source_slice, _, states = _authenticated_two_cutoff_run_fixture(sr_v2_config)

    def fake_run(self, dataset, *args, **kwargs):
        return SimpleNamespace(state=states[-1])

    def fail_finish(self, run_state):
        raise RuntimeError("synthetic collector finish failure")

    monkeypatch.setattr(episode_evidence.OfflineCompute, "run", fake_run)
    monkeypatch.setattr(EpisodeEvidenceCollector, "finish", fail_finish)
    with pytest.raises(RuntimeError, match="synthetic collector finish failure"):
        run_streaming_episode_artifact(
            config=sr_v2_config,
            source_slice=source_slice,
            analysis_start=UTC_START + timedelta(hours=15),
            knowledge_cutoff=UTC_START + timedelta(hours=16),
            null_seed="seed",
            artifact_root=tmp_path,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
        )
    _assert_no_artifact_temporary_directories(tmp_path)


def test_artifact_manifest_failure_removes_only_local_temporary_directory(
    monkeypatch, tmp_path
):
    evidence, _, _, _, _ = _fixture()

    def fail_validation(*args, **kwargs):
        raise ValueError("synthetic manifest failure")

    monkeypatch.setattr(
        episode_evidence, "_validate_artifact_manifest", fail_validation
    )
    with pytest.raises(ValueError, match="synthetic manifest failure"):
        write_episode_artifact(
            evidence,
            artifact_root=tmp_path,
            baseline_config_fingerprint="c" * 64,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
            null_seed="fixture-seed",
        )
    _assert_no_artifact_temporary_directories(tmp_path)


def test_artifact_collision_mismatch_removes_new_temporary_directory(tmp_path):
    evidence, _, _, _, _ = _fixture()
    artifact = write_episode_artifact(
        evidence,
        artifact_root=tmp_path,
        baseline_config_fingerprint="c" * 64,
        baseline_yaml_sha256="a" * 64,
        code_policy_id="policy",
        null_seed="fixture-seed",
    )
    episodes_path = artifact.directory / "episodes.jsonl"
    episodes_path.write_bytes(episodes_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="artifact|episodes"):
        write_episode_artifact(
            evidence,
            artifact_root=tmp_path,
            baseline_config_fingerprint="c" * 64,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
            null_seed="fixture-seed",
        )
    _assert_no_artifact_temporary_directories(tmp_path)


def test_equal_concurrent_artifact_writes_reuse_one_authenticated_target(tmp_path):
    evidence, _, _, _, _ = _fixture()

    def write_once(_):
        return write_episode_artifact(
            evidence,
            artifact_root=tmp_path,
            baseline_config_fingerprint="c" * 64,
            baseline_yaml_sha256="a" * 64,
            code_policy_id="policy",
            null_seed="fixture-seed",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        artifacts = tuple(pool.map(write_once, range(2)))
    assert len({item.artifact_id for item in artifacts}) == 1
    assert len({item.directory for item in artifacts}) == 1
    _assert_no_artifact_temporary_directories(tmp_path)
