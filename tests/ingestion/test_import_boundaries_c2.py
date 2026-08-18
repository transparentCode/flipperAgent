from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_IMPORTS = (
    "from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema",
    "from apps.ingestion_app.storage.repository import CandleRepository",
    "from apps.ingestion_app.publication.outbox import OutboxEvent",
    "from apps.ingestion_app.publication.publisher import OutboxPublisher",
    "from apps.ingestion_app.publication import OutboxPublisher",
    "import apps.ingestion_app.bootstrap",
    "import apps.ingestion_app.main",
)


def _fresh_process(expression: str) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    source_path = str(root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_path, environment.get("PYTHONPATH")) if value
    )
    return subprocess.run(
        [sys.executable, "-c", expression],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ingestion_package_imports_are_order_independent() -> None:
    for expression in _IMPORTS:
        result = _fresh_process(expression)
        assert result.returncode == 0, result.stderr


def test_package_outbox_publisher_is_the_direct_publisher_class() -> None:
    result = _fresh_process(
        "from apps.ingestion_app.publication import OutboxPublisher as package; "
        "from apps.ingestion_app.publication.publisher import OutboxPublisher as direct; "
        "assert package is direct"
    )
    assert result.returncode == 0, result.stderr
