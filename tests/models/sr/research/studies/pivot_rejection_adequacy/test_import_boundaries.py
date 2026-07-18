import ast
from pathlib import Path


def test_v21_study_has_no_sibling_study_imports() -> None:
    root = (
        Path(__file__).resolve().parents[6]
        / "src/libs/models/sr/research/studies/pivot_rejection_adequacy"
    )
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(
            module.startswith("libs.models.sr.research.studies.")
            and "pivot_rejection_adequacy" not in module
            for module in imports
        )
