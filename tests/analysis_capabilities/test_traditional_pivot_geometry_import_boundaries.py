import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_old_classic_identity_is_not_discoverable() -> None:
    assert (
        importlib.util.find_spec("libs.analysis_capabilities.ta.classic_pivot_geometry")
        is None
    )
    with pytest.raises(KeyError):
        from libs.analysis_capabilities.execution import execute_analysis_capability

        execute_analysis_capability("ta.classic_pivot_geometry", object())


def test_traditional_dispatch_loads_no_sibling_ta_or_model_provider() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

try:
    execute_analysis_capability('ta.traditional_pivot_geometry', object())
except TypeError:
    pass
else:
    raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' in sys.modules
assert 'libs.analysis_capabilities.ta' in sys.modules
assert 'libs.analysis_capabilities.ta.swing_anchors' not in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
assert not any(
    name.startswith(('libs.models.', 'libs.regression.', 'libs.features.', 'apps.'))
    for name in sys.modules
)
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_sibling_dispatch_does_not_import_traditional_provider() -> None:
    result = _run(
        """
import sys
from libs.analysis_capabilities.execution import execute_analysis_capability

for capability_id in (
    'model.trendlines',
    'ta.swing_anchors',
    'ta.fibonacci_geometry',
    'ta.vwap_geometry',
):
    try:
        execute_analysis_capability(capability_id, object())
    except TypeError:
        pass
    else:
        raise AssertionError('wrong request type was accepted')

assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' not in sys.modules
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout
