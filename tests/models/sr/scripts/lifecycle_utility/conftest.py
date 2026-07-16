from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.sr.domain.contracts import SREventType, ZoneSide
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar
from libs.models.sr.scripts.lifecycle_utility.config import (
    FROZEN_FOLD_NAMES,
    FROZEN_SOURCE_BUNDLE_ID,
    FROZEN_SOURCE_ID,
    FROZEN_BARS_SHA256,
    V10_AUDIT_ID,
    V10_BUNDLE_ID,
    V19_BUNDLE_ID,
    V19_STUDY_ID,
    load_lifecycle_utility_config,
)
from libs.models.sr.scripts.lifecycle_utility.contracts import (
    EventAccounting,
    LifecycleUtilityStudy,
    NullCell,
    ResolutionEvent,
    ResolutionOutcome,
)
from libs.models.sr.scripts.lifecycle_utility.metrics import evaluate_metrics


REPO_ROOT = Path(__file__).resolve().parents[5]
CONFIG_PATH = REPO_ROOT / "configs/sr_trials/sr_v1_11_taousdt_1d_lifecycle_utility.yaml"


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture(scope="session")
def lifecycle_config():
    return load_lifecycle_utility_config(CONFIG_PATH)


@pytest.fixture
def make_bars():
    def factory(count: int = 40, start: datetime = datetime(2024, 6, 1, tzinfo=timezone.utc)) -> tuple[SourceBar, ...]:
        bars = []
        for index in range(count):
            open_time = start + timedelta(days=index)
            opening = 100.0 + index * 0.25
            bars.append(
                SourceBar(
                    open_time=open_time,
                    closed_at=open_time + timedelta(days=1),
                    open=opening,
                    high=opening + 2.0,
                    low=opening - 1.0,
                    close=opening + 0.5,
                    volume=10.0 + index,
                    bar_id=f"test:TAOUSDT:1d:{index}",
                )
            )
        return tuple(bars)

    return factory


@pytest.fixture
def make_event():
    def factory(
        *,
        seed: str,
        fold: str = "2024_q3",
        event_class: str = "FALSE_BREAKOUT",
        side: ZoneSide = ZoneSide.SUPPORT,
        event_at: datetime | None = None,
        event_bar_id: str = "test-bar",
        anchor_close: float = 100.5,
    ) -> ResolutionEvent:
        event_at = event_at or datetime(2024, 7, 16, tzinfo=timezone.utc)
        return ResolutionEvent(
            case_id=digest(f"case:{seed}"),
            zone_id=digest(f"zone:{seed}"),
            event_id=digest(f"event:{seed}"),
            event_class=event_class,
            event_at=event_at,
            event_bar_id=event_bar_id,
            event_fold=fold,
            original_side=side,
            effective_side=side if event_class == "FALSE_BREAKOUT" else (ZoneSide.RESISTANCE if side is ZoneSide.SUPPORT else ZoneSide.SUPPORT),
            anchor_close=anchor_close,
            atr_at_event=1.5,
            atr_at_creation=1.25,
            center=100.0,
            lower_bound=99.0,
            upper_bound=101.0,
        )

    return factory


@pytest.fixture
def make_outcome():
    def factory(
        event: ResolutionEvent,
        *,
        quality: float = 0.25,
        null_median: float | None = 0.0,
        null_count: int = 4,
        censored: bool = False,
    ) -> ResolutionOutcome:
        if censored:
            return ResolutionOutcome(
                resolution_id=event.resolution_id,
                zone_id=event.zone_id,
                case_id=event.case_id,
                event_id=event.event_id,
                event_class=event.event_class,
                event_at=event.event_at,
                event_bar_id=event.event_bar_id,
                event_fold=event.event_fold,
                original_side=event.original_side,
                effective_side=event.effective_side,
                anchor_close=event.anchor_close,
                reference_atr_14=event.atr_at_event,
                outcome_start_bar_id=digest(f"start:{event.event_id}"),
                outcome_end_at=None,
                completed=False,
                right_censored=True,
                favorable_excursion_atr=None,
                adverse_excursion_atr=None,
                directional_quality_atr=None,
                null_median_quality_atr=None,
                excess_quality_atr=None,
                null_control_count=0,
            )
        adverse = 2.0
        favorable = adverse + quality
        return ResolutionOutcome(
            resolution_id=event.resolution_id,
            zone_id=event.zone_id,
            case_id=event.case_id,
            event_id=event.event_id,
            event_class=event.event_class,
            event_at=event.event_at,
            event_bar_id=event.event_bar_id,
            event_fold=event.event_fold,
            original_side=event.original_side,
            effective_side=event.effective_side,
            anchor_close=event.anchor_close,
            reference_atr_14=event.atr_at_event,
            outcome_start_bar_id=digest(f"start:{event.event_id}"),
            outcome_end_at=event.event_at + timedelta(days=10),
            completed=True,
            right_censored=False,
            favorable_excursion_atr=favorable,
            adverse_excursion_atr=adverse,
            directional_quality_atr=quality,
            null_median_quality_atr=null_median,
            excess_quality_atr=None if null_median is None else quality - null_median,
            null_control_count=null_count,
        )

    return factory


@pytest.fixture
def null_cells():
    return tuple(
        NullCell(
            fold=fold,
            effective_side=side,
            control_count=4,
            median_quality_atr=0.0,
            control_ids=(digest(f"{fold}:{side.value}:0"), digest(f"{fold}:{side.value}:1"), digest(f"{fold}:{side.value}:2"), digest(f"{fold}:{side.value}:3")),
        )
        for fold in FROZEN_FOLD_NAMES
        for side in (ZoneSide.RESISTANCE, ZoneSide.SUPPORT)
    )


@pytest.fixture
def synthetic_study(lifecycle_config, make_event, make_outcome, null_cells):
    def factory(implementation_commit: str = "a" * 40) -> LifecycleUtilityStudy:
        folds = FROZEN_FOLD_NAMES[:4]
        events = tuple(
            make_event(
                seed=f"study-{index}",
                fold=folds[index // 4],
                event_class="FALSE_BREAKOUT" if index % 2 == 0 else "BREAK_CONFIRMED",
                side=ZoneSide.SUPPORT if index % 3 else ZoneSide.RESISTANCE,
                event_at=datetime(2024, 7, 2, tzinfo=timezone.utc) + timedelta(days=index * 5),
                event_bar_id=f"study-bar-{index}",
            )
            for index in range(16)
        )
        outcomes = tuple(make_outcome(event, quality=0.25) for event in events)
        metrics = evaluate_metrics(outcomes, config=lifecycle_config)
        accounting = EventAccounting(
            source_case_count=36,
            resolution_event_count=16,
            unique_resolution_zone_count=16,
            false_breakout_count=8,
            break_confirmed_count=8,
            completed_count=16,
            right_censored_count=0,
        )
        return LifecycleUtilityStudy(
            implementation_commit=implementation_commit,
            config_hash=lifecycle_config.config_hash,
            v19_bundle_id=V19_BUNDLE_ID,
            v19_study_id=V19_STUDY_ID,
            v10_bundle_id=V10_BUNDLE_ID,
            v10_audit_id=V10_AUDIT_ID,
            source_bundle_id=FROZEN_SOURCE_BUNDLE_ID,
            source_id=FROZEN_SOURCE_ID,
            bars_sha256=FROZEN_BARS_SHA256,
            null_cells=null_cells,
            resolutions=events,
            outcomes=outcomes,
            fold_metrics=metrics.fold_metrics,
            aggregate=metrics.aggregate,
            event_accounting=accounting,
            decision=metrics.decision,
        )

    return factory


def simple_case(*, zone_id: str, side: ZoneSide, events: tuple[object, ...], available_at: datetime):
    zone = SimpleNamespace(
        available_at=available_at,
        atr_at_creation=1.25,
        center=100.0,
        lower_bound=99.0,
        upper_bound=101.0,
    )
    return SimpleNamespace(
        case_id=digest(f"case:{zone_id}"),
        zone_id=zone_id,
        side=side,
        zone=zone,
        lifecycle_events=events,
    )


def simple_event(*, event_id: str, zone_id: str, event_type: SREventType, timestamp: datetime, bar_id: str):
    return SimpleNamespace(
        event_id=event_id,
        zone_id=zone_id,
        event_type=event_type,
        timestamp=timestamp,
        bar_id=bar_id,
    )


__all__ = ["CONFIG_PATH", "REPO_ROOT", "digest", "simple_case", "simple_event"]
