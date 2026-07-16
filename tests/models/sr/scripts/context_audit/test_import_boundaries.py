from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys


FORBIDDEN_ROOTS = {"pandas", "numpy", "scipy", "sklearn", "statsmodels", "requests", "httpx", "ccxt"}


def test_context_audit_imports_stay_inside_research_boundary(repo_root: Path):
    package = repo_root / "src/libs/models/sr/scripts/context_audit"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name.split(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert not FORBIDDEN_ROOTS.intersection(names), f"forbidden import in {path}: {names}"


def test_clean_context_audit_import_has_no_provider_side_effect(repo_root: Path):
    result = subprocess.run(
        [sys.executable, "-c", "import libs.models.sr.scripts.context_audit"],
        cwd=repo_root,
        env={"PYTHONPATH": str(repo_root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "binance" not in result.stdout.lower()
