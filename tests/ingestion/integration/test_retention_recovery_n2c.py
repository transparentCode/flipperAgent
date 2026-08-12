from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_n2c_retention_and_empty_valkey_recovery_certification() -> None:
    if os.getenv("INGESTION_RUN_N2C_RETENTION") != "1":
        pytest.skip("set INGESTION_RUN_N2C_RETENTION=1 to run N2C certification")

    repository_root = Path(__file__).parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/certify_ingestion_retention_recovery_n2c.py",
            "--execute",
        ],
        cwd=repository_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "READY_FOR_REVIEW"' in result.stdout
