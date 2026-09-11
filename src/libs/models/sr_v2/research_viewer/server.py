"""Loopback-only static server for one verified SR v2 viewer bundle."""

from __future__ import annotations

import ipaddress
import json
import shutil
import tempfile
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock, Thread
from typing import Self
from urllib.parse import parse_qs, unquote, urlsplit

from ..domain.identity import canonical_hash, canonical_json
from .bundle import MAX_BUNDLE_BYTES, select_viewer_payload, validate_viewer_bundle
from .projection import ProjectionIndex

_ALLOWED_PATHS = frozenset(
    {
        "/",
        "/index.html",
        "/styles.css",
        "/dist/main.js",
        "/dist/payload_utils.js",
        "/vendor/lightweight-charts.mjs",
        "/bundle/chart_payload.json",
        "/bundle/inspection.json",
        "/bundle/zone_detail.json",
        "/bundle/lineage_history.json",
    }
)
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}
_CHART_QUERY = frozenset({"source_timeframe"})
_INSPECTION_QUERY = frozenset({"source_timeframe", "cutoff"})
_ZONE_QUERY = frozenset({"source_timeframe", "zone_id", "cutoff"})
_HISTORY_QUERY = frozenset({"source_timeframe", "cutoff"})


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _root(path: str | Path | None) -> Path:
    value = Path(path) if path is not None else Path(__file__).with_name("web")
    if value.is_symlink() or not value.is_dir():
        raise ValueError("viewer web root must be a regular directory")
    return value.resolve()


def _vendor(root: Path) -> Path:
    return root / "node_modules" / "lightweight-charts" / "dist" / "lightweight-charts.standalone.production.mjs"


def _safe(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            return False
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _query_values(query: str, expected: frozenset[str]) -> dict[str, str] | None:
    try:
        parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if set(parsed) != set(expected) or any(len(values) != 1 or not values[0] for values in parsed.values()):
        return None
    return {key: values[0] for key, values in parsed.items()}


def _json_response(semantic: Mapping[str, object]) -> bytes:
    body = {**semantic, "response_id": canonical_hash(semantic)}
    data = canonical_json(body).encode("utf-8")
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError("viewer response exceeds size limit")
    return data


_OWNERSHIP_SENTINEL = ".sr_v2_viewer_owned"
_OWNERSHIP_VALUE = "sr_v2_viewer_workspace_v1\n"


def create_owned_viewer_workspace(parent: str | Path | None = None) -> tuple[Path, Path]:
    """Create a unique workspace and bundle child owned by the viewer session."""

    parent_path = None if parent is None else Path(parent)
    if parent_path is not None and (parent_path.is_symlink() or not parent_path.is_dir()):
        raise ValueError("viewer workspace parent must be a regular directory")
    root = Path(tempfile.mkdtemp(prefix="sr_v2_viewer_", dir=None if parent_path is None else str(parent_path)))
    (root / _OWNERSHIP_SENTINEL).write_text(_OWNERSHIP_VALUE, encoding="utf-8")
    return root, root / "bundle"


def _validate_owned_cleanup(bundle: Path, cleanup: Path) -> None:
    if cleanup.is_symlink() or not cleanup.is_dir():
        raise ValueError("viewer cleanup directory must be a regular owned directory")
    sentinel = cleanup / _OWNERSHIP_SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != _OWNERSHIP_VALUE:
        raise ValueError("viewer cleanup directory lacks its ownership sentinel")
    if bundle.parent.resolve() != cleanup.resolve() or bundle.name != "bundle":
        raise ValueError("viewer cleanup must own exactly the viewer bundle child")


class _Handler(BaseHTTPRequestHandler):
    server: _ViewerHTTPServer

    def _file(self) -> tuple[Path, Path, str, str | None, str | None] | None:
        parsed = urlsplit(self.path)
        request = unquote(parsed.path)
        if request not in _ALLOWED_PATHS or ".." in request.split("/"):
            return None
        query = parsed.query
        requested_timeframe: str | None = None
        route: str | None = None
        if request in {"/", "/index.html"}:
            values = _query_values(query, _CHART_QUERY)
            if values is None or values["source_timeframe"] not in self.server.timeframes:
                return None
            requested_timeframe = values["source_timeframe"]
        elif request == "/bundle/chart_payload.json":
            values = _query_values(query, _CHART_QUERY)
            if values is None or values["source_timeframe"] not in self.server.timeframes:
                return None
            requested_timeframe = values["source_timeframe"]
            route = "chart"
        elif request == "/bundle/inspection.json":
            values = _query_values(query, _INSPECTION_QUERY)
            if values is None or values["source_timeframe"] not in self.server.timeframes:
                return None
            requested_timeframe = values["source_timeframe"]
            route = f"inspection:{values['cutoff']}"
        elif request == "/bundle/zone_detail.json":
            values = _query_values(query, _ZONE_QUERY)
            if values is None or values["source_timeframe"] not in self.server.timeframes:
                return None
            requested_timeframe = values["source_timeframe"]
            route = f"zone:{values['zone_id']}:{values['cutoff']}"
        elif request == "/bundle/lineage_history.json":
            values = _query_values(query, _HISTORY_QUERY)
            if values is None or values["source_timeframe"] not in self.server.timeframes:
                return None
            requested_timeframe = values["source_timeframe"]
            route = f"history:{values['cutoff']}"
        elif query:
            return None
        if request in {"/", "/index.html", "/styles.css", "/dist/main.js", "/dist/payload_utils.js"}:
            relative = "index.html" if request == "/" else request.removeprefix("/")
            path = self.server.web_root / relative
            return path, self.server.web_root, _CONTENT_TYPES.get(path.suffix, "application/octet-stream"), requested_timeframe, None
        if request == "/vendor/lightweight-charts.mjs":
            path = _vendor(self.server.web_root)
            return path, self.server.web_root, _CONTENT_TYPES[".mjs"], requested_timeframe, None
        return self.server.bundle / "chart_payload.json", self.server.bundle, _CONTENT_TYPES[".json"], requested_timeframe, route

    def _dynamic_body(self, route: str, timeframe: str) -> bytes:
        parsed = urlsplit(self.path)
        query = _query_values(
            parsed.query,
            _CHART_QUERY
            if route == "chart"
            else _INSPECTION_QUERY
            if route.startswith("inspection:")
            else _HISTORY_QUERY
            if route.startswith("history:")
            else _ZONE_QUERY,
        )
        if query is None or query["source_timeframe"] != timeframe:
            raise ValueError("viewer route query is invalid")
        if route == "chart":
            return canonical_json(select_viewer_payload(self.server.payload, timeframe)).encode("utf-8")
        if route.startswith("inspection:"):
            semantic = self.server.projection_index.project_inspection(timeframe, query["cutoff"])
        elif route.startswith("history:"):
            semantic = self.server.projection_index.project_lineage_history(timeframe, query["cutoff"])
        else:
            semantic = self.server.projection_index.project_zone_detail(
                timeframe,
                query["zone_id"],
                query["cutoff"],
            )
        return _json_response(semantic)

    def _respond(self, include_body: bool) -> None:
        requested = self._file()
        if requested is None:
            self.send_error(404)
            return
        path, root, content_type, timeframe, route = requested
        if route is not None:
            try:
                builder = lambda: self._dynamic_body(route, timeframe or "")
                if route.startswith("history:"):
                    data = builder()
                else:
                    data = self.server.cached_response((route, timeframe), builder)
            except (TypeError, ValueError, KeyError):
                self.send_error(404)
                return
        else:
            if not _safe(path, root) or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BUNDLE_BYTES:
                self.send_error(404)
                return
            data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_GET(self) -> None:
        self._respond(True)

    def do_HEAD(self) -> None:
        self._respond(False)

    def log_message(self, *_args: object) -> None:
        return


class _ViewerHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], bundle: Path, web_root: Path):
        self.bundle = bundle
        self.web_root = web_root
        self.payload = validate_viewer_bundle(bundle)
        self.evidence = json.loads((bundle / "evidence_index.json").read_bytes())
        self.projection_index = ProjectionIndex(self.evidence, self.payload)
        self.timeframes = tuple(self.payload["configured_timeframes"])
        self._response_cache: dict[tuple[str, str | None], bytes] = {}
        self._response_lock = RLock()
        super().__init__(address, _Handler)

    def cached_response(self, key: tuple[str, str | None], builder: object) -> bytes:
        with self._response_lock:
            cached = self._response_cache.get(key)
            if cached is not None:
                return cached
            if not callable(builder):
                raise TypeError("viewer response builder must be callable")
            value = builder()
            if not isinstance(value, bytes) or len(value) > MAX_BUNDLE_BYTES:
                raise ValueError("viewer response is invalid")
            self._response_cache[key] = value
            return value


def make_server(
    bundle_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
) -> _ViewerHTTPServer:
    if not isinstance(host, str) or not _loopback(host):
        raise ValueError("viewer server may bind only to loopback")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("viewer port must be an integer in [0, 65535]")
    bundle_input = Path(bundle_path)
    if bundle_input.is_symlink():
        raise ValueError("viewer bundle root must not be a symlink")
    validate_viewer_bundle(bundle_input)
    bundle = bundle_input.resolve()
    root = _root(web_root)
    for relative in (
        "index.html",
        "styles.css",
        "dist/main.js",
        "dist/payload_utils.js",
        "node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs",
    ):
        path = root / relative
        if not _safe(path, root) or path.is_symlink() or not path.is_file():
            raise ValueError(f"viewer resource is unavailable: {relative}")
        if path.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError(f"viewer resource is too large: {relative}")
    return _ViewerHTTPServer((host, port), bundle, root)


class SRV2ResearchViewerSession:
    """Own one ephemeral loopback server and close it idempotently."""

    def __init__(self, bundle_path: str | Path, *, web_root: str | Path | None = None, cleanup_directory: str | Path | None = None):
        bundle = Path(bundle_path)
        cleanup = None if cleanup_directory is None else Path(cleanup_directory)
        if cleanup is not None:
            _validate_owned_cleanup(bundle, cleanup)
        self._server = make_server(bundle, web_root=web_root, port=0)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._cleanup_directory = cleanup
        self._closed = False
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    @property
    def server_address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._cleanup_directory is not None and self._cleanup_directory.exists():
            _validate_owned_cleanup(self._server.bundle, self._cleanup_directory)
            shutil.rmtree(self._cleanup_directory, ignore_errors=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["SRV2ResearchViewerSession", "create_owned_viewer_workspace", "make_server"]
