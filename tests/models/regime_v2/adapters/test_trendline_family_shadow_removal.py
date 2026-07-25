from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_removed_shadow_modules_are_absent_and_active_adapters_remain_usable() -> None:
    source_root = Path(__file__).resolve().parents[4] / "src"
    script = """
import importlib.util
import sys

removed = (
    ".".join(("libs", "models", "regime_v2", "adapters", "trendline_family_feature_producer")),
    ".".join(("libs", "integrations", "trendline_regime_v2", "shadow")),
)
for module_name in removed:
    assert importlib.util.find_spec(module_name) is None, module_name

from libs.models.regime_v2.adapters import RegimeV2FeatureProducer, TrendlineFeatureProducer

RegimeV2FeatureProducer("BTCUSDT", "1h")
TrendlineFeatureProducer("BTCUSDT", "1h")
assert all(module_name not in sys.modules for module_name in removed)
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


def test_signal_pipeline_remains_free_of_removed_shadow_api() -> None:
    source_root = Path(__file__).resolve().parents[4] / "src"
    script = """
import inspect
import sys

from apps.signal_app.pipeline.regime import RegimeFeaturePipeline

pipeline = RegimeFeaturePipeline.create_optional("BTCUSDT", "1h")
assert "trendline_family_shadow" not in inspect.signature(RegimeFeaturePipeline).parameters
assert "timestamp" not in inspect.signature(RegimeFeaturePipeline.append_bar).parameters
assert not hasattr(pipeline, "trendline_family_shadow")
assert not hasattr(pipeline, "refresh_trendline_family_shadow")
removed = (
    ".".join(("libs", "models", "regime_v2", "adapters", "trendline_family_feature_producer")),
    ".".join(("libs", "integrations", "trendline_regime_v2", "shadow")),
)
assert all(module_name not in sys.modules for module_name in removed)
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
