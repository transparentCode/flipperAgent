import ast
from pathlib import Path


def test_v22_study_has_no_sibling_or_forbidden_imports() -> None:
    root = (
        Path(__file__).resolve().parents[6]
        / "src/libs/models/sr/research/studies/swing_reversal_adequacy"
    )
    forbidden = (
        "libs.models.sr.research.studies.",
        "libs.sr",
        "libs.trendlines",
        "pandas",
        "numpy",
        "requests",
    )
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            name
            for node in ast.walk(tree)
            for name in (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
        ]
        assert not any(
            name.startswith("libs.models.sr.research.studies.")
            and "swing_reversal_adequacy" not in name
            for name in imports
        )
        assert not any(
            name == prefix or name.startswith(f"{prefix}.")
            for name in imports
            for prefix in forbidden[1:]
        )
