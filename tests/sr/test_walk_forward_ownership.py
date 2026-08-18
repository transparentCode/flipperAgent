"""Final ownership and behavior tests for the SR walk-forward utility."""

import ast
import hashlib
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


def _load_validator_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load walk-forward module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SR_ROOT = _REPO_ROOT / "src" / "libs" / "sr"
_LIBS_ROOT = _REPO_ROOT / "src" / "libs"
_OWNED_PATH = _SR_ROOT / "optimization" / "walk_forward.py"
_LEGACY_PATH = _LIBS_ROOT / "regression" / "optimization" / "walk_forward_2way.py"
_owned = _load_validator_module(_OWNED_PATH, "r4a_sr_walk_forward")
WalkForwardSplit = _owned.WalkForwardSplit
WalkForwardValidator = _owned.WalkForwardValidator


def _split_signature(
    split: WalkForwardSplit,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        split.fold_id,
        split.train_start,
        split.train_end,
        split.test_start,
        split.test_end,
        split.train_size,
        split.test_size,
    )


def test_sr_owned_validator_is_the_canonical_copy() -> None:
    digest = hashlib.sha256(_OWNED_PATH.read_bytes()).hexdigest()
    assert digest == "a405b2b319bf43386d5af68c499406e4849e440c7fa5e5aefe346aff36cb0f8d"


def test_regression_owned_walk_forward_module_is_absent() -> None:
    assert not _LEGACY_PATH.exists()
    try:
        spec = importlib.util.find_spec(
            "libs.regression.optimization.walk_forward_2way"
        )
    except ModuleNotFoundError:
        spec = None
    assert spec is None


@pytest.mark.parametrize(
    ("kwargs", "n_bars", "expected_folds"),
    (
        (
            {
                "train_bars": 100,
                "test_bars": 50,
                "step_bars": 50,
                "purge_bars": 10,
                "min_train_bars": 50,
            },
            100,
            0,
        ),
        (
            {
                "train_bars": 100,
                "test_bars": 50,
                "step_bars": 50,
                "purge_bars": 10,
                "min_train_bars": 50,
            },
            150,
            1,
        ),
        (
            {
                "train_bars": 100,
                "test_bars": 50,
                "step_bars": 50,
                "purge_bars": 10,
                "min_train_bars": 50,
            },
            300,
            3,
        ),
        (
            {
                "train_bars": 80,
                "test_bars": 40,
                "step_bars": 40,
                "purge_bars": 5,
                "min_train_bars": 80,
            },
            300,
            5,
        ),
        ({}, 10000, 7),
    ),
)
def test_sr_owned_fold_counts_and_descriptors(kwargs, n_bars, expected_folds):
    validator = WalkForwardValidator(**kwargs)

    assert validator.n_folds(n_bars) == expected_folds
    splits = validator.get_splits(n_bars)
    assert len(splits) == expected_folds

    train_bars = min(validator.train_bars, int(n_bars * 0.6))
    expected = []
    for fold_id in range(expected_folds):
        train_start = fold_id * validator.step_bars
        train_end = train_start + train_bars
        test_start = train_end + validator.purge_bars
        test_end = test_start + validator.test_bars
        expected.append(
            (
                fold_id,
                train_start,
                train_end,
                test_start,
                test_end,
                train_bars,
                validator.test_bars,
            )
        )

    assert [_split_signature(split) for split in splits] == expected


def test_sr_owned_insufficient_data_exception() -> None:
    validator = WalkForwardValidator(
        train_bars=100,
        test_bars=50,
        step_bars=50,
        purge_bars=10,
        min_train_bars=50,
    )

    with pytest.raises(
        ValueError, match="Insufficient data for walk-forward validation"
    ):
        validator.n_folds(99)
    with pytest.raises(
        ValueError, match="Insufficient data for walk-forward validation"
    ):
        validator.get_splits(99)


def test_sr_owned_split_dataclass_and_size_properties() -> None:
    split = WalkForwardSplit(
        fold_id=2,
        train_start=30,
        train_end=130,
        test_start=140,
        test_end=190,
    )

    assert _split_signature(split) == (2, 30, 130, 140, 190, 100, 50)


@pytest.mark.parametrize("initial_train_bars", (None, 80))
def test_sr_owned_expanding_windows(initial_train_bars) -> None:
    validator = WalkForwardValidator(
        train_bars=100,
        test_bars=50,
        step_bars=50,
        purge_bars=10,
        min_train_bars=50,
    )

    splits = validator.expanding_window_splits(500, initial_train_bars)

    assert splits
    assert all(split.train_start == 0 for split in splits)
    assert all(split.train_end < split.test_start for split in splits)


def test_sr_owned_dataframe_iteration_preserves_boundaries_and_values() -> None:
    validator = WalkForwardValidator(
        train_bars=80,
        test_bars=40,
        step_bars=40,
        purge_bars=5,
        min_train_bars=80,
    )
    index = pd.date_range("2025-01-01", periods=300, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "close": range(300),
            "marker": [f"bar-{i}" for i in range(300)],
        },
        index=index,
    )

    folds = list(validator.iterate_splits(frame))

    assert len(folds) == validator.n_folds(len(frame))
    for split, train, test in folds:
        assert len(train) == split.train_size
        assert len(test) == split.test_size
        pd.testing.assert_frame_equal(
            train,
            frame.iloc[split.train_start : split.train_end].copy(),
        )
        pd.testing.assert_frame_equal(
            test,
            frame.iloc[split.test_start : split.test_end].copy(),
        )


def test_sr_production_has_no_regression_optimization_imports() -> None:
    forbidden = ("libs.regression.optimization", "app.regression.optimization")
    violations = []
    for path in _SR_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            violations.extend(
                (path, module) for module in modules if module.startswith(forbidden)
            )
    assert violations == []
