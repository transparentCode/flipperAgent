"""FastAPI surface for scraper consumers."""

from apps.scraper_app.api.app import app, create_app

__all__ = ["app", "create_app"]
