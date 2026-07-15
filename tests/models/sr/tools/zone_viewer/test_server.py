from __future__ import annotations

from hashlib import sha256
import http.client
import json
from pathlib import Path
import threading

import pytest

from libs.models.sr.tools.zone_viewer.server import make_server, validate_bundle


_MEMBERS = (
    "source_bars.json",
    "model_bars.json",
    "trace.json",
    "diagnostics.json",
    "chart_payload.json",
)


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    viewer = tmp_path / "viewer"
    (viewer / "src").mkdir(parents=True)
    (viewer / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (viewer / "src" / "main.js").write_text("export {};", encoding="utf-8")
    bundle = tmp_path / ("a" * 64)
    bundle.mkdir()
    members = []
    for name in _MEMBERS:
        data = ("{}\n" if name.endswith(".json") else "").encode()
        (bundle / name).write_bytes(data)
        members.append(
            {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}
        )
    manifest = {"bundle_id": bundle.name, "members": members}
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return viewer, bundle


def test_server_validates_bundle_and_serves_viewer_and_bundle(tmp_path: Path) -> None:
    viewer, bundle = _bundle(tmp_path)
    server = make_server(viewer, bundle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"<!doctype html>" in response.read()

        connection.request("GET", "/bundle/chart_payload.json")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("application/json")
        assert response.read() == b"{}\n"

        connection.request("GET", "/bundle/%2e%2e/manifest.json")
        response = connection.getresponse()
        assert response.status == 404
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert validate_bundle(bundle)["bundle_id"] == bundle.name


def test_server_rejects_tampered_bundle_before_binding(tmp_path: Path) -> None:
    viewer, bundle = _bundle(tmp_path)
    (bundle / "trace.json").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        make_server(viewer, bundle)
