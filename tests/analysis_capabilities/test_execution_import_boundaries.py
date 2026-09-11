import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_metadata_root_does_not_import_execution_or_models() -> None:
    result = _run(
        """
import sys
import libs.analysis_capabilities

assert 'libs.analysis_capabilities.execution' not in sys.modules
assert not any(
    name.startswith(('libs.models.', 'libs.regression.', 'apps.'))
    for name in sys.modules
)
"""
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_execution_root_is_lazy_about_all_model_stacks() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

assert callable(execute_analysis_capability)
assert 'libs.analysis_capabilities.execution' in sys.modules
assert 'libs.models.trendlines' not in sys.modules
assert 'libs.models.sr' not in sys.modules
assert 'libs.regression.api' not in sys.modules
assert 'libs.analysis_capabilities.ta' not in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.classic_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.vwap_geometry' not in sys.modules
"""
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_dispatching_one_branch_does_not_import_other_model_stacks() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

try:
    execute_analysis_capability('model.trendlines', object())
except TypeError:
    pass
else:
    raise AssertionError('wrong request type was accepted')

assert 'libs.models.trendlines' in sys.modules
assert 'libs.models.sr' not in sys.modules
assert 'libs.regression.api' not in sys.modules
assert 'libs.analysis_capabilities.ta' not in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.classic_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.vwap_geometry' not in sys.modules
"""
    )

    assert result.returncode == 0, result.stderr or result.stdout
