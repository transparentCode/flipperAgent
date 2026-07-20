from pathlib import Path


ROOT = Path("src/libs/models/sr/research/studies/adaptive_context_calibration")


def test_v23_study_does_not_import_prior_study_packages_or_runtime() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.glob("*.py"))
    assert "studies.v2_0" not in text
    assert "studies.v2_1" not in text
    assert "studies.v2_2" not in text
    assert "runtime" not in text
    assert "configs/sr.yaml" not in text


def test_provider_name_occurs_only_in_source_leaf() -> None:
    for path in ROOT.glob("*.py"):
        if path.name == "source.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "from apps." not in text
        assert "import apps." not in text
