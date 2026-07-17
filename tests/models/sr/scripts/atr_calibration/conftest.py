from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.scripts.atr_calibration.candidates import replay_candidates
from libs.models.sr.scripts.atr_calibration.config import load_calibration_config
from libs.models.sr.scripts.atr_calibration.metrics import compute_candidate_metrics
from libs.models.sr.scripts.atr_calibration.runner import resolve_frozen_sr_config
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage, SourceCapsule
from libs.models.sr.scripts.atr_calibration.source import build_development_capsule, load_frozen_source


ROOT = Path(__file__).resolve().parents[5]
CONFIG_PATH = ROOT / "configs/sr_trials/taousdt_1d_atr_calibration.yaml"


@pytest.fixture(scope="session")
def calibration_config():
    return load_calibration_config(CONFIG_PATH)


@pytest.fixture(scope="session")
def resolved_sr_config(calibration_config):
    return resolve_frozen_sr_config(calibration_config, repo_root=ROOT)


@pytest.fixture(scope="session")
def source_capsules(calibration_config):
    development = build_development_capsule(
        calibration_config,
        repo_root=ROOT,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    return development, None


@pytest.fixture(scope="session")
def sealed_test_capsule(calibration_config):
    """In-memory full-source fixture for holdout-validator contract tests only."""
    return SourceCapsule(
        stage=CapsuleStage.SEALED_HOLDOUT,
        source_bundle_id=calibration_config.source_bundle_id,
        source_bars_sha256=calibration_config.source_bars_sha256,
        source_row_count=calibration_config.source_row_count,
        split_boundary=calibration_config.holdout_start,
        implementation_commit=calibration_config.source_implementation_commit,
        bars=load_frozen_source(calibration_config, repo_root=ROOT),
    )


@pytest.fixture(scope="session")
def development_replays(calibration_config, resolved_sr_config, source_capsules):
    development, _ = source_capsules
    return replay_candidates(
        development,
        calibration_config.candidate_periods,
        config=calibration_config,
        resolved_config=resolved_sr_config,
    )


@pytest.fixture(scope="session")
def development_metrics(calibration_config, source_capsules, development_replays):
    development, _ = source_capsules
    return tuple(
        compute_candidate_metrics(replay, development, config=calibration_config)
        for replay in development_replays
    )
