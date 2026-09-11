"""PIT and configuration semantics retained under the research namespace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import signature
from pathlib import Path

import pytest

from libs.models.sr_v2.contracts import ForecastOutcome, ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.zones import ZoneRecord, lineage_from_candidate
from libs.models.sr_v2.forecast.targets import label_forecast, target_fingerprint
from libs.models.sr_v2.lifecycle.engine import advance_zone
from libs.models.sr_v2.lifecycle.rules import LifecycleRules
from libs.models.sr_v2.lifecycle.transitions import TransitionType
from libs.models.sr_v2.research.observations import (
    ResearchObservation,
    canonical_issuance_calendar_block,
    canonical_matching_strata,
    validate_issuance_calendar_block,
)
from libs.models.sr_v2.research.placebos import (
    build_shuffled_time_nulls,
    matched_random_price_placebos,
)
from libs.models.sr_v2.research.studies import (
    SR_V2_RESEARCH_CODE_VERSION,
    build_protected_evaluation,
    load_trial_config,
)


def _zone(issued_at: datetime, *, side: ZoneSide = ZoneSide.SUPPORT):
    candidate = Candidate(
        candidate_key="research-zone",
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        source_timeframe="15m",
        kernel_id="fixture",
        kernel_version="1",
        side=side,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=issued_at,
        available_at=issued_at,
        source_evidence_id="evidence",
        creation_atr=Decimal(1),
    )
    return lineage_from_candidate(candidate, config_fingerprint="config")


def _bar(opened: datetime, *, low: str, high: str, close: str) -> SRBar:
    closed = opened + timedelta(minutes=15)
    return SRBar(
        timeframe="15m",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(1),
        taker_buy_base=Decimal(".5"),
    )


def test_targets_only_inspect_bars_strictly_after_issuance():
    issued = datetime(2024, 1, 1, tzinfo=UTC)
    zone = _zone(issued)
    with pytest.raises(TypeError):
        label_forecast(  # type: ignore[call-arg]
            zone,
            issued_at=issued,
            future_bars=(),
            horizon=timedelta(hours=1),
            bounce_excursion_atr=Decimal(1),
            break_buffer_atr=Decimal(".5"),
            observation_timeframe="15m",
            observation_duration=timedelta(minutes=15),
        )
    observation = label_forecast(
        zone,
        issued_at=issued,
        future_bars=(_bar(issued, low="99", high="101", close="100"),),
        horizon=timedelta(minutes=15),
        bounce_excursion_atr=Decimal(1),
        break_buffer_atr=Decimal(".5"),
        break_confirmation_bars=2,
        observation_timeframe="15m",
        observation_duration=timedelta(minutes=15),
    )
    assert observation.outcome is ForecastOutcome.TOUCH_UNRESOLVED
    assert observation.ambiguous is False
    assert observation.complete is True


def test_lifecycle_revisit_and_typed_break_stream_are_deterministic():
    issued = datetime(2024, 1, 1, tzinfo=UTC)
    zone = _zone(issued, side=ZoneSide.RESISTANCE)
    rules = LifecycleRules(
        break_buffer_atr=Decimal(".5"),
        break_confirmation_bars=1,
        expiry=timedelta(days=90),
    )
    touched, first = advance_zone(
        ZoneRecord(lineage=zone),
        _bar(issued + timedelta(minutes=15), low="99.5", high="100.5", close="100"),
        rules=rules,
    )
    broken, second = advance_zone(
        touched,
        _bar(touched.last_transition_at, low="101", high="102", close="102"),
        rules=rules,
    )
    assert first[0].transition_type is TransitionType.TOUCH_STARTED
    assert second[-1].transition_type is TransitionType.BROKEN
    assert broken.lifecycle.value == "BROKEN"


def test_trial_loader_uses_canonical_model_and_explicit_trial_values():
    trial = load_trial_config("configs/sr_v2_trials/phase1.yaml")
    assert trial.version == 2
    assert trial.model_path.endswith("configs/sr_v2.yaml")
    assert len(trial.model_sha256) == 64
    assert trial.target_break_buffer_atr == Decimal("0.50")
    assert trial.target_break_confirmation_bars == 2
    assert trial.bootstrap_epoch.tzinfo is not None
    assert {item.name for item in trial.null_specs} == {"random_price", "shuffled_time"}
    assert trial.matching_strata


def test_random_price_null_is_deterministic_and_changes_geometry():
    issued = datetime(2024, 1, 1, tzinfo=UTC)
    zone = _zone(issued)
    first = matched_random_price_placebos((zone,), seed="fixture", max_abs_shift_atr=Decimal(1))
    second = matched_random_price_placebos((zone,), seed="fixture", max_abs_shift_atr=Decimal(1))
    assert first == second
    assert first[0].zone_id != zone.zone_id
    assert first[0].available_at == zone.available_at


def _observation(issued_at: datetime, *, width: str = "w1") -> ResearchObservation:
    return ResearchObservation(
        observation_id=f"observation-{issued_at.isoformat()}-{width}",
        asset="BTCUSDT",
        timeframe="1d",
        side="SUPPORT",
        width_stratum=width,
        issuance_calendar_block=issued_at.date().isoformat(),
        normalized_distance_stratum="d1",
        volatility_stratum="v1",
        level_density_stratum="l1",
        touch_opportunity_stratum="t1",
        formed_at=issued_at,
        issued_at=issued_at,
        observation_end_at=issued_at + timedelta(hours=1),
        source_evidence_id="evidence",
    )


def test_matching_strata_selection_and_order_change_keys_and_target_identity(tmp_path):
    observation = _observation(datetime(2024, 1, 1, tzinfo=UTC))
    assert observation.strata_key_for(("asset", "width")) == ("BTCUSDT", "w1")
    assert observation.strata_key_for(("width", "asset")) == ("w1", "BTCUSDT")
    common = {
        "horizons": (timedelta(hours=1),),
        "bounce_excursion_atr": Decimal(1),
        "break_buffer_atr": Decimal(".5"),
        "break_confirmation_bars": 2,
        "observation_timeframe": "15m",
        "observation_duration": timedelta(minutes=15),
    }
    assert target_fingerprint(**common) != target_fingerprint(
        **{**common, "observation_timeframe": "30m", "observation_duration": timedelta(minutes=30)}
    )
    model_copy = tmp_path / "sr_v2.yaml"
    model_copy.write_bytes(Path("configs/sr_v2.yaml").read_bytes())
    trial_text = Path("configs/sr_v2_trials/phase1.yaml").read_text(encoding="utf-8")
    trial_text = trial_text.replace("path: ../sr_v2.yaml", "path: sr_v2.yaml")
    trial_a = tmp_path / "trial_a.yaml"
    trial_a.write_text(trial_text, encoding="utf-8")
    trial_b = tmp_path / "trial_b.yaml"
    trial_b.write_text(
        trial_text.replace(
            "[asset, timeframe, side, width, issuance_calendar_block, normalized_distance, volatility, level_density, touch_opportunity]",
            "[asset, timeframe, side]",
        ),
        encoding="utf-8",
    )
    assert load_trial_config(trial_a).config_fingerprint != load_trial_config(trial_b).config_fingerprint


def test_matching_strata_accepts_only_canonical_ontology_names():
    with pytest.raises(ValueError, match="unsupported fields"):
        canonical_matching_strata(("calendar",))


def test_shuffled_time_nulls_use_the_explicit_configured_strata_subset():
    first = _observation(datetime(2024, 1, 1, tzinfo=UTC), width="w1")
    second = _observation(datetime(2024, 1, 2, tzinfo=UTC), width="w2")
    nulls = build_shuffled_time_nulls(
        (first, second),
        seed="fixture",
        matching_strata=("asset", "timeframe", "side"),
    )
    assert {item.issued_at for item in nulls} == {first.issued_at, second.issued_at}
    with pytest.raises(ValueError, match="not derangeable"):
        build_shuffled_time_nulls(
            (first, second),
            seed="fixture",
            matching_strata=("asset", "timeframe", "width"),
        )


def test_shuffled_time_nulls_copy_source_calendar_and_record_provenance():
    epoch = datetime(2024, 1, 1, tzinfo=UTC)

    def sourced(issued_at: datetime, identity: str) -> ResearchObservation:
        return ResearchObservation(
            observation_id=f"observation-{identity}",
            asset="BTCUSDT",
            timeframe="1d",
            side="SUPPORT",
            width_stratum="w1",
            issuance_calendar_block=canonical_issuance_calendar_block(
                issued_at,
                block=timedelta(days=7),
                epoch=epoch,
            ),
            normalized_distance_stratum="d1",
            volatility_stratum="v1",
            level_density_stratum="l1",
            touch_opportunity_stratum="t1",
            formed_at=issued_at,
            issued_at=issued_at,
            observation_end_at=issued_at + timedelta(hours=1),
            source_file_path=f"/protected/{identity}.jsonl",
            source_record_identity=identity,
            source_evidence_id=f"evidence-{identity}",
        )

    first = sourced(datetime(2024, 1, 2, tzinfo=UTC), "record-a")
    second = sourced(datetime(2024, 1, 10, tzinfo=UTC), "record-b")
    source_by_issued = {first.issued_at: first, second.issued_at: second}
    nulls = build_shuffled_time_nulls(
        (first, second),
        seed="provenance-fixture",
        matching_strata=("asset", "timeframe", "side"),
    )

    for null in nulls:
        source = source_by_issued[null.issued_at]
        assert null.issuance_calendar_block == source.issuance_calendar_block
        assert null.source_file_path == source.source_file_path
        assert null.source_record_identity == source.source_record_identity
        assert validate_issuance_calendar_block(
            null.issued_at,
            null.issuance_calendar_block,
            block=timedelta(days=7),
            epoch=epoch,
        ) == source.issuance_calendar_block

    with pytest.raises(ValueError, match="asset and timeframe"):
        build_shuffled_time_nulls(
            (first, second),
            seed="provenance-fixture",
            matching_strata=("asset", "side"),
        )


def test_protected_evaluation_derives_provenance_from_resolved_inputs():
    parameters = signature(build_protected_evaluation).parameters
    assert "target_config" in parameters
    assert parameters["target_config"].default is parameters["target_config"].empty
    assert not {
        "runtime_config_fingerprint",
        "target_fingerprint",
        "kernel_fingerprint",
        "code_fingerprint",
    } & set(parameters)
    assert SR_V2_RESEARCH_CODE_VERSION.startswith("sr_v2.research.phase1@")
