from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REMOVED_PACKAGE = REPOSITORY_ROOT / "src/apps/ingestion"
ACTIVE_ROOTS = (
    REPOSITORY_ROOT / "src",
    REPOSITORY_ROOT / "scripts",
    REPOSITORY_ROOT / "configs",
)
FORBIDDEN_IMPORT = re.compile(r"apps\.ingestion_app_" + r"v2")


def test_versioned_namespace_is_absent_and_unreferenced() -> None:
    assert not REMOVED_PACKAGE.exists()

    violations: list[str] = []

    for root in ACTIVE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if FORBIDDEN_IMPORT.search(text):
                violations.append(str(path.relative_to(REPOSITORY_ROOT)))

    assert not violations, "legacy ingestion imports remain: " + ", ".join(violations)
