# Claude Code setup for flipperAgent

This project intentionally keeps `AGENTS.md` as the single repository-wide agent constitution. Claude Code 2.1.277+ reads `AGENTS.md` directly when no project `CLAUDE.md` is present, so adding a duplicate root `CLAUDE.md` would waste context and create policy-drift risk.

## Start

From the repository root, run `claude`.

For an isolated parallel implementation, run `claude --worktree <task-name>`.

The first interactive launch after `.mcp.json` changes will ask you to trust/approve the project MCP servers. The intended tier is:

1. `codebase-memory-mcp` for normal semantic and project-scoped graph navigation;
2. `gitnexus` only for justified whole-repo/PDG/cross-directory escalation;
3. `hindsight` only from the root orchestrator for durable memory.

Claude auto-memory is disabled for this project so it does not become a competing durable-memory layer beside Hindsight and `plans/`.

## Role routing

- Root session: Quant Orchestrator from `AGENTS.md`.
- `quant-architect`: Opus, read-only planning/research/design.
- `quant-coder`: Sonnet, approved implementation only.

The Claude agents are thin adapters. Canonical role policy remains under `.agents/skills/`.

## Useful manual skills

- `/architecture-audit <subsystem or question>`
- `/research-gate <experiment / claim / handoff>`
- `/implementation-review <handoff + implementation scope>`
- `/phase-handoff <current phase and next owner>`

The first three run in isolated read-only architect contexts, keeping large audits and reviews out of the main conversation window.

## Context discipline

- Use `/clear` when moving to an unrelated outcome.
- Prefer `/phase-handoff ...` followed by `/clear` when crossing a durable workflow boundary such as audit -> design, design -> implementation, or implementation -> independent review.
- Use `/compact` only when continuing the same outcome and a fresh phase handoff is unnecessary.
- Use `/context` to inspect what is consuming the active window.
- Keep long-lived decisions in `plans/`, not only in conversation history.
- Use worktrees for parallel writers; do not run two writers against one checkout.

## Safety and permissions

Project settings pre-approve common focused test/lint/read-only Git commands, keep destructive Git/Docker operations behind an explicit prompt, block direct reads of repo secrets and common credential directories, and disable bypass-permissions mode.

Personal approvals that Claude saves belong in `.claude/settings.local.json`; keep that file untracked.
