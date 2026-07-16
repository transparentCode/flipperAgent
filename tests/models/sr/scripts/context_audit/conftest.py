from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.scripts.context_audit.config import load_context_audit_config
from libs.models.sr.scripts.context_audit.runner import compute_audit, repository_commit


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


@pytest.fixture(scope="session")
def context_config(repo_root: Path):
    return load_context_audit_config(
        repo_root / "configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml"
    )


@pytest.fixture(scope="session")
def context_result(context_config, repo_root: Path):
    return compute_audit(
        context_config,
        repo_root=repo_root,
        implementation_commit=repository_commit(repo_root),
    )
