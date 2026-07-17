from __future__ import annotations

from types import SimpleNamespace

from libs.models.sr.scripts.lifecycle_utility import runner


def test_compute_study_consumes_only_validated_inputs(monkeypatch, lifecycle_config, synthetic_study):
    expected = synthetic_study(implementation_commit="c" * 40)
    calls = []
    inputs = SimpleNamespace(
        v10_audit=SimpleNamespace(cases=tuple(range(36))),
        source_bars=tuple(),
        null_cells=expected.null_cells,
    )
    monkeypatch.setattr(runner, "load_validated_inputs", lambda *args, **kwargs: calls.append("validated-inputs") or inputs)
    monkeypatch.setattr(runner, "extract_first_resolution_events", lambda *args, **kwargs: expected.resolutions)
    monkeypatch.setattr(runner, "compute_wilder_atr_by_bar", lambda *args, **kwargs: tuple())
    monkeypatch.setattr(runner, "null_cell_for_event", lambda *args, **kwargs: None)
    by_resolution = {item.resolution_id: item for item in expected.outcomes}
    monkeypatch.setattr(runner, "build_resolution_outcome", lambda event, *args, **kwargs: by_resolution[event.resolution_id])

    actual = runner.compute_study(lifecycle_config, repo_root=".", implementation_commit="c" * 40)
    assert calls == ["validated-inputs"]
    assert actual.to_payload() == expected.to_payload()
