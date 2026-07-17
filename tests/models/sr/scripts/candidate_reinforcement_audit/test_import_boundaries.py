from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[5] / "src/libs/models/sr/scripts/candidate_reinforcement_audit"
FORBIDDEN = (
    "apps.ingestion_app",
    "binance",
    "requests",
    "urllib",
    "socket",
    "database",
    "holdout",
    "zone_viewer",
    "libs.sr",
)


def test_package_imports_are_research_only_and_network_free():
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in FORBIDDEN) for name in names), (path, names)
