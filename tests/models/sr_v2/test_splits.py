from datetime import UTC, datetime, timedelta

from libs.models.sr_v2.research.splits import ChronologicalSplits, validate_splits


def test_splits_require_embargo():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    windows = tuple((start + timedelta(days=offset), start + timedelta(days=offset + 1)) for offset in (0, 3, 6, 9))
    splits = ChronologicalSplits(development_train=windows[0], calibration=windows[1], validation=windows[2], protected_holdout=windows[3], embargo=timedelta(days=1))
    assert validate_splits(splits, max_horizon=timedelta(hours=1)) == splits
