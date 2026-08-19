from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.storage.shadow_progress import (
    InMemoryShadowProgressRepository,
    ShadowProgress,
    ShadowProgressSaveResult,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _identity() -> LaneExecutionIdentity:
    return LaneExecutionIdentity(
        lane_id="BTCUSDT:momentum_1h",
        effective_lane_revision="lane-revision",
        feature_plan_fingerprint="feature-fingerprint",
        data_plan_fingerprint="data-fingerprint",
    )


@pytest.mark.asyncio
async def test_shadow_progress_is_monotonic_and_exact_identity_scoped() -> None:
    repository = InMemoryShadowProgressRepository()
    identity = _identity()
    first = ShadowProgress.create(identity=identity, market_as_of=BASE)

    assert await repository.save(first) == ShadowProgressSaveResult.INSERTED
    assert await repository.save(first) == ShadowProgressSaveResult.IDENTICAL
    assert (
        await repository.save(
            ShadowProgress.create(
                identity=identity,
                market_as_of=BASE + timedelta(hours=1),
                last_disposition="shadow",
            )
        )
        == ShadowProgressSaveResult.UPDATED
    )
    assert (
        await repository.save(
            ShadowProgress.create(
                identity=identity,
                market_as_of=BASE,
                last_disposition="shadow",
            )
        )
        == ShadowProgressSaveResult.REJECTED_OLDER
    )
    assert (
        await repository.save(
            ShadowProgress.create(
                identity=identity,
                market_as_of=BASE + timedelta(hours=1),
            )
        )
        == ShadowProgressSaveResult.CONFLICT
    )

    other_identity = LaneExecutionIdentity(
        lane_id=identity.lane_id,
        effective_lane_revision=identity.effective_lane_revision,
        feature_plan_fingerprint=identity.feature_plan_fingerprint,
        data_plan_fingerprint="other-data-fingerprint",
    )
    assert await repository.load(other_identity) is None


@pytest.mark.asyncio
async def test_shadow_progress_rejects_invalid_disposition() -> None:
    with pytest.raises(ValueError, match="last_disposition"):
        ShadowProgress.create(
            identity=_identity(),
            market_as_of=BASE,
            last_disposition="published",  # type: ignore[arg-type]
        )
