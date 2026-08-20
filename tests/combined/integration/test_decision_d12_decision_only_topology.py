from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

from tests.combined.d12_harness import (
    D12_COMPOSE_FILE,
    EXPECTED_SERVICES,
    FORBIDDEN_SERVICE_TOKENS,
)


def test_d12_compose_contains_only_decision_topology() -> None:
    document = yaml.safe_load(D12_COMPOSE_FILE.read_text(encoding="utf-8"))
    assert tuple(document["services"]) == EXPECTED_SERVICES
    assert all(token not in document["services"] for token in FORBIDDEN_SERVICE_TOKENS)


@pytest.mark.skipif(
    os.environ.get("D12_RUN_REAL") != "1",
    reason="real disposable D12 infrastructure is opt-in",
)
def test_real_d12_certification() -> None:
    import subprocess

    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "scripts/certify_decision_d12_decision_only_topology.py"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": "src"},
        text=True,
        check=False,
    )
    assert result.returncode == 0
