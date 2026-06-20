"""Ingestion app package exports."""

from typing import Any

__all__ = [
    "main",
    "IngestionScheduler",
    "WorkerSettings",
    "startup",
    "shutdown",
]


def __getattr__(name: str) -> Any:
    if name == "main":
        from apps.ingestion_app.main import main as resolved
        return resolved
    if name == "IngestionScheduler":
        from apps.ingestion_app.schedules import IngestionScheduler as resolved
        return resolved
    if name == "WorkerSettings":
        from apps.ingestion_app.worker import WorkerSettings as resolved
        return resolved
    if name == "startup":
        from apps.ingestion_app.worker import startup as resolved
        return resolved
    if name == "shutdown":
        from apps.ingestion_app.worker import shutdown as resolved
        return resolved
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
