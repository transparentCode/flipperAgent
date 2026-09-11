"""Source-backed R4/R5 diagnostic viewer export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_trendline_v2_causal_structural_reachability import (
    verify_reachability_bundle,
)
from scripts.analyze_trendline_v2_reachability_asymmetry_attribution import (
    verify_attribution_bundle,
)

from .diagnostic_payload import (
    DIAGNOSTIC_RAW_CANDLE_PATH,
    DIAGNOSTIC_RAW_CANDLE_SHA256,
    R4_DIAGNOSTIC_ID,
    R4_INVENTORY,
    R4_MANIFEST_ID,
    R5_ATTRIBUTION_ID,
    R5_INVENTORY,
    R5_MANIFEST_ID,
    DiagnosticViewerError,
    _bundle_identity,
    _canonical_json_bytes,
    _load_canonical_json,
    _sha256,
    build_diagnostic_payload,
    validate_diagnostic_bundle,
    write_diagnostic_bundle,
)


R4_ROOT = Path(
    "/tmp/trendline_v2_phase11r4_causal_structural_reachability/20260522_20260701"
)
R5_ROOT = Path(
    "/tmp/trendline_v2_phase11r5_reachability_asymmetry_attribution/20260522_20260701"
)
RAW_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11v1_model_local_tvlc_viewer/20260522_20260701"
)
OUTPUT_BUNDLE = OUTPUT_ROOT / "btcusdt_4h_support_budget1_checkpoint5"


def _source_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    r4_result = verify_reachability_bundle(R4_ROOT, source_backed=True)
    r5_result = verify_attribution_bundle(
        R5_ROOT,
        source_backed=True,
        r4_root=R4_ROOT,
    )
    if (
        r4_result["diagnostic_id"],
        r4_result["manifest_id"],
        r4_result["output_inventory_sha256"],
    ) != (R4_DIAGNOSTIC_ID, R4_MANIFEST_ID, R4_INVENTORY):
        raise DiagnosticViewerError("verified R4 identities do not match frozen source")
    if (
        r5_result["attribution_id"],
        r5_result["manifest_id"],
        r5_result["output_inventory_sha256"],
    ) != (R5_ATTRIBUTION_ID, R5_MANIFEST_ID, R5_INVENTORY):
        raise DiagnosticViewerError("verified R5 identities do not match frozen source")
    r4_diagnostic, _ = _load_canonical_json(R4_ROOT / "reachability_diagnostic.json")
    r5_attribution, _ = _load_canonical_json(
        R5_ROOT / "reachability_asymmetry_attribution.json"
    )
    raw_path = RAW_ROOT / DIAGNOSTIC_RAW_CANDLE_PATH
    raw_bytes = raw_path.read_bytes()
    if _sha256(raw_bytes) != DIAGNOSTIC_RAW_CANDLE_SHA256:
        raise DiagnosticViewerError("raw candle source hash mismatch")
    raw_payload, _ = _load_canonical_json(raw_path)
    return r4_diagnostic, r5_attribution, raw_payload, raw_bytes


def _render_bundle(payload: dict[str, object]) -> dict[str, bytes]:
    payload_bytes = _canonical_json_bytes(payload)
    member = {
        "name": "chart_payload.json",
        "sha256": _sha256(payload_bytes),
        "byte_length": len(payload_bytes),
    }
    manifest_semantics = {
        "schema_version": "trendline_v2_r5_diagnostic_viewer_bundle_v1",
        "payload_id": payload["payload_id"],
        "members": [member],
    }
    manifest = {
        **manifest_semantics,
        "bundle_id": _bundle_identity(manifest_semantics),
    }
    return {
        "chart_payload.json": payload_bytes,
        "manifest.json": _canonical_json_bytes(manifest),
    }


def build_verified_diagnostic_payload() -> dict[str, object]:
    r4_diagnostic, r5_attribution, raw_payload, raw_bytes = _source_inputs()
    return build_diagnostic_payload(
        r4_diagnostic,
        r5_attribution,
        raw_payload,
        raw_bytes=raw_bytes,
    )


def verify_diagnostic_bundle(root: Path = OUTPUT_BUNDLE) -> dict[str, object]:
    """Verify bundle structure, protected sources and exact derived bytes."""

    manifest = validate_diagnostic_bundle(root)
    expected = build_verified_diagnostic_payload()
    expected_files = _render_bundle(expected)
    for relative, expected_bytes in expected_files.items():
        if (root / relative).read_bytes() != expected_bytes:
            raise DiagnosticViewerError(f"diagnostic artifact mismatch: {relative}")
    if manifest["payload_id"] != expected["payload_id"]:
        raise DiagnosticViewerError("diagnostic manifest payload mismatch")
    return {
        "status": "R5_DIAGNOSTIC_VIEWER_VERIFIED",
        "payload_id": expected["payload_id"],
        "bundle_id": manifest["bundle_id"],
        "member_count": len(manifest["members"]),
        "r4_diagnostic_id": R4_DIAGNOSTIC_ID,
        "r4_manifest_id": R4_MANIFEST_ID,
        "r4_inventory": R4_INVENTORY,
        "r5_attribution_id": R5_ATTRIBUTION_ID,
        "r5_manifest_id": R5_MANIFEST_ID,
        "r5_inventory": R5_INVENTORY,
        "raw_candle_sha256": DIAGNOSTIC_RAW_CANDLE_SHA256,
    }


def generate_diagnostic_bundle(root: Path = OUTPUT_BUNDLE) -> dict[str, object]:
    """Generate one frozen local bundle; no provider or network path exists here."""

    if root.exists():
        raise DiagnosticViewerError("diagnostic output already exists; refusing rerun")
    payload = build_verified_diagnostic_payload()
    write_diagnostic_bundle(payload, root)
    return verify_diagnostic_bundle(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.generate == args.verify:
        parser.error("select exactly one of --generate or --verify")
    result = generate_diagnostic_bundle() if args.generate else verify_diagnostic_bundle()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "OUTPUT_BUNDLE",
    "OUTPUT_ROOT",
    "build_verified_diagnostic_payload",
    "generate_diagnostic_bundle",
    "main",
    "verify_diagnostic_bundle",
]
