"""Tests for handoff parsing and writing."""

from __future__ import annotations

from pathlib import Path

import pytest

from conductor.handoff import find_handoffs, parse_handoff, write_handoff


@pytest.fixture
def sample_handoff(tmp_path: Path) -> Path:
    path = tmp_path / "architect-to-coder-sample-v1.md"
    path.write_text(
        """---
goal: 'Sample Handoff'
stage: 'architect-to-coder'
date_created: '2026-07-12'
owner: 'Quant Architect'
status: 'Ready'
tags: ['handoff', 'quant']
target_agent: 'Quant Coder'
---

# Architect-to-Coder Handoff: Sample

## Objective
Refactor the sample module.

## Scope Boundaries
**In-Scope:**
- Extract helpers

**Out-of-Scope:**
- Change API surface

## Acceptance Criteria
- [ ] Helpers extracted
- [ ] Tests pass

## Known Risks
- [ ] Risk one
""",
        encoding="utf-8",
    )
    return path


def test_parse_handoff(sample_handoff: Path) -> None:
    handoff = parse_handoff(sample_handoff)
    assert handoff.goal == "Sample Handoff"
    assert handoff.stage == "architect-to-coder"
    assert handoff.status == "Ready"
    assert handoff.tags == ["handoff", "quant"]
    assert handoff.objective == "Refactor the sample module."
    assert "Extract helpers" in handoff.scope_boundaries.get("In-Scope", [])
    assert handoff.acceptance_criteria == ["Helpers extracted", "Tests pass"]
    assert handoff.known_risks == ["Risk one"]


def test_write_and_roundtrip(sample_handoff: Path, tmp_path: Path) -> None:
    handoff = parse_handoff(sample_handoff)
    out = tmp_path / "out.md"
    write_handoff(out, handoff)
    parsed = parse_handoff(out)
    assert parsed.goal == handoff.goal
    assert parsed.stage == handoff.stage


def test_find_handoffs(tmp_path: Path) -> None:
    (tmp_path / "a-architect-to-coder-v1.md").write_text(
        "---\ngoal: A\nstage: architect-to-coder\n---\n\nbody\n",
        encoding="utf-8",
    )
    (tmp_path / "b-other-v1.md").write_text(
        "---\ngoal: B\nstage: other\n---\n\nbody\n",
        encoding="utf-8",
    )
    all_paths = find_handoffs(tmp_path)
    assert len(all_paths) == 2

    filtered = find_handoffs(tmp_path, stage="architect-to-coder")
    assert len(filtered) == 1
    assert filtered[0].name == "a-architect-to-coder-v1.md"
