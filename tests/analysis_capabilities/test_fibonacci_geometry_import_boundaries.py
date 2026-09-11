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


def test_swing_anchor_dispatch_does_not_import_fibonacci_provider() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

try:
    execute_analysis_capability('ta.swing_anchors', object())
except TypeError:
    pass
else:
    raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.swing_anchors' in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_fibonacci_dispatch_loads_only_ta_dependencies() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

try:
    execute_analysis_capability('ta.fibonacci_geometry', object())
except TypeError:
    pass
else:
    raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.fibonacci_geometry' in sys.modules
assert 'libs.analysis_capabilities.ta.swing_anchors' in sys.modules
assert not any(
    name.startswith(('libs.models.', 'libs.regression.', 'apps.', 'libs.features.'))
    for name in sys.modules
)
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_model_dispatch_does_not_import_fibonacci_provider() -> None:
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
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout
