"""FastAPI control-plane boundary for ingestion."""

from .app import create_app

__all__ = ["create_app"]
