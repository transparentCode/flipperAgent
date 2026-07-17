from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.scripts.baseline_adequacy.config import load_baseline_adequacy_config
from libs.models.sr.scripts.baseline_adequacy.runner import compute_study, load_frozen_inputs


ROOT = Path(__file__).resolve().parents[5]
CONFIG_PATH = ROOT / "configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def adequacy_config():
    return load_baseline_adequacy_config(CONFIG_PATH)


@pytest.fixture(scope="session")
def frozen_inputs(adequacy_config, repo_root):
    return load_frozen_inputs(adequacy_config, repo_root=repo_root)


@pytest.fixture(scope="session")
def adequacy_study(adequacy_config, repo_root):
    return compute_study(adequacy_config, repo_root=repo_root, implementation_commit="a" * 40)
