"""Loopback-only static server for one verified Trendline V2 bundle."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .payload import (
    BUNDLE_SCHEMA_VERSION,
    PAYLOAD_SCHEMA_VERSION,
    _bundle_identity,
    _canonical_json_bytes,
    _is_sha256,
    _sha256,
    _validate_payload,
)
from .diagnostic_payload import (
    DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
    DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
    _bundle_identity as _diagnostic_bundle_identity,
    validate_diagnostic_payload,
)


_BUNDLE_MEMBERS = frozenset({"manifest.json", "chart_payload.json"})
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}
_ALLOWED_PATHS = frozenset(
    {
        "/",
        "/styles.css",
        "/dist/main.js",
        "/dist/candidate_filter.js",
        "/dist/contracts.js",
        "/dist/payload.js",
        "/dist/trendline_primitive.js",
        "/vendor/lightweight-charts.mjs",
        "/bundle/chart_payload.json",
    }
)
_MISSING = object()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        data = path.read_bytes()
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON file: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return parsed, data


def _validate_real_file(path: Path, *, field_name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{field_name} must be a regular non-symlink file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read {field_name}") from exc


def validate_bundle(bundle_path: str | Path) -> dict[str, object]:
    """Validate one exact viewer bundle before it is exposed over HTTP."""

    original = Path(bundle_path)
    if original.is_symlink():
        raise ValueError("bundle path must not be a symlink")
    bundle = original.resolve()
    if not bundle.is_dir():
        raise ValueError("bundle path must be a directory")
    actual_names = {entry.name for entry in bundle.iterdir()}
    if actual_names != _BUNDLE_MEMBERS:
        raise ValueError("bundle contains unexpected files")
    manifest_path = bundle / "manifest.json"
    payload_path = bundle / "chart_payload.json"
    _validate_real_file(manifest_path, field_name="manifest.json")
    _validate_real_file(payload_path, field_name="chart_payload.json")
    manifest, manifest_bytes = _load_json(manifest_path)
    payload, payload_bytes = _load_json(payload_path)
    if manifest_bytes != _canonical_json_bytes(manifest):
        raise ValueError("manifest bytes are not canonical")
    if payload_bytes != _canonical_json_bytes(payload):
        raise ValueError("chart payload bytes are not canonical")
    if set(manifest) != {"schema_version", "bundle_id", "payload_id", "members"}:
        raise ValueError("manifest keys mismatch")
    bundle_schema = manifest["schema_version"]
    if bundle_schema not in {BUNDLE_SCHEMA_VERSION, DIAGNOSTIC_BUNDLE_SCHEMA_VERSION}:
        raise ValueError("unsupported bundle schema")
    bundle_id = manifest["bundle_id"]
    payload_id = manifest["payload_id"]
    if not _is_sha256(bundle_id) or not _is_sha256(payload_id):
        raise ValueError("manifest identities must be lowercase SHA-256 values")
    if not isinstance(manifest["members"], list) or len(manifest["members"]) != 1:
        raise ValueError("manifest must contain exactly one payload member")
    member = manifest["members"][0]
    if not isinstance(member, dict) or set(member) != {"name", "sha256", "byte_length"}:
        raise ValueError("manifest member metadata is malformed")
    if member["name"] != "chart_payload.json":
        raise ValueError("manifest member name is invalid")
    if not _is_sha256(member["sha256"]):
        raise ValueError("manifest member SHA-256 is invalid")
    if type(member["byte_length"]) is not int or member["byte_length"] < 0:
        raise ValueError("manifest member byte length is invalid")
    if member["byte_length"] != len(payload_bytes) or member["sha256"] != _sha256(payload_bytes):
        raise ValueError("chart payload hash or length mismatch")
    if bundle_schema == BUNDLE_SCHEMA_VERSION:
        validated_payload = _validate_payload(payload)
        if validated_payload["schema_version"] != PAYLOAD_SCHEMA_VERSION:
            raise ValueError("unsupported chart payload schema")
        bundle_identity = _bundle_identity
    else:
        validated_payload = validate_diagnostic_payload(payload)
        if validated_payload["schema_version"] != DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION:
            raise ValueError("unsupported diagnostic payload schema")
        bundle_identity = _diagnostic_bundle_identity
    if validated_payload["payload_id"] != payload_id:
        raise ValueError("manifest payload_id does not match chart payload")
    manifest_semantics = {
        "schema_version": manifest["schema_version"],
        "payload_id": payload_id,
        "members": manifest["members"],
    }
    if bundle_identity(manifest_semantics) != bundle_id:
        raise ValueError("bundle_id does not match manifest semantic content")
    return manifest


def _loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _web_root_path(web_root: str | Path | None) -> Path:
    root = Path(web_root) if web_root is not None else Path(__file__).with_name("web")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("viewer web root must be a real directory")
    return root.resolve()


def _vendor_path(web_root: Path) -> Path:
    return web_root / "node_modules" / "lightweight-charts" / "dist" / (
        "lightweight-charts.standalone.production.mjs"
    )


def _requested_file(path: str, *, bundle: Path, web_root: Path) -> tuple[Path, str] | None:
    if path not in _ALLOWED_PATHS:
        return None
    if path == "/":
        return web_root / "index.html", "text/html; charset=utf-8"
    if path == "/styles.css":
        return web_root / "styles.css", _CONTENT_TYPES[".css"]
    if path == "/vendor/lightweight-charts.mjs":
        return _vendor_path(web_root), _CONTENT_TYPES[".mjs"]
    if path == "/bundle/chart_payload.json":
        return bundle / "chart_payload.json", _CONTENT_TYPES[".json"]
    return web_root / path.removeprefix("/"), _CONTENT_TYPES[".js"]


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
            data = _validate_real_file(path, field_name=request_path)
        except ValueError:
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
    def __init__(self, server_address: tuple[str, int], bundle: Path, web_root: Path):
        self.bundle = bundle
        self.web_root = web_root
        super().__init__(server_address, _ViewerHandler)


def make_server(
    bundle_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    web_root: str | Path | None = None,
) -> _ViewerHTTPServer:
    """Validate a bundle, then construct a loopback-only static server."""

    if not isinstance(host, str) or not _loopback_host(host):
        raise ValueError("viewer server may bind only to a loopback host")
    validate_bundle(bundle_path)
    return _ViewerHTTPServer(
        (host, port),
        Path(bundle_path).resolve(),
        _web_root_path(web_root),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Serve a Trendline V2 viewer bundle")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
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


__all__ = ["main", "make_server", "validate_bundle"]
