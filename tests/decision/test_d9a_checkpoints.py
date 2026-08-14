from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.state import LaneExecutionIdentity
from apps.decision_app.storage.checkpoints import (
    CheckpointCorruptionError,
    CheckpointSaveResult,
    InMemoryCheckpointRepository,
    LaneStateCheckpoint,
)
from apps.decision_app.storage.state_codec import (
    StateCodecError,
    decode_state_payload,
    encode_state_payload,
    state_payload_sha256,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
IDENTITY = LaneExecutionIdentity(
    lane_id="BTCUSDT:1h",
    effective_lane_revision="lane-rev",
    feature_plan_fingerprint="feature-rev",
    data_plan_fingerprint="data-rev",
)


def test_checkpoint_codec_round_trip_and_canonical_hash() -> None:
    state = {
        "count": 3,
        "decimal": Decimal("1.25"),
        "when": BASE,
        "values": (True, b"abc", None),
    }
    payload = encode_state_payload(state)
    decoded = decode_state_payload(payload)

    assert decoded["count"] == 3
    assert decoded["decimal"] == Decimal("1.25")
    assert decoded["when"] == BASE
    assert state_payload_sha256(payload) == state_payload_sha256(payload)
    assert encode_state_payload(decoded) == payload


@pytest.mark.parametrize("value", [{"bad": {1, 2}}, object()])
def test_checkpoint_codec_rejects_unsupported_state(value: object) -> None:
    with pytest.raises((StateCodecError, TypeError, ValueError)):
        encode_state_payload(value)


def _checkpoint(cutoff: datetime, *, count: int = 1) -> LaneStateCheckpoint:
    return LaneStateCheckpoint.create(
        identity=IDENTITY,
        market_as_of=cutoff,
        state_inception_at=BASE + timedelta(hours=1),
        state_by_binding={"binding-a": {"count": count}},
    )


@pytest.mark.asyncio
async def test_checkpoint_latest_only_idempotency_and_conflict() -> None:
    repository = InMemoryCheckpointRepository()
    first = _checkpoint(BASE + timedelta(hours=2))
    assert await repository.save(first) is CheckpointSaveResult.INSERTED
    assert await repository.save(first) is CheckpointSaveResult.IDENTICAL
    assert (
        await repository.save(_checkpoint(BASE + timedelta(hours=2), count=2))
        is CheckpointSaveResult.CONFLICT
    )
    assert (
        await repository.save(_checkpoint(BASE + timedelta(hours=1)))
        is CheckpointSaveResult.REJECTED_OLDER
    )
    assert (
        await repository.save(_checkpoint(BASE + timedelta(hours=3)))
        is CheckpointSaveResult.UPDATED
    )


@pytest.mark.asyncio
async def test_checkpoint_load_requires_exact_stateful_binding_set() -> None:
    repository = InMemoryCheckpointRepository()
    await repository.save(_checkpoint(BASE + timedelta(hours=2)))
    with pytest.raises(CheckpointCorruptionError, match="binding IDs"):
        await repository.load(IDENTITY, expected_binding_ids=("other",))
