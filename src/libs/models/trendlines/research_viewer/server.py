"""Loopback-only static server for one verified research viewer bundle."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import shutil
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlsplit

from .bundle import validate_viewer_bundle
from .contracts import TrendlineViewerContractError


_ALLOWED_PATHS = frozenset(
    {
        "/",
        "/styles.css",
        "/dist/main.js",
        "/dist/contracts.js",
        "/dist/payload.js",
        "/dist/trendline_primitive.js",
        "/vendor/lightweight-charts.mjs",
        "/bundle/chart_payload.json",
    }
)
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


def _loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _real_file(path: Path, field_name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrendlineViewerContractError(
            f"{field_name} must be a regular non-symlink file"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TrendlineViewerContractError(f"cannot read {field_name}") from exc


def _web_root(web_root: str | Path | None) -> Path:
    root = Path(web_root) if web_root is not None else Path(__file__).with_name("web")
    if root.is_symlink() or not root.is_dir():
        raise TrendlineViewerContractError("viewer web root must be a real directory")
    return root.resolve()


def _vendor_path(root: Path) -> Path:
    return root / "node_modules" / "lightweight-charts" / "dist" / (
        "lightweight-charts.standalone.production.mjs"
    )


def _requested_file(path: str, *, bundle: Path, web_root: Path) -> tuple[Path, str] | None:
    if path not in _ALLOWED_PATHS:
        return None
    if path == "/":
        return web_root / "index.html", "text/html; charset=utf-8"
    if path == "/styles.css":
        return web_root / "styles.css", "text/css; charset=utf-8"
    if path == "/vendor/lightweight-charts.mjs":
        return _vendor_path(web_root), "text/javascript; charset=utf-8"
    if path == "/bundle/chart_payload.json":
        return bundle / "chart_payload.json", "application/json; charset=utf-8"
    return web_root / path.removeprefix("/"), "text/javascript; charset=utf-8"


def _safe_path(path: Path, *, root: Path) -> bool:
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


class _ViewerHandler(BaseHTTPRequestHandler):
    server: "_ViewerHTTPServer"

    def _respond(self, *, include_body: bool) -> None:
        request_path = unquote(urlsplit(self.path).path)
        if ".." in request_path.split("/"):
            self.send_error(404)
            return
        requested = _requested_file(
            request_path,
            bundle=self.server.bundle,
            web_root=self.server.web_root,
        )
        if requested is None:
            self.send_error(404)
            return
        path, content_type = requested
        root = self.server.bundle if request_path.startswith("/bundle/") else self.server.web_root
        if not _safe_path(path, root=root):
            self.send_error(404)
            return
        try:
            data = _real_file(path, request_path)
        except TrendlineViewerContractError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._respond(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._respond(include_body=False)

    def log_message(self, format: str, *args: object) -> None:
        return


class _ViewerHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], bundle: Path, web_root: Path):
        self.bundle = bundle
        self.web_root = web_root
        super().__init__(address, _ViewerHandler)


def make_server(
    bundle_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    web_root: str | Path | None = None,
) -> _ViewerHTTPServer:
    """Validate bundle and construct a loopback-only server."""

    if not isinstance(host, str) or not _loopback_host(host):
        raise TrendlineViewerContractError("viewer server may bind only to loopback")
    bundle = Path(bundle_path)
    validate_viewer_bundle(bundle)
    root = _web_root(web_root)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise TrendlineViewerContractError("viewer port must be an integer in [0, 65535]")
    return _ViewerHTTPServer((host, port), bundle.resolve(), root)


class TrendlinesResearchViewerSession:
    """Own one daemon-thread loopback server and optional temporary directory."""

    def __init__(
        self,
        bundle_path: str | Path,
        *,
        web_root: str | Path | None = None,
        cleanup_directory: str | Path | None = None,
    ) -> None:
        self._server = make_server(bundle_path, web_root=web_root, port=0)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._cleanup_directory = (
            Path(cleanup_directory) if cleanup_directory is not None else None
        )
        self._closed = False
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        host_text = "127.0.0.1" if host == "localhost" else host
        return f"http://{host_text}:{port}/"

    @property
    def server_address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)
        if self._cleanup_directory is not None:
            shutil.rmtree(self._cleanup_directory, ignore_errors=False)

    def __enter__(self) -> "TrendlinesResearchViewerSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Serve a trendlines research viewer bundle")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8766, type=int)
    args = parser.parse_args()
    server = make_server(args.bundle, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


__all__ = ["TrendlinesResearchViewerSession", "main", "make_server"]
