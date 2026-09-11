"""risk_app entrypoint for the internal risk observability API."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("RISK_API_HOST", "0.0.0.0")
    port = int(os.environ.get("RISK_API_PORT", "8095"))
    uvicorn.run("apps.risk_app.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
