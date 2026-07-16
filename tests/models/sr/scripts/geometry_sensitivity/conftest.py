from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.scripts.geometry_sensitivity.config import load_geometry_config
from libs.models.sr.scripts.geometry_sensitivity.runner import compute_study, load_frozen_inputs


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


@pytest.fixture(scope="session")
def geometry_config(repo_root: Path):
    return load_geometry_config(repo_root / "configs/sr_trials/sr_v1_8_1d_geometry_sensitivity.yaml")


@pytest.fixture(scope="session")
def frozen_inputs(geometry_config, repo_root):
    return load_frozen_inputs(geometry_config, repo_root=repo_root)


@pytest.fixture(scope="session")
def study(geometry_config, repo_root):
    return compute_study(geometry_config, repo_root=repo_root, implementation_commit="a" * 40)
