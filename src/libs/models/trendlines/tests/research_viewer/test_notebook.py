import json
from pathlib import Path

import IPython.display as ipython_display
from IPython.core.interactiveshell import InteractiveShell
from IPython.display import IFrame


NOTEBOOK = Path(__file__).resolve().parents[6] / "research" / "trendlines_research_lab.ipynb"


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_notebook_json_contract() -> None:
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] >= 0
    assert all(cell["cell_type"] in {"markdown", "code"} for cell in notebook["cells"])


def test_notebook_outputs_are_cleared() -> None:
    for cell in _notebook()["cells"]:
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []


def test_notebook_executes_top_to_bottom(monkeypatch) -> None:
    shell = InteractiveShell()
    display_calls = []

    def record_display(*objects, **kwargs):
        display_calls.extend(objects)

    monkeypatch.setattr(ipython_display, "display", record_display)
    try:
        for cell in _notebook()["cells"]:
            if cell["cell_type"] != "code":
                continue
            result = shell.run_cell("".join(cell["source"]), store_history=False)
            assert result.error_in_exec is None
    finally:
        session = shell.user_ns.get("session_result")
        if session is not None:
            session.close()
        final_status = shell.user_ns.get("final_status")
        assert final_status["viewer_servers_closed"] is True
        assert final_status["temporary_bundles_removed"] is True
    assert sum(isinstance(value, IFrame) for value in display_calls) >= 3


def test_notebook_has_no_model_or_provider_implementation() -> None:
    source = "\n".join(
        "".join(cell["source"])
        for cell in _notebook()["cells"]
        if cell["cell_type"] == "code"
    )
    assert "from apps" not in source
    assert "BinanceConnector" not in source
    assert "window_left" not in source
    assert "pivot_window" not in source
    assert "yaml.safe_dump" not in source
