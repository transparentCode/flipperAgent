"""Shared helpers for conductor agent wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_STAGE_TRANSITIONS: dict[str, str] = {
    "architect": "coder",
    "coder": "orchestrator",
    "orchestrator": "done",
}


@dataclass
class Handoff:
    """Minimal handoff model for wrapper use."""

    path: Path | None
    goal: str
    stage: str
    status: str
    body: str
    objective: str | None = None
    tags: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    known_risks: list[str] | None = None
    metadata: dict[str, Any] | None = None


def parse_handoff(path: Path) -> Handoff:
    """Parse a handoff markdown file with YAML frontmatter."""
    text = path.read_text(encoding="utf-8")
    return parse_handoff_text(text, path=path)


def parse_handoff_text(text: str, path: Path | None = None) -> Handoff:
    """Parse handoff text with optional YAML frontmatter."""
    text = text.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return Handoff(
                path=path,
                goal=str(frontmatter.get("goal", "")),
                stage=str(frontmatter.get("stage", "")),
                status=str(frontmatter.get("status", "Draft")),
                body=body,
                objective=frontmatter.get("objective"),
                tags=_list_field(frontmatter.get("tags")),
                acceptance_criteria=_list_field(frontmatter.get("acceptance_criteria")),
                known_risks=_list_field(frontmatter.get("known_risks")),
                metadata=frontmatter,
            )
    return Handoff(
        path=path,
        goal="",
        stage="",
        status="Draft",
        body=text,
    )


def _list_field(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(v) for v in value]


def next_stage(role: str, transitions: dict[str, str] | None = None) -> str | None:
    """Return the next stage role for a given role."""
    mapping = transitions or DEFAULT_STAGE_TRANSITIONS
    return mapping.get(role)


def write_handoff(
    path: Path,
    role: str,
    next_stage_role: str,
    goal: str,
    body: str,
    status: str = "Ready",
) -> Path:
    """Write a next-stage handoff file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "goal": goal,
        "stage": f"{role}-to-{next_stage_role}",
        "status": status,
    }
    content = (
        "---\n"
        f"{yaml.safe_dump(frontmatter, sort_keys=False)}"
        "---\n\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def extract_handoff_from_output(output: str, role: str, next_stage_role: str) -> tuple[str, str]:
    """Extract goal and body from agent output.

    Returns (goal, body). If a YAML frontmatter block is found, it is parsed;
    otherwise a simple heading is assumed.
    """
    output = output.strip()
    if output.startswith("---"):
        handoff = parse_handoff_text(output)
        if handoff.goal:
            return handoff.goal, output
    # Fallback: use first heading or first line as goal.
    lines = output.splitlines()
    goal = ""
    body_lines = lines[:]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            goal = stripped[2:].strip()
            body_lines = lines[i + 1:]
            break
        if stripped and not goal:
            goal = stripped
            body_lines = lines[i + 1:]
            break
    body = "\n".join(body_lines).strip()
    if not body:
        body = output
    return goal, body


def build_prompt(handoff: Handoff, role: str, next_stage_role: str) -> str:
    """Build a prompt for an AI agent to produce the next handoff."""
    objective = handoff.objective or "(none provided)"
    acceptance = "\n".join(f"- {c}" for c in (handoff.acceptance_criteria or [])) or "(none)"
    risks = "\n".join(f"- {r}" for r in (handoff.known_risks or [])) or "(none)"
    return (
        f"You are the {role} agent in a quant research workflow.\n"
        f"Read the handoff below and produce the next handoff for the {next_stage_role} stage.\n\n"
        "The output must be a valid markdown file with YAML frontmatter exactly like:\n\n"
        "---\n"
        "goal: '<concise goal for the next stage>'\n"
        f"stage: '{role}-to-{next_stage_role}'\n"
        "status: 'Ready'\n"
        "---\n\n"
        "# <Title>\n\n"
        "## Objective\n...\n\n"
        "## Deliverables\n...\n\n"
        "## Acceptance Criteria\n- [ ] ...\n\n"
        "## Known Risks\n- ...\n\n"
        "## Input Handoff\n"
        f"Goal: {handoff.goal}\n"
        f"Stage: {handoff.stage}\n"
        f"Objective: {objective}\n"
        f"Acceptance Criteria:\n{acceptance}\n"
        f"Known Risks:\n{risks}\n\n"
        "## Input Body\n"
        f"{handoff.body}\n"
    )
