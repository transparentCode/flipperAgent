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


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _hash(payload: dict) -> str:
    return sha256(_json_bytes(payload).rstrip(b"\n")).hexdigest()


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    viewer = tmp_path / "viewer"
    (viewer / "src").mkdir(parents=True)
    standalone_module = (
        viewer
        / "node_modules"
        / "lightweight-charts"
        / "dist"
        / "lightweight-charts.standalone.production.mjs"
    )
    standalone_module.parent.mkdir(parents=True)
    standalone_module.write_text("export const standalone = true;\n", encoding="utf-8")
    (viewer / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (viewer / "src" / "main.js").write_text("export {};", encoding="utf-8")
    unbound_chart = _json_bytes({"bundle_id": None, "value": 1})
    model_data = _json_bytes(
        {
            "atr": {"first_valid_at": "2024-01-02T00:00:00Z"},
            "bars": [{"closed_at": "2024-01-02T00:00:00Z"}],
        }
    )
    prebind_members = []
    for name in _MEMBERS:
        data = (
            unbound_chart
            if name == "chart_payload.json"
            else model_data
            if name == "model_bars.json"
            else b"{}\n"
        )
        prebind_members.append(
            {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}
        )
    identity = {
        "atr": {"first_valid_at": "2024-01-02T00:00:00Z"},
        "bundle_id_basis_members": prebind_members,
        "chart_payload_identity_hash": _hash({"value": 1}),
        "members": prebind_members,
        "source_bars_sha256": prebind_members[0]["sha256"],
    }
    bundle_id = _hash(identity)
    bundle = tmp_path / bundle_id
    bundle.mkdir()
    actual_members = []
    for name in _MEMBERS:
        data = (
            _json_bytes({"bundle_id": bundle_id, "value": 1})
            if name == "chart_payload.json"
            else model_data
            if name == "model_bars.json"
            else b"{}\n"
        )
        (bundle / name).write_bytes(data)
        actual_members.append(
            {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}
        )
    manifest = {
        **identity,
        "bundle_id": bundle_id,
        "bundle_id_semantic_payload": identity,
        "members": actual_members,
    }
    (bundle / "manifest.json").write_bytes(_json_bytes(manifest))
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
        assert json.loads(response.read())["bundle_id"] == bundle.name

        connection.request(
            "GET",
            "/node_modules/lightweight-charts/dist/"
            "lightweight-charts.standalone.production.mjs",
        )
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/javascript")
        assert response.read() == b"export const standalone = true;\n"

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


def test_server_rejects_duplicate_manifest_keys(tmp_path: Path) -> None:
    viewer, bundle = _bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8").rstrip()
    manifest_path.write_text(
        raw[:-1] + ',"duplicate_probe":1,"duplicate_probe":2}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        make_server(viewer, bundle)
