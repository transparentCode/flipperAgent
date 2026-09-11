from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R3_SOURCE_ROOT = ROOT / "research" / "analysis_capabilities"


def test_metadata_root_stays_lightweight_until_execution_is_opted_in() -> None:
    script = """
import sys
import libs.analysis_capabilities
for name in ("pandas", "numpy", "scipy", "sklearn", "asyncpg", "research.analysis_capabilities"):
    assert name not in sys.modules, name
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src:."
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_r3_imports_are_static_and_do_not_contain_acquisition_or_browser_calls() -> (
    None
):
    forbidden_names = {
        "requests",
        "httpx",
        "urlopen",
        "webbrowser",
        "create_pool",
        "get_historical_ohlcv",
        "fetch_native_window",
    }
    for path in R3_SOURCE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] not in forbidden_names
                    for alias in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden_names, path
            elif isinstance(node, ast.Call):
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                assert function_name not in forbidden_names, path


def test_r3_package_exports_only_the_named_offline_vertical_slice() -> None:
    script = """
import research.analysis_capabilities as r3
expected = {
    "R3CanonicalSourceError", "R3CanonicalSourceSlice", "R3ExecutionBundle",
    "R3RequestError", "R3ViewerError", "R3_SOURCE_REVISION", "build_canonical_frame",
    "build_canonical_source_slice", "build_fibonacci_request", "build_r3_source_slice",
    "build_swing_request", "build_traditional_pivot_request", "build_trendlines_request",
    "build_tvlc_html", "build_tvlc_payload", "build_vwap_request",
    "execute_fibonacci", "execute_r3_vertical_slice", "execute_swing_anchors",
    "execute_traditional_pivot", "execute_trendlines", "execute_vwap",
    "source_slice_fingerprint",
}
assert set(r3.__all__) == expected
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src:."
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
