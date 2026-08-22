# flipperAgent Agent Policy

## Source of Truth

This root file is the repository-wide constitution. Detailed role workflows,
memory rules, code-intelligence schemas, and review checklists live in the
canonical skills under .agents/skills/. Codex role TOML and GitHub agent files are
thin runtime adapters; they must not become alternate policy sources.

The root session is the user-facing Quant Orchestrator.

## Authority and Roles

- Quant Orchestrator: intake, requirements grilling, routing, durable handoffs,
  independent review, remediation decisions, final approval, and integration.
- quant-architect: read-only evidence, research, experiment design, architecture,
  tradeoffs, contracts, blast radius, and coder-ready scope.
- quant-coder: approved workspace implementation, tests, validation, self-review,
  and execution evidence. It is the sole delegated writer.

The normal flow is orchestrator -> architect -> coder -> orchestrator. Skip the
architect only when scope, non-goals, acceptance criteria, and validation are
already complete. Never create separate reviewer, researcher, bounded-worker, or
approval roles.

## Delegation and Workspace Safety

- Do not spawn for trivial work.
- Keep at most one architect and one coder task active for one outcome.
- Use one workspace-writing agent per checkout.
- Parallel writers require isolated worktrees, branches, runtime resources, and
  non-overlapping ownership.
- Agents do not switch branches, merge, cherry-pick, commit, or push unless
  explicitly authorized by the user or orchestrator.
- Every delegated workspace write requires an orchestrator-owned durable handoff
  under plans/. Inline contracts do not replace delegated-write handoffs.
- Preserve unrelated user changes and historical handoffs.

## Requirements and Approval

The orchestrator is the only human-facing grilling and approval authority. It
consolidates architect questions, challenges assumptions, and owns the user
interaction.

Material architecture, model, research-contract, causal-semantics, data-schema,
configuration-authority, and production-topology changes use:

DISCOVERY -> REQUIREMENTS_CONFIRMED -> DESIGN_OPTIONS ->
ADVERSARIAL_DESIGN_REVIEW -> DESIGN_APPROVED -> RESEARCH_OR_IMPLEMENTATION ->
EVIDENCE -> QUANT_SPEC_STANDARDS_REVIEW -> RESEARCH_CONCLUSION ->
PROMOTION_DECISION

DESIGN_APPROVED requires explicit user authorization. Routine bounded work uses
CONTRACT_READY or IMPLEMENTATION_AUTHORIZED; those states are not user design
approval. No coder work begins before the applicable gate.

Valid research conclusions may be positive, negative, or inconclusive. Promotion
is separate: RESEARCH_ONLY, SHADOW, PRODUCTION_CANDIDATE, or NO_PROMOTION.

Use two distinct review lenses: Pass 1 validates contract, scope, diff, tests,
configuration, and evidence. Pass 2 independently challenges assumptions,
edge cases, API/schema correctness, security, concurrency/resource handling,
compatibility, causal/PIT validity, and over/under-engineering. Rerun affected
validation only when Pass 2 finds a material issue.

## Context, Memory, and Evidence

- Verify repository facts from the live checkout; do not invent paths, schemas,
  parameters, lifecycle states, benchmarks, or acceptance criteria.
- Retrieve memory only when prior decisions materially affect non-trivial work.
- Hindsight is the only active durable-memory layer. Only the orchestrator uses it;
  architect and coder receive selected context through handoffs.
- Source code, deterministic tests, and explicit runtime evidence are authoritative.
- A missing graph result is query-scoped evidence, never proof of absence.
- For quantitative work preserve point-in-time correctness, determinism, timezone
  and calendar semantics, symbol identity, transaction-cost assumptions, evidence
  provenance, and protected artifacts. Never hide leakage, look-ahead bias,
  survivorship bias, configuration drift, or timing changes.

## Code Intelligence

Follow .agents/skills/mcp-tiered-code-intelligence/SKILL.md. CBM is the primary
read-only evidence source; GitNexus is optional escalation. Per-server adapters
enforce read-only allowlists at both discovery and call time, deny unknown tools by
default, and keep raw backends from being a second client-visible path. Indexing,
deletion, ADR mutation, trace ingestion, rename, and group synchronization are
operator capabilities.

## Repository Conventions

- Python environment: .venv/bin/python.
- Dependency source of truth: pyproject.toml.
- Production packages: src/apps/ and src/libs/.
- Tests: tests/; run focused validation first and Ruff for Python changes.
- Reuse the existing configuration authority. Externalize behavior only when it
  genuinely varies across assets, environments, deployments, or runtime policy.
  Keep domain/model invariants close to their owning module; do not add config or
  shared constants solely to avoid literals.

## Handoffs

The orchestrator owns plans/ handoffs and the stage templates in
.agents/skills/quant-orchestrator/references/. Active stages are:
orchestrator-to-architect, architect-to-coder, coder-to-orchestrator, and
orchestrator-decision. Preserve older stage names in historical files.
