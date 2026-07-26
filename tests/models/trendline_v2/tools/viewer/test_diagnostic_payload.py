from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.tools.viewer.diagnostic_export import (
    build_verified_diagnostic_payload,
    OUTPUT_BUNDLE,
    verify_diagnostic_bundle,
)
from libs.models.trendline_v2.tools.viewer.diagnostic_payload import (
    DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
    DiagnosticViewerError,
    _canonical_json_bytes,
    _sha256,
    validate_diagnostic_bundle,
    validate_diagnostic_payload,
    write_diagnostic_bundle,
)


@pytest.fixture(scope="module")
def payload() -> dict[str, object]:
    return build_verified_diagnostic_payload()


def _rebind(payload: dict[str, object]) -> dict[str, object]:
    result = deepcopy(payload)
    semantic = dict(result)
    semantic.pop("payload_id", None)
    result["payload_id"] = deterministic_hash(
        DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
        semantic,
    )
    return result


def test_diagnostic_payload_has_exact_target_and_two_lines(payload) -> None:
    assert payload["asset"] == "BTCUSDT"
    assert payload["timeframe"] == "4h"
    assert payload["checkpoint_index"] == 5
    assert len(payload["lines"]) == 2
    assert {line["side"] for line in payload["lines"]} == {"contender", "control"}
    assert all(candle["time"] < 1780963200 for candle in payload["candles"])


def test_diagnostic_bundle_has_exact_two_members(payload, tmp_path: Path) -> None:
    bundle = write_diagnostic_bundle(payload, tmp_path / "bundle")
    assert {path.name for path in bundle.iterdir()} == {"manifest.json", "chart_payload.json"}
    manifest = validate_diagnostic_bundle(bundle)
    assert manifest["payload_id"] == payload["payload_id"]
    assert manifest["members"] == [
        {
            "name": "chart_payload.json",
            "sha256": _sha256((bundle / "chart_payload.json").read_bytes()),
            "byte_length": (bundle / "chart_payload.json").stat().st_size,
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("r4_diagnostic_id", "0" * 64, "r4_diagnostic_id"),
        ("r5_attribution_id", "0" * 64, "r5_attribution_id"),
        ("raw_candle_sha256", "0" * 64, "raw_candle_sha256"),
    ],
)
def test_frozen_source_identity_mutations_reject_after_rebinding(payload, field, value, message) -> None:
    forged = deepcopy(payload)
    forged[field] = value
    forged = _rebind(forged)
    with pytest.raises(DiagnosticViewerError, match=message):
        validate_diagnostic_payload(forged)


def test_wrong_cell_and_lineage_reject_after_rebinding(payload) -> None:
    forged_cell = deepcopy(payload)
    forged_cell["cell_attribution"]["one_sided_direction"] = "contender_only"
    with pytest.raises(DiagnosticViewerError, match="cell attribution"):
        validate_diagnostic_payload(_rebind(forged_cell))

    forged_line = deepcopy(payload)
    forged_line["lines"][0]["lineage_id"] = "0" * 64
    with pytest.raises(DiagnosticViewerError, match="lineage"):
        validate_diagnostic_payload(_rebind(forged_line))


def test_post_checkpoint_candle_rejected_after_rebinding(payload) -> None:
    forged = deepcopy(payload)
    forged["candles"].append({
        "time": 1780963200,
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "volume": 1.0,
    })
    with pytest.raises(DiagnosticViewerError, match="post-checkpoint"):
        validate_diagnostic_payload(_rebind(forged))


def test_outcome_mutation_does_not_change_diagnostic_selection(payload) -> None:
    import scripts.analyze_trendline_v2_causal_structural_reachability as r4
    from libs.models.trendline_v2.tools.viewer.diagnostic_export import _source_inputs
    from libs.models.trendline_v2.tools.viewer.diagnostic_payload import build_diagnostic_payload

    r4_diagnostic, r5_attribution, raw_payload, raw_bytes = _source_inputs()
    mutated = deepcopy(r4_diagnostic)
    mutated["outcome_evidence"][0]["outcomes"] = {"24h": {"future_contact_count": 999999}}
    rebuilt = build_diagnostic_payload(
        mutated,
        r5_attribution,
        raw_payload,
        raw_bytes=raw_bytes,
    )
    assert rebuilt == payload
    assert r4.__name__


def test_payload_bytes_are_canonical(payload) -> None:
    encoded = _canonical_json_bytes(payload)
    assert encoded == _canonical_json_bytes(json.loads(encoded))
    assert hashlib.sha256(encoded).hexdigest()


def test_published_bundle_rederives_from_r4_r5_and_raw_sources() -> None:
    if not OUTPUT_BUNDLE.exists():
        pytest.skip("canonical diagnostic bundle is not present")
    result = verify_diagnostic_bundle(OUTPUT_BUNDLE)
    assert result["status"] == "R5_DIAGNOSTIC_VIEWER_VERIFIED"
    assert result["member_count"] == 1
