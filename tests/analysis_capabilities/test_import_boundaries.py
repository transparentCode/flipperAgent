import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "libs" / "analysis_capabilities"


def test_foundation_source_has_no_dynamic_or_model_imports() -> None:
    forbidden_prefixes = (
        "apps",
        "libs.models",
        "libs.regression",
        "importlib",
    )

    for source_path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported_names = [node.module or ""]
            else:
                continue
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in imported_names
                for prefix in forbidden_prefixes
            ), f"forbidden import in {source_path}: {imported_names}"


def test_foundation_import_does_not_load_model_implementations() -> None:
    script = """
import sys

from libs.analysis_capabilities import list_analysis_capabilities

assert [entry.capability_id for entry in list_analysis_capabilities()] == [
    'model.regression',
    'model.sr',
    'model.trendlines',
    'ta.abcd_pattern_geometry',
    'ta.anchored_vwap_path',
    'ta.cypher_pattern_geometry',
    'ta.elliott_correction_wave_geometry',
    'ta.elliott_impulse_wave_geometry',
    'ta.fibonacci_geometry',
    'ta.fibonacci_trend_extension_geometry',
    'ta.gann_box_geometry',
    'ta.gann_fan_geometry',
    'ta.head_shoulders_pattern_geometry',
    'ta.parallel_channel_geometry',
    'ta.swing_anchors',
    'ta.three_drives_pattern_geometry',
    'ta.traditional_pivot_geometry',
    'ta.triangle_pattern_geometry',
    'ta.volume_profile_geometry',
    'ta.vwap_geometry',
    'ta.xabcd_pattern_geometry',
]

for name in (
    'libs.models.trendlines',
    'libs.models.trendlines_v4',
    'libs.models.sr',
    'libs.regression.api',
    'libs.selection',
    'numpy',
    'pandas',
    'scipy',
    'sklearn',
    'xgboost',
    'lightgbm',
    'torch',
    'apps.decision_app',
):
    assert name not in sys.modules, name
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
