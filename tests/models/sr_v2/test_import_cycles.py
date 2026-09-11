from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _run_fresh_imports(source: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    source_root = str(REPOSITORY_ROOT / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root if not existing else f"{source_root}{os.pathsep}{existing}"
    )
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_research_lab_data_then_development_imports_in_fresh_process():
    result = _run_fresh_imports(
        """
from libs.models.sr_v2.research_lab.data import AuthenticatedSourceSlice
from libs.models.sr_v2.research.development import ResolvedTargetDesignConfig
assert AuthenticatedSourceSlice.__name__ == 'AuthenticatedSourceSlice'
assert ResolvedTargetDesignConfig.__name__ == 'ResolvedTargetDesignConfig'
"""
    )
    assert result.returncode == 0, result.stderr


def test_development_then_research_lab_data_imports_in_fresh_process():
    result = _run_fresh_imports(
        """
from libs.models.sr_v2.research.development import ResolvedTargetDesignConfig
from libs.models.sr_v2.research_lab.data import AuthenticatedSourceSlice
assert ResolvedTargetDesignConfig.__name__ == 'ResolvedTargetDesignConfig'
assert AuthenticatedSourceSlice.__name__ == 'AuthenticatedSourceSlice'
"""
    )
    assert result.returncode == 0, result.stderr


def test_final_mechanics_use_their_own_module_boundaries_in_fresh_process():
    result = _run_fresh_imports(
        """
from libs.models.sr_v2.research.development import ResolvedTargetDesignConfig
from libs.models.sr_v2.research.geometry_evidence import GeometryFamilyEvidence
from libs.models.sr_v2.research.optimizer import GeometryRankingInput
assert ResolvedTargetDesignConfig.__name__ == 'ResolvedTargetDesignConfig'
assert GeometryFamilyEvidence.__name__ == 'GeometryFamilyEvidence'
assert GeometryRankingInput.__name__ == 'GeometryRankingInput'
"""
    )
    assert result.returncode == 0, result.stderr
