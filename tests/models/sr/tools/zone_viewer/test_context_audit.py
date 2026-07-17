from __future__ import annotations

from hashlib import sha256
import http.client
import json
from pathlib import Path
import threading

from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.tools.zone_viewer.server import make_server, validate_bundle


def _bytes(payload: object) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _member(name: str, data: bytes) -> dict[str, object]:
    return {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}


def _context_bundle(tmp_path: Path) -> tuple[Path, Path]:
    viewer = tmp_path / "viewer"
    (viewer / "src").mkdir(parents=True)
    (viewer / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (viewer / "src" / "main.js").write_text("export {};", encoding="utf-8")
    audit = {"audit_id": "a" * 64, "case_count": 36, "cases": [{} for _ in range(36)]}
    chart_unbound = {
        "schema_version": "1.0",
        "bundle_id": None,
        "audit_id": audit["audit_id"],
        "casebook": {"case_count": 36, "cases": [{} for _ in range(36)]},
    }
    audit_bytes = _bytes(audit)
    chart_unbound_bytes = _bytes(chart_unbound)
    basis = (_member("audit.json", audit_bytes), _member("chart_payload.json", chart_unbound_bytes))
    semantic = {
        "schema_version": "1.0",
        "stage": "context_semantics_audit_development",
        "created_by": "test",
        "implementation_commit": "b" * 40,
        "config_hash": "c" * 64,
        "config": {},
        "trial_name": "test",
        "venue": "binance_usdm",
        "asset": "TAOUSDT",
        "timeframe": "1d",
        "purpose": "diagnostic_only",
        "audit_status": "COMPLETE",
        "audit_id": audit["audit_id"],
        "v19_bundle_id": "d" * 64,
        "v19_study_id": "e" * 64,
        "v19_disposition": "BASELINE_NOT_BETTER_THAN_NAIVE_NULL",
        "source_bundle_id": "f" * 64,
        "source_id": "1" * 64,
        "trace_id": "2" * 64,
        "case_count": 36,
        "comparison_count": 31,
        "chart_payload_identity_hash": deterministic_hash({key: value for key, value in chart_unbound.items() if key != "bundle_id"}),
        "bundle_id_basis_members": list(basis),
    }
    bundle_id = deterministic_hash(semantic)
    chart = {**chart_unbound, "bundle_id": bundle_id}
    chart_bytes = _bytes(chart)
    members = (_member("audit.json", audit_bytes), _member("chart_payload.json", chart_bytes))
    manifest = {**semantic, "bundle_id": bundle_id, "members": list(members), "bundle_id_semantic_payload": semantic}
    bundle = tmp_path / bundle_id
    bundle.mkdir()
    (bundle / "manifest.json").write_bytes(_bytes(manifest))
    (bundle / "audit.json").write_bytes(audit_bytes)
    (bundle / "chart_payload.json").write_bytes(chart_bytes)
    return viewer, bundle


def test_context_bundle_is_verified_and_served_with_exact_members(tmp_path: Path):
    viewer, bundle = _context_bundle(tmp_path)
    server = make_server(viewer, bundle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/bundle/audit.json")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("application/json")
        assert json.loads(response.read())["case_count"] == 36
        connection.request("GET", "/bundle/source_bars.json")
        assert connection.getresponse().status == 404
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert validate_bundle(bundle)["bundle_id"] == bundle.name
