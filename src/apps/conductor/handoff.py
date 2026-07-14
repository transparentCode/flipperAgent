"""Parse and write quant handoff markdown documents."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from apps.conductor.contracts import Handoff


# Regex to split YAML frontmatter from markdown body.
_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$",
    re.DOTALL,
)


def parse_handoff(path: Path) -> Handoff:
    """Parse a handoff markdown file into a ``Handoff`` model."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"Handoff {path} missing YAML frontmatter")

    frontmatter_text, body = match.groups()
    data = yaml.safe_load(frontmatter_text) or {}
    data["body"] = body.strip()
    data["path"] = path

    # Extract structured sections from the body for convenience.
    sections = _extract_sections(body)
    data.setdefault("objective", sections.get("Objective"))
    data.setdefault("scope_boundaries", _parse_scope_boundaries(sections.get("Scope Boundaries", "")))
    data.setdefault("acceptance_criteria", _parse_checklist(sections.get("Acceptance Criteria", "")))
    data.setdefault("known_risks", _parse_checklist(sections.get("Known Risks", "")))

    return Handoff.model_validate(data)


def write_handoff(path: Path, handoff: Handoff) -> None:
    """Serialize a ``Handoff`` to disk with YAML frontmatter."""
    data = handoff.model_dump(exclude={"path", "body"}, exclude_none=True)
    frontmatter = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    body = handoff.body.strip()
    path.write_text(
        f"---\n{frontmatter}---\n\n{body}\n",
        encoding="utf-8",
    )


def _extract_sections(body: str) -> dict[str, str]:
    """Extract top-level '## Section' blocks from markdown body."""
    sections: dict[str, str] = {}
    current_title: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


def _parse_checklist(text: str) -> list[str]:
    """Parse '- [ ] item' / '- [x] item' checklist lines."""
    items: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*-\s*\[\s*[xX]?\s*\]\s*(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def _parse_scope_boundaries(text: str) -> dict[str, list[str]]:
    """Parse '**In-Scope**:' / '**Out-of-Scope**:' lists."""
    result: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key_match = re.match(r"^\*?\*?(In-Scope|Out-of-Scope)\*?\*?:\s*(.*)$", line, re.IGNORECASE)
        if key_match:
            current_key = "In-Scope" if key_match.group(1).lower() == "in-scope" else "Out-of-Scope"
            remainder = key_match.group(2).strip()
            result.setdefault(current_key, [])
            if remainder:
                result[current_key].append(remainder)
            continue
        item_match = re.match(r"^[-*]\s+(.+)$", line)
        if item_match and current_key:
            result[current_key].append(item_match.group(1).strip())
    return result


def find_handoffs(plans_dir: Path, stage: str | None = None) -> list[Path]:
    """Find handoff markdown files under ``plans_dir``.

    Args:
        plans_dir: Directory containing ``.md`` handoff files.
        stage: Optional stage filter, e.g. ``architect-to-coder``.

    Returns:
        Sorted list of matching handoff paths.
    """
    paths = [p for p in plans_dir.glob("*.md") if p.is_file()]
    if stage is None:
        return sorted(paths)

    matched: list[Path] = []
    for path in paths:
        try:
            handoff = parse_handoff(path)
        except ValueError:
            continue
        if handoff.stage == stage:
            matched.append(path)
    return sorted(matched)
