from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from libs.models.sr_v2.contracts import ZoneSide
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.candidates import Candidate
from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.domain.zones import lineage_from_candidate
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.forecast.targets import (
    label_scientific_target,
    resolve_target_spec,
    scientific_target_fingerprint,
)
from libs.models.sr_v2.research.evaluation import (
    DevelopmentEvaluationControls,
    DevelopmentForecast,
    DevelopmentStatus,
    bootstrap_joint_calendar_blocks,
    evaluate_development,
)
from libs.models.sr_v2.research.observations import canonical_issuance_calendar_block
from libs.models.sr_v2.research.placebos import (
    build_feasible_random_price_null,
)
from libs.models.sr_v2.research_lab.scientific_compiler import (
    CompiledScientificSet,
    ScientificGroupKey,
    ScientificObservation,
)

_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
_SOURCE_ID = "development-manifest"
_SOURCE_SHA = "a" * 64


def _bar(opened: datetime, *, high: str, low: str, timeframe: str = "15m") -> SRBar:
    duration = grid_for(timeframe).duration
    high_value = Decimal(high)
    low_value = Decimal(low)
    midpoint = (high_value + low_value) / Decimal(2)
    return SRBar(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=midpoint,
        high=high_value,
        low=low_value,
        close=midpoint,
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
    )


def _zone(issued_at: datetime, *, asset: str, candidate_key: str):
    candidate = Candidate(
        candidate_key=candidate_key,
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset=asset,
        source_timeframe="1h",
        kernel_id="fixture",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
        center=Decimal(100),
        lower=Decimal(99),
        upper=Decimal(101),
        formed_at=issued_at - timedelta(hours=1),
        available_at=issued_at,
        source_evidence_id=f"evidence-{candidate_key}",
        creation_atr=Decimal(7),
    )
    return lineage_from_candidate(candidate, config_fingerprint="fixture-config")


def _reference(issuance: datetime) -> tuple[SRBar, ...]:
    start = issuance - timedelta(hours=3)
    return tuple(
        _bar(
            start + timedelta(hours=index),
            timeframe="1h",
            high="102",
            low="98",
        )
        for index in range(3)
    )


def _future(issuance: datetime, *, touched: bool) -> tuple[SRBar, ...]:
    if touched:
        values = [("100.5", "99.5"), ("104", "100.5")]
    else:
        values = [("110", "109")]
    values += [("110", "109")] * (8 - len(values))
    return tuple(
        _bar(
            issuance + timedelta(minutes=15 * index),
            high=high,
            low=low,
        )
        for index, (high, low) in enumerate(values)
    )


def _spec():
    return resolve_target_spec(
        source_timeframe="1h",
        source_horizon_bars=2,
        reference_lookback=2,
        barrier_multiplier=Decimal("0.5"),
        observation_timeframe="15m",
        observation_duration=timedelta(minutes=15),
    )


def _observation(
    issued_at: datetime,
    *,
    asset: str,
    candidate_key: str,
    touched: bool,
    ambiguous: bool = False,
    censored: bool = False,
) -> ScientificObservation:
    zone = _zone(issued_at, asset=asset, candidate_key=candidate_key)
    spec = _spec()
    future = _future(issued_at, touched=touched)
    if ambiguous:
        future = (
            _bar(issued_at, high="104", low="96"),
            *_future(issued_at + timedelta(minutes=15), touched=False),
        )[:8]
    if censored:
        future = future[:1]
    target = label_scientific_target(
        zone,
        issued_at=issued_at,
        future_bars=future,
        target_spec=spec,
        reference_bars=_reference(issued_at),
    )
    kernel_bars = tuple(
        _bar(
            issued_at - timedelta(hours=3 - index),
            timeframe="1h",
            high="110",
            low=str(90 + index * 5),
        )
        for index in range(3)
    )
    feasible_null = build_feasible_random_price_null(
        zone,
        kernel_bars=kernel_bars,
        active_zones=(),
        seed="evaluation-null",
    )
    assert feasible_null.zone is not None
    null_target = label_scientific_target(
        feasible_null.zone,
        issued_at=issued_at,
        future_bars=future,
        target_spec=spec,
        reference_bars=_reference(issued_at),
    )
    group = ScientificGroupKey(
        asset=asset,
        timeframe="1h",
        kernel_id="fixture",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
    )
    return ScientificObservation(
        observation_id=zone.zone_id,
        group=group,
        zone=zone,
        target=target,
        feasible_null=feasible_null,
        null_target=null_target,
        source_manifest_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA,
        target_fingerprint=scientific_target_fingerprint(spec),
        null_fingerprint=canonical_hash(feasible_null.provenance),
    )


def _compiled(observations: tuple[ScientificObservation, ...]) -> CompiledScientificSet:
    expected = tuple(sorted({observation.group for observation in observations}))
    return CompiledScientificSet(
        source_manifest_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA,
        expected_groups=expected,
        observations=observations,
        compiler_fingerprint="compiler-fingerprint",
        knowledge_cutoff=max(observation.issued_at for observation in observations)
        + timedelta(hours=2),
    )


def _controls(groups, *, minimum_touched: int = 1, repetitions: int = 20):
    return DevelopmentEvaluationControls(
        expected_groups=tuple(groups),
        minimum_uncensored_lineages=1,
        minimum_touched_lineages=minimum_touched,
        bootstrap_repetitions=repetitions,
        bootstrap_seed="evaluation-seed",
        bootstrap_block=timedelta(days=1),
        bootstrap_epoch=_EPOCH,
        confidence=0.9,
        ece_bins=5,
        source_manifest_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA,
    )


def _forecasts(observations):
    return tuple(
        DevelopmentForecast(
            observation_id=observation.observation_id,
            group=observation.group,
            issued_at=observation.issued_at,
            source_manifest_id=_SOURCE_ID,
            source_sha256=_SOURCE_SHA,
            touch_probability=0.5,
            bounce_probability=0.7,
            break_probability=0.3,
        )
        for observation in observations
    )


def test_evaluation_is_inconclusive_and_uses_canonical_joint_blocks():
    observations = (
        _observation(
            _EPOCH + timedelta(hours=1),
            asset="BTCUSDT",
            candidate_key="one",
            touched=True,
        ),
        _observation(
            _EPOCH + timedelta(days=1, hours=1),
            asset="BTCUSDT",
            candidate_key="two",
            touched=False,
        ),
        _observation(
            _EPOCH + timedelta(hours=1),
            asset="ETHUSDT",
            candidate_key="three",
            touched=True,
        ),
        _observation(
            _EPOCH + timedelta(days=1, hours=1),
            asset="ETHUSDT",
            candidate_key="four",
            touched=False,
        ),
    )
    compiled = _compiled(observations)
    controls = _controls(compiled.expected_groups)
    report = evaluate_development(
        compiled, tuple(reversed(_forecasts(observations))), controls
    )
    assert report.status is DevelopmentStatus.INCONCLUSIVE
    assert report.reason is None
    assert report.calendar_blocks
    assert all(
        isinstance(label, str) and "/" in label for label in report.calendar_blocks
    )
    assert all(
        metric.status is DevelopmentStatus.INCONCLUSIVE
        for metric in report.metrics_by_group.values()
    )


def test_evaluation_rejects_identity_gaps_and_unavailable_nulls():
    observations = (
        _observation(
            _EPOCH + timedelta(hours=1),
            asset="BTCUSDT",
            candidate_key="one",
            touched=True,
        ),
        _observation(
            _EPOCH + timedelta(days=1, hours=1),
            asset="BTCUSDT",
            candidate_key="two",
            touched=False,
        ),
    )
    compiled = _compiled(observations)
    controls = _controls(compiled.expected_groups)
    missing = evaluate_development(compiled, _forecasts(observations)[:1], controls)
    assert missing.status is DevelopmentStatus.INVALID
    assert (
        missing.metrics_by_group[observations[0].group].status
        is DevelopmentStatus.INVALID
    )

    incomplete_null = replace(
        observations[0],
        feasible_null=replace(
            observations[0].feasible_null,
            complete=False,
            zone=None,
            reason="fixture unavailable",
        ),
        null_target=None,
    )
    invalid = evaluate_development(
        _compiled((incomplete_null, observations[1])),
        _forecasts((incomplete_null, observations[1])),
        controls,
    )
    assert invalid.status is DevelopmentStatus.INVALID
    assert "unavailable" in invalid.reason


def test_evaluation_excludes_censored_and_ambiguous_reaction_rows():
    observations = (
        _observation(
            _EPOCH + timedelta(hours=1),
            asset="BTCUSDT",
            candidate_key="touch",
            touched=True,
        ),
        _observation(
            _EPOCH + timedelta(hours=2),
            asset="BTCUSDT",
            candidate_key="plain",
            touched=False,
        ),
        _observation(
            _EPOCH + timedelta(hours=3),
            asset="BTCUSDT",
            candidate_key="censored",
            touched=False,
            censored=True,
        ),
        _observation(
            _EPOCH + timedelta(hours=4),
            asset="BTCUSDT",
            candidate_key="ambiguous",
            touched=True,
            ambiguous=True,
        ),
    )
    report = evaluate_development(
        _compiled(observations),
        _forecasts(observations),
        _controls((observations[0].group,)),
    )
    metric = report.metrics_by_group[observations[0].group]
    assert report.status is DevelopmentStatus.INCONCLUSIVE
    assert metric.observation_count == 4
    assert metric.uncensored_count == 3
    assert metric.reaction_count == 1


def test_evaluation_reports_insufficient_support_and_extra_forecast_invalid():
    observations = (
        _observation(
            _EPOCH + timedelta(hours=1),
            asset="BTCUSDT",
            candidate_key="one",
            touched=True,
        ),
        _observation(
            _EPOCH + timedelta(days=1, hours=1),
            asset="BTCUSDT",
            candidate_key="two",
            touched=False,
        ),
    )
    compiled = _compiled(observations)
    insufficient = evaluate_development(
        compiled,
        _forecasts(observations),
        _controls(compiled.expected_groups, minimum_touched=2),
    )
    assert insufficient.status is DevelopmentStatus.INSUFFICIENT
    assert all(
        metric.status is DevelopmentStatus.INSUFFICIENT
        for metric in insufficient.metrics_by_group.values()
    )

    extra = DevelopmentForecast(
        observation_id="extra-observation",
        group=observations[0].group,
        issued_at=observations[0].issued_at,
        source_manifest_id=_SOURCE_ID,
        source_sha256=_SOURCE_SHA,
        touch_probability=0.5,
        bounce_probability=0.5,
        break_probability=0.5,
    )
    invalid = evaluate_development(
        compiled,
        (*_forecasts(observations), extra),
        _controls(compiled.expected_groups),
    )
    assert invalid.status is DevelopmentStatus.INVALID


def test_joint_bootstrap_preserves_duplicate_slots_and_is_order_invariant():
    first = ScientificGroupKey(
        asset="BTCUSDT",
        timeframe="1h",
        kernel_id="k",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
    )
    second = ScientificGroupKey(
        asset="ETHUSDT",
        timeframe="1h",
        kernel_id="k",
        kernel_version="1",
        side=ZoneSide.SUPPORT,
    )
    issued = (
        _EPOCH + timedelta(hours=1),
        _EPOCH + timedelta(days=1, hours=1),
    )
    kwargs = {
        "repetitions": 20,
        "seed": "seed",
        "block": timedelta(days=1),
        "epoch": _EPOCH,
    }
    draws = bootstrap_joint_calendar_blocks({first: issued, second: issued}, **kwargs)
    reversed_draws = bootstrap_joint_calendar_blocks(
        {second: issued, first: issued}, **kwargs
    )
    assert draws == reversed_draws
    assert any(len(set(slots)) < len(slots) for slots in draws)
    assert all(len(slots) == 2 for slots in draws)
    assert bootstrap_joint_calendar_blocks({first: (issued[0],)}, **kwargs) == ()


def test_joint_bootstrap_interval_retains_duplicate_slot_multiplicity():
    issued = (
        _EPOCH + timedelta(hours=1),
        _EPOCH + timedelta(days=1, hours=1),
        _EPOCH + timedelta(days=2, hours=1),
    )
    observations = (
        _observation(issued[0], asset="BTCUSDT", candidate_key="poor", touched=True),
        _observation(issued[1], asset="BTCUSDT", candidate_key="good", touched=False),
        _observation(issued[2], asset="BTCUSDT", candidate_key="mid", touched=True),
    )
    group = observations[0].group
    controls = _controls((group,), repetitions=64)
    forecasts = tuple(
        DevelopmentForecast(
            observation_id=observation.observation_id,
            group=group,
            issued_at=observation.issued_at,
            source_manifest_id=_SOURCE_ID,
            source_sha256=_SOURCE_SHA,
            touch_probability=(0.1, 0.1, 0.5)[index],
            bounce_probability=0.5,
            break_probability=0.5,
        )
        for index, observation in enumerate(observations)
    )
    report = evaluate_development(_compiled(observations), forecasts, controls)
    assert report.status is DevelopmentStatus.INCONCLUSIVE
    metric = report.metrics_by_group[group]
    labels = tuple(
        canonical_issuance_calendar_block(
            value,
            block=controls.bootstrap_block,
            epoch=controls.bootstrap_epoch,
        )
        for value in issued
    )
    draws = bootstrap_joint_calendar_blocks(
        {group: issued},
        repetitions=controls.bootstrap_repetitions,
        seed=controls.bootstrap_seed,
        block=controls.bootstrap_block,
        epoch=controls.bootstrap_epoch,
    )
    # The two block scores differ, so retaining repeated draw slots has a
    # directly observable effect on the interval rather than only on metadata.
    score_by_block = {
        labels[0]: (0.1 - 1.0) ** 2,
        labels[1]: 0.1**2,
        labels[2]: (0.5 - 1.0) ** 2,
    }
    preserved_samples = tuple(
        sum(score_by_block[label] for label in slots) / len(slots) for slots in draws
    )
    flattened_samples = tuple(
        sum(score_by_block[label] for label in dict.fromkeys(slots))
        / len(dict.fromkeys(slots))
        for slots in draws
    )
    assert any(
        preserved != flattened
        for preserved, flattened in zip(preserved_samples, flattened_samples)
    )
    ordered = sorted(preserved_samples)
    alpha = (1.0 - controls.confidence) / 2.0
    lower = min(len(ordered) - 1, max(0, math.floor(alpha * len(ordered))))
    upper = min(
        len(ordered) - 1,
        max(0, math.ceil((1.0 - alpha) * len(ordered)) - 1),
    )
    assert metric.touch_interval == (ordered[lower], ordered[upper])


def test_cutoff_weighting_is_not_lineage_count_weighting():
    first_cutoff = _EPOCH + timedelta(hours=1)
    second_cutoff = _EPOCH + timedelta(hours=2)
    observations = (
        _observation(
            first_cutoff, asset="BTCUSDT", candidate_key="first-poor", touched=True
        ),
        _observation(
            first_cutoff, asset="BTCUSDT", candidate_key="first-good", touched=True
        ),
        _observation(
            second_cutoff, asset="BTCUSDT", candidate_key="second-good", touched=False
        ),
    )
    group = observations[0].group
    forecasts = tuple(
        DevelopmentForecast(
            observation_id=observation.observation_id,
            group=group,
            issued_at=observation.issued_at,
            source_manifest_id=_SOURCE_ID,
            source_sha256=_SOURCE_SHA,
            touch_probability=(
                0.0
                if observation.observation_id == observations[0].observation_id
                else 1.0
                if observation.observation_id == observations[1].observation_id
                else 0.0
            ),
            bounce_probability=0.5,
            break_probability=0.5,
        )
        for observation in observations
    )
    report = evaluate_development(
        _compiled(observations),
        forecasts,
        _controls((group,), repetitions=16),
    )
    metric = report.metrics_by_group[group]
    assert report.status is DevelopmentStatus.INCONCLUSIVE
    assert metric.cutoff_count == 2
    assert metric.touch_brier == 0.25
