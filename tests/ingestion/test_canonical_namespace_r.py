from __future__ import annotations

import importlib.util
from pathlib import Path

from apps.ingestion_app.publication.outbox import (
    CANDLE_COMMITTED_EVENT_TYPE,
    CANDLE_COMMITTED_PRODUCER,
    CANDLE_COMMITTED_SCHEMA_VERSION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_canonical_application_and_test_namespaces_are_unique() -> None:
    assert importlib.util.find_spec("apps.ingestion_app") is not None
    assert importlib.util.find_spec("apps.ingestion_app.main") is not None
    old_app_namespace = "apps.ingestion_app" + "_" + "v2"
    assert importlib.util.find_spec(old_app_namespace) is None

    assert (REPOSITORY_ROOT / "src/apps/ingestion_app").is_dir()
    old_app_path = REPOSITORY_ROOT / "src/apps" / ("ingestion_app" + "_v2")
    assert not old_app_path.exists()
    assert (REPOSITORY_ROOT / "tests/ingestion").is_dir()
    old_test_path = REPOSITORY_ROOT / "tests" / ("ingestion" + "_v2")
    assert not old_test_path.exists()


def test_canonical_protocols_and_configuration_are_aligned() -> None:
    assert CANDLE_COMMITTED_PRODUCER == "ingestion"
    assert CANDLE_COMMITTED_EVENT_TYPE == "candle.committed"
    assert CANDLE_COMMITTED_SCHEMA_VERSION == 1

    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text()
    global_config = (REPOSITORY_ROOT / "configs/ingestion/global.yaml").read_text()
    dashboard = (
        REPOSITORY_ROOT
        / "configs/observability/grafana/provisioning/dashboards/ingestion.json"
    ).read_text()

    assert "ingestion:" in compose
    assert "python -m apps.ingestion_app.main" in compose
    assert "OTEL_SERVICE_NAME: ingestion" in compose
    assert 'flipper-ingestion = "apps.ingestion_app.main:main"' in pyproject
    assert global_config.lstrip().startswith("ingestion:")
    assert '"uid": "flipper-ingestion"' in dashboard
