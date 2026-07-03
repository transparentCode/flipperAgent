"""alert_app entrypoint for the internal alert API."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("ALERT_API_HOST", "0.0.0.0")
    port = int(os.environ.get("ALERT_API_PORT", "8096"))
    uvicorn.run("apps.alert_app.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()

