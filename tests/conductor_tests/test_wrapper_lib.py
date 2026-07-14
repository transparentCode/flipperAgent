"""Tests for conductor wrapper shared library."""

from __future__ import annotations

from pathlib import Path

from conductor.scripts.conductor_wrapper_lib import (
    extract_handoff_from_output,
    next_stage,
    parse_handoff_text,
    write_handoff,
)


def test_parse_handoff_text_with_frontmatter() -> None:
    text = (
        "---\n"
        "goal: 'Test goal'\n"
        "stage: 'researcher-to-architect'\n"
        "status: 'Ready'\n"
        "---\n\n"
        "# Body\n\n"
        "Some content.\n"
    )
    handoff = parse_handoff_text(text)
    assert handoff.goal == "Test goal"
    assert handoff.stage == "researcher-to-architect"
    assert handoff.status == "Ready"
    assert "Some content." in handoff.body


def test_parse_handoff_text_without_frontmatter() -> None:
    handoff = parse_handoff_text("Just body text.")
    assert handoff.body == "Just body text."
    assert handoff.goal == ""


def test_next_stage_default() -> None:
    assert next_stage("architect") == "coder"
    assert next_stage("coder") == "reviewer"
    assert next_stage("reviewer") == "approval"
    assert next_stage("approval") == "done"


def test_next_stage_custom() -> None:
    assert next_stage("architect", {"architect": "review"}) == "review"


def test_write_handoff(tmp_path: Path) -> None:
    path = tmp_path / "architect-to-coder.md"
    write_handoff(path, "architect", "coder", "Implement X", "Body text")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "goal: Implement X" in text
    assert "stage: architect-to-coder" in text
    assert "Body text" in text


def test_extract_handoff_from_output_with_frontmatter() -> None:
    output = (
        "---\n"
        "goal: 'New goal'\n"
        "stage: 'architect-to-coder'\n"
        "---\n\n"
        "# Title\n\n"
        "Body here.\n"
    )
    goal, body = extract_handoff_from_output(output, "architect", "coder")
    assert goal == "New goal"
    assert "Body here." in body


def test_extract_handoff_from_output_fallback() -> None:
    goal, body = extract_handoff_from_output("# Heading\n\nbody", "architect", "coder")
    assert goal == "Heading"
    assert body == "body"
