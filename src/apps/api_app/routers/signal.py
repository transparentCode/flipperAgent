"""Signal API router shim to the modular signal_app package."""

from apps.signal_app.api.routes import router

__all__ = ["router"]
