def test_runtime_package_does_not_import_current_sr():
    from pathlib import Path
    root = Path("src/libs/models/sr_v2")
    assert not any("libs.models.sr." in path.read_text() for path in root.rglob("*.py"))


def test_research_composition_has_no_selection_forecast_or_browser_execution():
    from pathlib import Path

    roots = (
        Path("src/libs/models/sr_v2/research_lab"),
        Path("src/libs/models/sr_v2/research_viewer"),
    )
    files = [path for root in roots for path in root.rglob("*.py")]
    files.append(Path("src/libs/models/sr_v2/research_lab/sr_v2_research_lab.ipynb"))
    forbidden = (
        "select_top_down",
        "selected_references",
        "selection_reasons",
        "CalibrationArtifact",
        "ForecastModel",
        "from libs.contracts.decision",
        "import libs.contracts.decision",
        "libs.models.sr.",
        "playwright",
        "patchright",
        "selenium",
        "browser.launch",
        "https://cdn.",
    )
    violations = [
        (str(path), token)
        for path in files
        for token in forbidden
        if token in path.read_text()
    ]
    assert not violations, violations
