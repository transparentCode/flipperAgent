"""portfolio_app entrypoint for the internal portfolio observability API."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("PORTFOLIO_API_HOST", "0.0.0.0")
    port = int(os.environ.get("PORTFOLIO_API_PORT", "8094"))
    uvicorn.run("apps.portfolio_app.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
