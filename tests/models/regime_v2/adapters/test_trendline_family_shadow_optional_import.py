from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_active_adapters_import_without_optional_family_shadow_module() -> None:
    source_root = Path(__file__).resolve().parents[4] / "src"
    script = """
import builtins
import sys

original_import = builtins.__import__

def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "libs.models.regime_v2.adapters.trendline_family_feature_producer":
        raise ImportError("optional trendline-family adapter unavailable")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = blocked_import
from libs.models.regime_v2.adapters import RegimeV2FeatureProducer, TrendlineFeatureProducer

RegimeV2FeatureProducer("BTCUSDT", "1h")
TrendlineFeatureProducer("BTCUSDT", "1h")
assert "libs.models.regime_v2.adapters.trendline_family_feature_producer" not in sys.modules
"""
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
