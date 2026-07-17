from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from libs.models.sr.scripts.cohort_readiness.config import load_cohort_config
from libs.models.sr.scripts.cohort_readiness.runner import resolve_frozen_configs
from libs.models.sr.scripts.cohort_readiness.source import load_taousdt_source


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


@pytest.fixture(scope="session")
def cohort_config(repo_root):
    return load_cohort_config(repo_root / "configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml")


@pytest.fixture(scope="session")
def resolved_configs(cohort_config, repo_root):
    sr, inputs, hashes = resolve_frozen_configs(cohort_config, repo_root=repo_root)
    return sr, inputs, hashes


@pytest.fixture(scope="session")
def tao_source(cohort_config, resolved_configs, repo_root):
    _, _, hashes = resolved_configs
    return load_taousdt_source(
        cohort_config,
        repo_root=repo_root,
        resolved_sr_config_hash=hashes["TAOUSDT"][0],
        resolved_input_hash=hashes["TAOUSDT"][1],
    )


def frame_for_asset(source, asset):
    return pd.DataFrame(
        [
            {
                "timestamp": int(bar.open_time.timestamp() * 1000),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in source.bars
        ],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
