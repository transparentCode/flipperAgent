from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
    LaneEffectProgressSaveResult,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _identity() -> LaneExecutionIdentity:
    return LaneExecutionIdentity(
        lane_id="BTCUSDT:momentum_1h",
        effective_lane_revision="lane-revision",
        feature_plan_fingerprint="feature-fingerprint",
    )


@pytest.mark.asyncio
async def test_shadow_progress_is_monotonic_and_exact_identity_scoped() -> None:
    repository = InMemoryLaneEffectProgressRepository()
    identity = _identity()
    first = LaneEffectProgress.create(identity=identity, market_as_of=BASE)

    assert await repository.save(first) == LaneEffectProgressSaveResult.INSERTED
    assert await repository.save(first) == LaneEffectProgressSaveResult.IDENTICAL
    assert (
        await repository.save(
            LaneEffectProgress.create(
                identity=identity,
                market_as_of=BASE + timedelta(hours=1),
                last_disposition="shadow",
            )
        )
        == LaneEffectProgressSaveResult.UPDATED
    )
    assert (
        await repository.save(
            LaneEffectProgress.create(
                identity=identity,
                market_as_of=BASE,
                last_disposition="shadow",
            )
        )
        == LaneEffectProgressSaveResult.REJECTED_OLDER
    )
    assert (
        await repository.save(
            LaneEffectProgress.create(
                identity=identity,
                market_as_of=BASE + timedelta(hours=1),
            )
        )
        == LaneEffectProgressSaveResult.CONFLICT
    )

    other_identity = LaneExecutionIdentity(
        lane_id=identity.lane_id,
        effective_lane_revision=identity.effective_lane_revision,
        feature_plan_fingerprint="other-feature-fingerprint",
    )
    assert await repository.load(other_identity) is None


@pytest.mark.asyncio
async def test_lane_effect_progress_accepts_authoritative_dispositions() -> None:
    published = LaneEffectProgress.create(
        identity=_identity(),
        market_as_of=BASE,
        last_disposition="published",  # type: ignore[arg-type]
    )
    no_signal = LaneEffectProgress.create(
        identity=_identity(),
        market_as_of=BASE,
        last_disposition="no_signal",  # type: ignore[arg-type]
    )
    assert published.last_disposition == "published"
    assert no_signal.last_disposition == "no_signal"


@pytest.mark.asyncio
async def test_shadow_progress_rejects_invalid_disposition() -> None:
    with pytest.raises(ValueError, match="last_disposition"):
        LaneEffectProgress.create(
            identity=_identity(),
            market_as_of=BASE,
            last_disposition="invalid",  # type: ignore[arg-type]
        )
