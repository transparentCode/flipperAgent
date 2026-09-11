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


def test_vwap_dispatch_loads_no_sibling_ta_or_model_provider() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

try:
    execute_analysis_capability('ta.vwap_geometry', object())
except TypeError:
    pass
else:
    raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.vwap_geometry' in sys.modules
assert 'libs.analysis_capabilities.ta' in sys.modules
assert 'libs.analysis_capabilities.ta.swing_anchors' not in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.classic_pivot_geometry' not in sys.modules
assert not any(
    name.startswith(('libs.models.', 'libs.regression.', 'libs.features.', 'apps.', 'libs.sr.'))
    for name in sys.modules
)
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_sibling_dispatch_does_not_import_vwap_provider() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

for capability_id in (
    'model.trendlines',
    'ta.swing_anchors',
    'ta.fibonacci_geometry',
    'ta.traditional_pivot_geometry',
):
    try:
        execute_analysis_capability(capability_id, object())
    except TypeError:
        pass
    else:
        raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.vwap_geometry' not in sys.modules
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout
