import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R2_SOURCE = ROOT / "src" / "libs" / "analysis_capabilities" / "invocation"


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


def test_invocation_package_import_does_not_eagerly_load_native_stacks() -> None:
    result = _run(
        """
import sys
import libs.analysis_capabilities.invocation

assert 'libs.analysis_capabilities.invocation' in sys.modules
assert 'libs.analysis_capabilities.execution' in sys.modules
assert 'libs.models.trendlines' not in sys.modules
assert 'libs.models.sr' not in sys.modules
assert 'libs.regression.api' not in sys.modules
assert 'libs.analysis_capabilities.ta' not in sys.modules
assert 'numpy' not in sys.modules
assert 'pandas' not in sys.modules
assert not any(name.startswith('apps.') for name in sys.modules)
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_bound_ta_branch_does_not_load_sibling_ta_or_model_stacks() -> None:
    result = _run(
        """
from datetime import UTC, datetime, timedelta
import sys

from libs.analysis_capabilities.invocation import (
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.ta.swing_anchors import (
    SwingAnchorBar,
    SwingAnchorRequest,
)

start = datetime(2026, 1, 1, tzinfo=UTC)
bars = tuple(
    SwingAnchorBar(start + timedelta(hours=i), 10.0 + i, 5.0)
    for i in range(3)
)
request = SwingAnchorRequest(bars=bars, span=1)
series = AnalysisSeriesIdentity(
    asset='BTCUSDT', venue='binance', instrument_id='fixture:btc', timeframe='1h'
)
source = AnalysisSourceAttestation(
    series=series, source_type='fixture', source_provider=None,
    source_timeframe=None, source_revision='r1', source_slice_sha256='a' * 64,
    source_available_at=bars[-1].closed_at, volume_unit=None,
)
context = AnalysisInvocationContext(
    source=source, market_as_of=bars[-1].closed_at,
    request_available_at=bars[-1].closed_at + timedelta(minutes=1),
    evaluation_at=bars[-1].closed_at + timedelta(minutes=2),
)
execute_bound_analysis_capability('ta.swing_anchors', request, context)
assert 'libs.analysis_capabilities.ta.swing_anchors' in sys.modules
assert 'libs.analysis_capabilities.ta.fibonacci_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.traditional_pivot_geometry' not in sys.modules
assert 'libs.analysis_capabilities.ta.vwap_geometry' not in sys.modules
assert 'libs.models.trendlines' not in sys.modules
assert 'libs.models.sr' not in sys.modules
assert 'libs.regression.api' not in sys.modules
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_bound_trendline_branch_does_not_load_sibling_model_or_ta_stacks() -> None:
    result = _run(
        """
from datetime import UTC, datetime, timedelta
import sys

from libs.analysis_capabilities.invocation import (
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.execution.trendlines import TrendlinesExecutionRequest
from libs.models.trendlines import TrendlineBar

start = datetime(2026, 1, 1, tzinfo=UTC)
history = tuple(
    TrendlineBar(start + timedelta(hours=i), 100.0 + i, 101.0 + i,
                 99.0 + i, 100.5 + i)
    for i in range(3)
)
request = TrendlinesExecutionRequest(history)
series = AnalysisSeriesIdentity(
    asset='BTCUSDT', venue='binance', instrument_id='fixture:btc', timeframe='1h'
)
source = AnalysisSourceAttestation(
    series=series, source_type='fixture', source_provider=None,
    source_timeframe=None, source_revision='r1', source_slice_sha256='a' * 64,
    source_available_at=history[-1].closed_at, volume_unit=None,
)
context = AnalysisInvocationContext(
    source=source, market_as_of=history[-1].closed_at,
    request_available_at=history[-1].closed_at + timedelta(minutes=1),
    evaluation_at=history[-1].closed_at + timedelta(minutes=2),
)
execute_bound_analysis_capability('model.trendlines', request, context)
assert 'libs.models.trendlines' in sys.modules
assert 'libs.models.sr' not in sys.modules
assert 'libs.regression.api' not in sys.modules
assert 'libs.analysis_capabilities.ta' not in sys.modules
assert not any(name.startswith('apps.') for name in sys.modules)
"""
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_r2_production_sources_have_no_apps_or_dynamic_imports() -> None:
    forbidden = ("apps", "importlib")
    for source_path in R2_SOURCE.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in names
                for prefix in forbidden
            ), f"forbidden R2 import in {source_path}: {names}"
