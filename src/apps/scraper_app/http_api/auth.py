"""Bearer-token authentication for ``/v2``.

The token comes from the environment, else from a file that is re-read when its
mtime changes. A token shorter than 32 characters is rejected (one ERROR). The
token is never logged.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import Request

from apps.scraper_app.http_api.rules import ApiError
from apps.scraper_app.settings import API_READ_TOKEN_ENV, API_READ_TOKEN_FILE_ENV
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

MIN_TOKEN_LENGTH = 32


class TokenSource:
    def __init__(self, *, env_token: str = "", file_path: str | None = None) -> None:
        self._env_token = env_token.strip()
        self._path = Path(file_path) if file_path else None
        self._mtime: float | None = None
        self._file_token = ""
        self._complained: set[str] = set()

    def _usable(self, token: str, origin: str) -> str | None:
        if not token:
            return None
        if len(token) < MIN_TOKEN_LENGTH:
            if origin not in self._complained:
                self._complained.add(origin)
                logger.error(
                    "scraper API read token from %s is shorter than %d characters; "
                    "/v2 stays unavailable",
                    origin,
                    MIN_TOKEN_LENGTH,
                )
            return None
        return token

    def current(self) -> str | None:
        if self._env_token:
            return self._usable(self._env_token, "environment")
        if self._path is None:
            return None
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            self._mtime, self._file_token = None, ""
            return None
        if mtime != self._mtime:
            try:
                self._file_token = self._path.read_text(encoding="utf-8").strip()
            except OSError:
                self._file_token = ""
            self._mtime = mtime
            self._complained.discard("file")
        return self._usable(self._file_token, "file")


def token_source_from_environment(
    environ: Mapping[str, str] | None = None,
) -> TokenSource:
    env = os.environ if environ is None else environ
    return TokenSource(
        env_token=env.get(API_READ_TOKEN_ENV, ""),
        file_path=env.get(API_READ_TOKEN_FILE_ENV) or None,
    )


def make_auth_dependency(tokens: TokenSource):
    async def require_token(request: Request) -> None:
        expected = tokens.current()
        if expected is None:
            raise ApiError(
                503, "auth_not_configured", "the read token is not configured"
            )
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.strip().encode(), expected.encode()
        ):
            raise ApiError(
                401,
                "unauthorized",
                "a valid bearer token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_token


__all__ = [
    "MIN_TOKEN_LENGTH",
    "TokenSource",
    "make_auth_dependency",
    "token_source_from_environment",
]
