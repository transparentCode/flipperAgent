"""Cookie file for logged-in datasets. Names and values are never logged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

COOKIE_DOMAIN = "coinglass.com"
_ALLOWED_KEYS = {
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
}
_SAME_SITE = {"Lax", "Strict", "None"}


def _in_scope(domain: object) -> bool:
    if not isinstance(domain, str):
        return False
    host = domain.strip().lstrip(".").lower()
    return host == COOKIE_DOMAIN or host.endswith("." + COOKIE_DOMAIN)


def _normalize(cookie: dict[str, Any]) -> dict[str, Any] | None:
    """Same file format as the old browser runtime; ``None`` when unusable."""
    if not isinstance(cookie.get("name"), str) or not isinstance(
        cookie.get("value"), str
    ):
        return None
    if not _in_scope(cookie.get("domain")):
        return None
    out = dict(cookie)
    expiry = out.pop("expirationDate", None)
    if "expires" not in out and isinstance(expiry, (int, float)):
        out["expires"] = float(expiry)
    same_site = out.get("sameSite")
    if isinstance(same_site, str):
        canonical = same_site[:1].upper() + same_site[1:].lower()
        if canonical in _SAME_SITE:
            out["sameSite"] = canonical
        else:
            out.pop("sameSite", None)
    return {k: v for k, v in out.items() if k in _ALLOWED_KEYS and v is not None}


class CookieStore:
    """Reads the cookie file; re-reads only when its mtime or size changes."""

    def __init__(self, path: str | None) -> None:
        self._path = None if not path else Path(path)
        self._stamp: tuple[int, int] | None = None
        self._cookies: list[dict[str, Any]] = []

    def load(self) -> list[dict[str, Any]]:
        """CDP cookie params for ``coinglass.com`` and its subdomains only."""
        if self._path is None:
            return []
        try:
            stat = self._path.stat()
        except OSError:
            self._reset()
            return []
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._stamp:
            return [dict(c) for c in self._cookies]
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise TypeError("not a list")
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("cookie file unreadable: %s", type(exc).__name__)
            self._reset()
            self._stamp = stamp
            return []
        usable = [n for c in raw if isinstance(c, dict) and (n := _normalize(c))]
        logger.info(
            "cookie file loaded: %d entries, %d in scope", len(raw), len(usable)
        )
        self._stamp = stamp
        self._cookies = usable
        return [dict(c) for c in usable]

    def _reset(self) -> None:
        self._stamp = None
        self._cookies = []


__all__ = ["COOKIE_DOMAIN", "CookieStore"]
