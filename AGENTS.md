# flipperAgent - AI Agent Guidelines

## Overview
These are the foundational instructions for any AI assistant working on the `flipperAgent` project.

## Start Here
- Preferred user-facing entry point: `Quant Orchestrator`.
- Treat the specialized quant agents as internal workflow stages coordinated by the orchestrator unless the user explicitly asks to work with a specific specialist.

## Development Environment
- **Ecosystem:** Python.
- **Environment:** The project uses a local virtual environment located in `.venv/`. Agents should activate this environment or use the Python executable within `.venv/bin/python` when running commands or tests.

## Coding Conventions & Workflow
- Maintain modular design by placing core logic in a dedicated module (e.g., `src/` or `flipper_agent/`).
- Make sure to update a `requirements.txt`, `pyproject.toml`, or `Pipfile` when adding dependencies.
- Use `pytest` (or the preferred testing framework) and keep tests easily runnable in a `tests/` folder.
- Follow general Python best practices and PEP 8 guidelines.
- **Link, don't embed:** Refer to [README.md](README.md) for project purpose and architectural overviews.
## Memory & Context Protocol (Applies to ALL Agents)
- **NO PREASSUMPTIONS OR SHORTCUTS:** You must not assume context.
- **START OF TASK:** Always utilize the MCP memory harness (`automem` / `memoir`) or read persistent memory files to retrieve past context, decisions, and history before beginning any solution architecture, coding, or review.
- **END OF TASK:** Always save updated state, architectural outcomes, or major findings to the MCP memory harness before handing off or returning to the user.
