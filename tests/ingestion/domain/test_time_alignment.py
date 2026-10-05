from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.ingestion_app.domain.time_alignment import aligned_bucket_start, is_aligned

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "duration",
    [
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=2),
        timedelta(hours=4),
        timedelta(hours=6),
        timedelta(hours=12),
        timedelta(days=1),
        timedelta(weeks=1),
    ],
)
def test_fixed_duration_alignment_uses_only_duration_and_origin(
    duration: timedelta,
) -> None:
    timestamp = ORIGIN + duration * 3 + duration - timedelta(seconds=1)

    assert aligned_bucket_start(timestamp, duration, ORIGIN) == ORIGIN + duration * 3


def test_is_aligned_is_true_only_for_bucket_starts() -> None:
    duration = timedelta(minutes=15)
    bucket_start = ORIGIN + duration * 3

    assert is_aligned(bucket_start, duration, ORIGIN)
    assert not is_aligned(bucket_start + timedelta(seconds=1), duration, ORIGIN)
    assert not is_aligned(bucket_start - timedelta(seconds=1), duration, ORIGIN)
