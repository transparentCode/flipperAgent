from __future__ import annotations

import subprocess
import sys


def test_baseline_adequacy_import_boundary_is_provider_free():
    code = """
import sys
import libs.models.sr.scripts.baseline_adequacy
for name in sys.modules:
    assert not name.startswith('apps.ingestion_app.adapters.binance_native')
    assert not name.startswith('libs.models.sr.tools.zone_viewer')
    assert not name.startswith('requests')
    assert not name.startswith('httpx')
"""
    result = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
