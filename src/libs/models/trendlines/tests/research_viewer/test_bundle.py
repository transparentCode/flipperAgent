import asyncio
import json

import pytest

from libs.models.trendlines.research_viewer import (
    TrendlineResearchNotebookSession,
    read_viewer_bundle,
    validate_viewer_bundle,
    write_viewer_bundle,
)
from libs.models.trendlines.research_viewer.notebook_support import run_research_notebook_session
from libs.models.trendlines.data.contracts import TrendlineArtifactRef
from libs.models.trendlines.workflows.research import (
    read_research_evidence_bundle,
    write_research_evidence_bundle,
)
@pytest.fixture(scope="module")
def smoke_session() -> TrendlineResearchNotebookSession:
    result = asyncio.run(run_research_notebook_session(start_viewer=False))
    yield result
    result.close()


def test_invalid_evidence_payload_is_rejected(smoke_session: TrendlineResearchNotebookSession) -> None:
    payload = dict(smoke_session.payload)
    payload["replay_point_id"] = "f" * 64
    with pytest.raises(Exception):
        write_viewer_bundle(payload, "/tmp/unused-trendline-viewer-invalid")


def test_bundle_round_trip(smoke_session: TrendlineResearchNotebookSession, tmp_path) -> None:
    path = write_viewer_bundle(smoke_session.payload, tmp_path / "bundle")
    assert read_viewer_bundle(path) == smoke_session.payload


def test_bundle_tamper_rejected(smoke_session: TrendlineResearchNotebookSession, tmp_path) -> None:
    path = write_viewer_bundle(smoke_session.payload, tmp_path / "bundle")
    payload_path = path / "chart_payload.json"
    payload = json.loads(payload_path.read_text())
    payload["asset"] = "ETHUSDT"
    payload_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(Exception):
        validate_viewer_bundle(path)


def test_explicit_viewer_export_writes_exact_members(
    smoke_session: TrendlineResearchNotebookSession,
    tmp_path,
) -> None:
    path = write_viewer_bundle(smoke_session.payload, tmp_path / "bundle")
    assert {entry.name for entry in path.iterdir()} == {"manifest.json", "chart_payload.json"}
    evidence_path = write_research_evidence_bundle(
        smoke_session.evidence_bundle,
        TrendlineArtifactRef(
            artifact_root=str(tmp_path),
            relative_path="evidence.json",
            label="smoke-evidence",
        ),
    )
    assert read_research_evidence_bundle(evidence_path).bundle_id == smoke_session.evidence_bundle.bundle_id


def test_bundle_rejects_extra_member(smoke_session: TrendlineResearchNotebookSession, tmp_path) -> None:
    path = write_viewer_bundle(smoke_session.payload, tmp_path / "bundle")
    (path / "unexpected.txt").write_text("no")
    with pytest.raises(Exception):
        validate_viewer_bundle(path)
