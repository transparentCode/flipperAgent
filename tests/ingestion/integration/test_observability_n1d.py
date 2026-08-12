"""Guarded real-stack observability certification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("INGESTION_RUN_N1D_OBSERVABILITY") != "1":
    pytest.skip(
        "set INGESTION_RUN_N1D_OBSERVABILITY=1 to run N1D certification",
        allow_module_level=True,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_real_ingestion_observability_certification() -> None:
    environment = os.environ.copy()
    environment["INGESTION_RUN_N1D_OBSERVABILITY"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/certify_ingestion_observability_n1d.py",
            "--execute",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "READY_FOR_REVIEW"
    assert report["prometheus"]
    assert report["tempo"]["trace_count"] >= 1
    assert report["loki"]["stream_count"] >= 1
    assert report["grafana"]["dashboards"]
