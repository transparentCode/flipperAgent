"""Loopback-only static server for one verified SR zone evidence bundle."""

from __future__ import annotations

from hashlib import sha256
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import math
from pathlib import Path
import posixpath
from urllib.parse import unquote, urlsplit


_BUNDLE_MEMBERS = frozenset(
    {
        "manifest.json",
        "source_bars.json",
        "model_bars.json",
        "trace.json",
        "diagnostics.json",
        "chart_payload.json",
    }
)
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}
_MISSING = object()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON file: {path}: {exc}") from exc


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _canonical_value(value: object) -> object:
    if value is None or type(value) is bool or type(value) is int or type(value) is str:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return 0.0 if value == 0.0 else value
    if type(value) is list:
        return [_canonical_value(item) for item in value]
    if type(value) is dict:
        return {
            key: _canonical_value(item)
            for key, item in sorted(value.items())
        }
    raise ValueError("unsupported JSON identity value")


def _deterministic_hash(value: object) -> str:
    canonical = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _chart_payload_identity(payload: dict[str, object]) -> str:
    identity = dict(payload)
    identity.pop("bundle_id", None)
    return _deterministic_hash(identity)


def _validate_manifest_identity(
    manifest: dict[str, object],
    chart_payload: dict[str, object],
    model_payload: dict[str, object],
) -> None:
    identity = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(identity) is not dict or type(bundle_id) is not str:
        raise ValueError("bundle identity payload is missing")
    if _deterministic_hash(identity) != bundle_id:
        raise ValueError("bundle_id does not match bundle_id_semantic_payload")
    expected_keys = set(identity) | {"bundle_id", "bundle_id_semantic_payload"}
    if set(manifest) != expected_keys:
        raise ValueError("manifest semantic fields do not match bundle identity")
    for key, expected in identity.items():
        if key == "members":
            continue
        if manifest.get(key, _MISSING) != expected:
            raise ValueError(f"manifest semantic field mismatch: {key}")

    actual_members = manifest.get("members")
    identity_members = identity.get("members")
    if type(actual_members) is not list or type(identity_members) is not list:
        raise ValueError("bundle identity members are malformed")
    if identity.get("bundle_id_basis_members") != identity_members:
        raise ValueError("bundle identity basis members do not match members")
    actual_by_name = {member["name"]: member for member in actual_members}
    identity_by_name = {
        member.get("name"): member
        for member in identity_members
        if type(member) is dict
    }
    if set(actual_by_name) != set(identity_by_name):
        raise ValueError("bundle identity member names do not match")
    for name in actual_by_name:
        if name != "chart_payload.json" and actual_by_name[name] != identity_by_name[name]:
            raise ValueError(f"bundle identity member mismatch: {name}")
    if manifest.get("source_bars_sha256") != actual_by_name["source_bars.json"]["sha256"]:
        raise ValueError("source_bars_sha256 does not match member metadata")
    if chart_payload.get("bundle_id") != bundle_id:
        raise ValueError("chart payload bundle_id does not match manifest")
    if _chart_payload_identity(chart_payload) != manifest.get("chart_payload_identity_hash"):
        raise ValueError("chart payload identity does not match manifest")
    model_bars = model_payload.get("bars")
    if type(model_bars) is not list or not model_bars or type(model_bars[0]) is not dict:
        raise ValueError("model bars are malformed")
    if model_payload.get("atr") != manifest.get("atr"):
        raise ValueError("model ATR provenance does not match manifest")
    atr = manifest.get("atr")
    if type(atr) is not dict or atr.get("first_valid_at") != model_bars[0].get("closed_at"):
        raise ValueError("ATR first_valid_at does not match first model bar closed_at")


def validate_bundle(bundle_path: str | Path) -> dict[str, object]:
    """Validate the selected bundle without importing SR model code."""
    bundle = Path(bundle_path).resolve()
    if not bundle.is_dir():
        raise ValueError("bundle path must be a directory")
    manifest = _load_json(bundle / "manifest.json")
    if type(manifest) is not dict:
        raise ValueError("manifest must be a mapping")
    bundle_id = manifest.get("bundle_id")
    if type(bundle_id) is not str or bundle.name != bundle_id:
        raise ValueError("bundle directory does not match manifest bundle_id")
    members = manifest.get("members")
    if type(members) is not list:
        raise ValueError("manifest members must be a list")
    if any(type(member) is not dict for member in members):
        raise ValueError("manifest members must contain mappings")
    names = [member.get("name") for member in members]
    if any(type(name) is not str for name in names):
        raise ValueError("bundle member names must be strings")
    if set(names) != _BUNDLE_MEMBERS - {"manifest.json"} or len(names) != 5:
        raise ValueError("manifest members do not match bundle schema")
    if {path.name for path in bundle.iterdir()} != _BUNDLE_MEMBERS:
        raise ValueError("bundle contains unexpected files")
    for member in members:
        if set(member) != {"name", "sha256", "byte_length"}:
            raise ValueError("malformed bundle member metadata")
        name = member["name"]
        digest = member["sha256"]
        byte_length = member["byte_length"]
        if (
            type(name) is not str
            or type(digest) is not str
            or type(byte_length) is not int
            or byte_length < 0
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or "/" in name
            or "\\" in name
            or ".." in Path(name).parts
        ):
            raise ValueError("malformed bundle member metadata")
        member_path = bundle / name
        if not member_path.is_file() or member_path.is_symlink():
            raise ValueError("bundle member must be a regular file")
        data = member_path.read_bytes()
        if len(data) != byte_length or sha256(data).hexdigest() != digest:
            raise ValueError(f"bundle member hash mismatch: {name}")
    chart_payload = _load_json(bundle / "chart_payload.json")
    if type(chart_payload) is not dict:
        raise ValueError("chart payload must be a mapping")
    model_payload = _load_json(bundle / "model_bars.json")
    if type(model_payload) is not dict:
        raise ValueError("model payload must be a mapping")
    _validate_manifest_identity(manifest, chart_payload, model_payload)
    return manifest


def _safe_file(root: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.startswith("/"):
        raise ValueError("invalid relative path")
    normalized = posixpath.normpath(relative_path)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        raise ValueError("path traversal is not allowed")
    if "\\" in normalized:
        raise ValueError("invalid path separator")
    root = root.resolve()
    candidate = (root / normalized).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escaped serving root")
    if not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError(relative_path)
    return candidate


class _ViewerHandler(BaseHTTPRequestHandler):
    viewer_root: Path
    bundle_root: Path

    def _serve(self, *, head_only: bool = False) -> None:
        request_path = unquote(urlsplit(self.path).path)
        try:
            if request_path == "/" or request_path == "":
                file_path = _safe_file(self.viewer_root, "index.html")
            elif request_path.startswith("/bundle/"):
                relative = request_path.removeprefix("/bundle/")
                if relative not in _BUNDLE_MEMBERS:
                    raise FileNotFoundError(relative)
                file_path = _safe_file(self.bundle_root, relative)
            else:
                file_path = _safe_file(self.viewer_root, request_path.removeprefix("/"))
        except (ValueError, FileNotFoundError):
            self.send_error(404, "Not found")
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._serve()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
        self._serve(head_only=True)

    def log_message(self, format: str, *args: object) -> None:
        return


def make_server(
    viewer_root: str | Path,
    bundle_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """Build a verified loopback server; no server starts during construction."""
    viewer = Path(viewer_root).resolve()
    if not viewer.is_dir():
        raise ValueError("viewer_root must be a directory")
    bundle = Path(bundle_path).resolve()
    validate_bundle(bundle)

    class Handler(_ViewerHandler):
        pass

    Handler.viewer_root = viewer
    Handler.bundle_root = bundle
    return ThreadingHTTPServer((host, port), Handler)


def serve_bundle(
    viewer_root: str | Path,
    bundle_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Serve one verified bundle until interrupted."""
    server = make_server(viewer_root, bundle_path, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = ["make_server", "serve_bundle", "validate_bundle"]
