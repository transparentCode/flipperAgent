from __future__ import annotations

import ast
import http.client
import json
from pathlib import Path
import subprocess
import threading

import pytest

from libs.models.trendline_v2.tools.viewer import write_viewer_bundle
from libs.models.trendline_v2.tools.viewer.server import make_server, validate_bundle
from libs.models.trendline_v2.tools.viewer.diagnostic_export import (
    build_verified_diagnostic_payload,
)
from libs.models.trendline_v2.tools.viewer.diagnostic_payload import write_diagnostic_bundle

from .test_payload import _result


def _web_root(tmp_path: Path) -> Path:
    root = tmp_path / "web"
    (root / "dist").mkdir(parents=True, exist_ok=True)
    vendor = root / "node_modules" / "lightweight-charts" / "dist"
    vendor.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    for name in ("main.js", "contracts.js", "payload.js", "trendline_primitive.js"):
        (root / "dist" / name).write_text(f"export const file = '{name}';", encoding="utf-8")
    (vendor / "lightweight-charts.standalone.production.mjs").write_text(
        "export const tvlc = true;", encoding="utf-8"
    )
    return root


def _server(tmp_path: Path):
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    server = make_server(bundle, port=0, web_root=_web_root(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, bundle


def _request(server, method: str, path: str):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request(method, path)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response, body


def test_server_serves_only_allowlisted_assets_and_supports_head(tmp_path: Path) -> None:
    server, thread, bundle = _server(tmp_path)
    try:
        for path in (
            "/",
            "/styles.css",
            "/dist/main.js",
            "/dist/contracts.js",
            "/dist/payload.js",
            "/dist/trendline_primitive.js",
            "/vendor/lightweight-charts.mjs",
            "/bundle/chart_payload.json",
        ):
            response, body = _request(server, "GET", path)
            assert response.status == 200, path
            assert body
        response, body = _request(server, "HEAD", "/bundle/chart_payload.json")
        assert response.status == 200
        assert body == b""
        assert int(response.getheader("Content-Length")) > 0
        for path in (
            "/manifest.json",
            "/node_modules/lightweight-charts/package.json",
            "/bundle/../manifest.json",
            "/bundle/%2e%2e/manifest.json",
            "/not-allowed",
        ):
            response, _ = _request(server, "GET", path)
            assert response.status == 404, path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert validate_bundle(bundle)["payload_id"]


def test_server_defaults_to_loopback_and_rejects_non_loopback(tmp_path: Path) -> None:
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    with pytest.raises(ValueError, match="loopback"):
        make_server(bundle, host="0.0.0.0", web_root=_web_root(tmp_path))
    with pytest.raises(ValueError, match="loopback"):
        make_server(bundle, host="192.168.1.10", web_root=_web_root(tmp_path))


def test_server_rejects_duplicate_keys_and_tampered_bundle(tmp_path: Path) -> None:
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    manifest_path = bundle / "manifest.json"
    original = manifest_path.read_text(encoding="utf-8").rstrip()
    manifest_path.write_text(
        original[:-1]
        + ',"bundle_id":"'
        + "0" * 64
        + '","bundle_id":"'
        + "1" * 64
        + '"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        validate_bundle(bundle)

    bundle = write_viewer_bundle(_result(), tmp_path / "bundle2")
    payload_path = bundle / "chart_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["asset"] = "ETHUSDT"
    payload_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash or length mismatch"):
        validate_bundle(bundle)

    bundle = write_viewer_bundle(_result(), tmp_path / "bundle3")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["payload_id"] = "0" * 64
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="payload_id"):
        validate_bundle(bundle)

    bundle = write_viewer_bundle(_result(), tmp_path / "bundle4")
    (bundle / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected files"):
        validate_bundle(bundle)

    bundle = write_viewer_bundle(_result(), tmp_path / "bundle5")
    payload_path = bundle / "chart_payload.json"
    payload_path.write_text(
        payload_path.read_text(encoding="utf-8").replace(
            '"asset":"BTCUSDT"', '"asset":NaN', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite|canonical|hash"):
        validate_bundle(bundle)


def test_server_rejects_symlink_bundle_members(tmp_path: Path) -> None:
    bundle = write_viewer_bundle(_result(), tmp_path / "bundle")
    target = bundle / "chart_payload.json"
    content = target.read_bytes()
    target.unlink()
    source = tmp_path / "payload-source.json"
    source.write_bytes(content)
    target.symlink_to(source)
    with pytest.raises(ValueError, match="regular non-symlink"):
        validate_bundle(bundle)


def test_viewer_import_boundaries_are_one_way() -> None:
    repository = Path(__file__).parents[3]
    viewer_root = repository / "src" / "libs" / "models" / "trendline_v2" / "tools" / "viewer"
    forbidden = (
        "libs.models.sr",
        "libs.models.regime_v2",
        "libs.models.trendline_family",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "app.trendlines",
        "tracking",
        "storage",
        "research",
    )
    for path in viewer_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not any(
            name == token or name.startswith(f"{token}.")
            for token in forbidden
            for name in imported
        ), path
    for path in (repository / "src" / "libs" / "models" / "trendline_v2").rglob("*.py"):
        assert "trendline_v2_viewer" not in path.read_text(encoding="utf-8")
    for path in (viewer_root / "web" / "src").rglob("*.ts"):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in ("react", "vue", "svelte", "websocket"))


def test_server_serves_verified_diagnostic_payload_and_dom_contract(tmp_path: Path) -> None:
    payload = build_verified_diagnostic_payload()
    bundle = write_diagnostic_bundle(payload, tmp_path / "diagnostic")
    server = make_server(bundle, port=0, web_root=_web_root(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response, body = _request(server, "GET", "/bundle/chart_payload.json")
        assert response.status == 200
        assert json.loads(body)["schema_version"] == "trendline_v2_r5_diagnostic_viewer_payload_v1"
        for path in ("/", "/styles.css", "/dist/main.js"):
            response, body = _request(server, "GET", path)
            assert response.status == 200
            assert body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_entrypoint_contains_candle_and_two_line_rendering_contract() -> None:
    repository = Path(__file__).parents[5]
    source = (repository / "src" / "libs" / "models" / "trendline_v2" / "tools" / "viewer" / "web" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "CandlestickSeries" in source
    assert "new TrendlinePrimitive" in source
    assert "diagnostic.lines.length" in source


def test_viewer_is_model_local_and_does_not_track_node_modules() -> None:
    repository = Path(__file__).parents[5]
    assert not (repository / "src" / "apps" / "trendline_v2_viewer").exists()
    assert not (repository / "tests" / "apps" / "trendline_v2_viewer").exists()
    tracked = subprocess.run(
        ["git", "ls-files", "node_modules", "src/libs/models/trendline_v2/tools/viewer/**/node_modules"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout == ""
