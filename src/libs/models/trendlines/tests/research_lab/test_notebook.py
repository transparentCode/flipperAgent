from __future__ import annotations

import json
from pathlib import Path

from libs.models.trendlines.research_lab import (
    compare_lab_sessions,
)

from . import session_for


NOTEBOOK = Path(__file__).resolve().parents[6] / "research" / "trendlines_research_lab.ipynb"


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_notebook_contract_has_required_sections_and_cell_shape() -> None:
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) >= 35
    markdown = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown"
    )
    for heading in ("## 0. Methodology and Safety", "## 8. Per-Timeframe TVLC Viewers", "## 19. Final Status and Cleanup"):
        assert heading in markdown
    viewer_cells = [
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code" and "viewer_manifest" in "".join(cell["source"])
    ]
    assert len(viewer_cells) == 1
    assert "for timeframe in controls.timeframes" in viewer_cells[0]
    assert "display(IFrame(" in viewer_cells[0]


def test_notebook_has_no_legacy_or_model_implementation_strings() -> None:
    source = "\n".join(
        "".join(cell["source"])
        for cell in _notebook()["cells"]
        if cell["cell_type"] == "code"
    )
    for forbidden in ("from apps", "app.connectors", "BinanceConnector", "Plotly", "matplotlib", "yaml.safe_dump"):
        assert forbidden not in source


def test_session_comparison_rejects_incompatible_replay_policy() -> None:
    left = session_for()
    right = session_for(("4h", "1h"))
    result = compare_lab_sessions([left, right])
    assert result.compatible is False
    assert any(item["field"] == "timeframes" for item in result.mismatches)


def test_session_fixture_is_zero_provider_and_cleanup_safe() -> None:
    session = session_for()
    assert session.provider_calls_made == 0
    session.close()
    session.close()
