from __future__ import annotations

import subprocess
import sys


def test_geometry_package_import_does_not_load_provider_or_viewer_modules():
    code = """
import sys
import libs.models.sr.scripts.geometry_sensitivity
for name in sys.modules:
    assert not name.startswith('apps.ingestion_app.adapters.binance_native')
    assert not name.startswith('libs.models.sr.tools.zone_viewer')
"""
    result = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
