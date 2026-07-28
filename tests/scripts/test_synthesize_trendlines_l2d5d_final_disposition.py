"""Artifact-only D5D synthesis and closeout tests."""

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.synthesize_trendlines_l2d5d_final_disposition import (
    D5DError,
    FINAL_FILES,
    OUTPUT_ROOT,
    verify_published_output,
)


def test_published_d5d_artifact_readback_is_complete():
    result = verify_published_output()
    root = Path(OUTPUT_ROOT)
    assert result["cohort_count"] == 5
    assert result["outcome"] == "utility_not_better_than_naive_null"
    assert result["recommended_action"] == "REDESIGN_GEOMETRY_SELECTION"
    assert tuple(sorted(path.name for path in root.iterdir() if path.is_file())) == tuple(sorted(FINAL_FILES))
    checksums = __import__("json").loads((root / "checksums.json").read_text())
    assert len(checksums["files"]) == 5


def test_existing_output_root_is_never_overwritten():
    from scripts.synthesize_trendlines_l2d5d_final_disposition import synthesize

    with pytest.raises(D5DError, match="already exists"):
        synthesize()


def test_d5d_script_has_no_execution_or_provider_boundary():
    source = Path("scripts/synthesize_trendlines_l2d5d_final_disposition.py").read_text()
    for forbidden in (
        "run_causal_replay",
        "prepare_trendline_research",
        "BinanceNativeAdapter",
        "TrendlineResearchLoader",
        "provider",
    ):
        if forbidden == "provider":
            # Provider accounting fields are permitted; provider construction is not.
            assert "Binance" not in source
        else:
            assert forbidden not in source


def test_decision_matrix_contains_frozen_rules_and_actual_selection():
    import json

    payload = json.loads(
        (Path(OUTPUT_ROOT) / "decision_matrix.json").read_text(encoding="utf-8")
    )
    assert len(payload["rules"]) == 6
    assert payload["first_selected_rule"] == "RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL"
    assert sum(row["selected"] for row in payload["rules"]) == 1
    assert len(payload["cohort_evidence"]) == 5


def test_prior_execution_counts_are_zero():
    import json

    manifest = json.loads(
        (Path(OUTPUT_ROOT) / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["provider_calls"] == 0
    assert manifest["provider_retries"] == 0
    assert manifest["model_executions"] == 0
    assert manifest["replay_executions"] == 0
    assert manifest["parameter_trials"] == 0


def _copy_output(tmp_path: Path) -> Path:
    target = tmp_path / "d5d-output"
    shutil.copytree(OUTPUT_ROOT, target)
    return target


def _rewrite_checksums(root: Path) -> None:
    entries = []
    for path in sorted(root.iterdir()):
        if path.name == "checksums.json":
            continue
        entries.append(
            {
                "path": path.name,
                "byte_length": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (root / "checksums.json").write_text(
        json.dumps(
            {
                "schema_version": "trendlines.l2d5d-final-disposition-checksums.v1",
                "files": entries,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("tamper", ("passed", "decisive_null", "first_selected_rule"))
def test_published_readback_recomputes_complete_decision_matrix(tmp_path, tamper):
    root = _copy_output(tmp_path)
    path = root / "decision_matrix.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if tamper == "passed":
        payload["rules"][0]["passed"] = not payload["rules"][0]["passed"]
    elif tamper == "decisive_null":
        payload["decisive_null"]["id"] = "0" * 64
    else:
        payload["first_selected_rule"] = "RULE_1_COVERAGE_FAILURE"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(root)
    with pytest.raises(D5DError, match="decision matrix differs"):
        verify_published_output(root)
