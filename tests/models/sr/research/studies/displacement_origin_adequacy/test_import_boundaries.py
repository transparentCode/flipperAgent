from __future__ import annotations

import ast
from pathlib import Path


_PACKAGE = Path("src/libs/models/sr/research/studies/displacement_origin_adequacy")


def test_v2_study_imports_no_sibling_study_or_provider_boundary() -> None:
    forbidden = (
        "libs.models.sr.research.studies.",
        "libs.models.sr.adapters",
        "libs.models.sr.providers",
        "pandas",
        "requests",
    )
    for path in _PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                continue
            assert not any(
                name.startswith(prefix) for name in names for prefix in forbidden
            ), f"forbidden V2.0 import in {path}: {names}"
