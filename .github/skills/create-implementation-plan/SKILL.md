---
name: create-implementation-plan
description: 'Create an implementation plan file for new features, refactors, package upgrades, architecture, infrastructure, or quant pipeline changes. Use when: planning a new capability, restructuring code, defining a research or data workflow, or preparing an execution-ready handoff.'
argument-hint: 'What needs to be planned?'
user-invocable: true
---

# Create Implementation Plan

## Primary Directive

Your goal is to create a new implementation plan file for the user's requested change. The output should be structured, explicit, and suitable for execution by another AI agent or a human engineer.

## Execution Context

This skill is used to convert a request into a concrete implementation plan. Before drafting the plan, retrieve prior context from available memory systems and inspect the repository so the plan reflects verified constraints instead of assumptions.

## Core Requirements

- Generate implementation plans that are executable by AI agents or humans.
- Use explicit language and call out any unresolved unknowns separately.
- Structure the plan so phases, tasks, and validation steps are easy to parse.
- Keep the plan self-contained enough that a coding agent can execute it without re-deriving the architecture.
- Use codebase intelligence tools when available to verify dependency structure, affected execution flows, and blast radius instead of inferring them from surface reading alone.

## Plan Structure Requirements

Plans must consist of discrete phases with executable tasks. Cross-phase dependencies should be explicit, and tasks that can run in parallel should be marked as such.

## Phase Architecture

- Each phase must have measurable completion criteria
- Tasks within phases must be executable in parallel unless dependencies are specified
- Task descriptions should include verified file paths, symbols, and interfaces when known
- If exact implementation details are not yet verified, explicitly mark them as open context instead of inventing them

## AI-Optimized Implementation Standards

- Use explicit, unambiguous language with zero interpretation required
- Structure all content as machine-parseable formats (tables, lists, structured data)
- Include specific file paths and exact code references where applicable
- Define configuration values and assumptions explicitly when they are known
- Provide enough context within each task description for a coding agent to execute it safely
- Use standardized prefixes for all identifiers (REQ-, TASK-, etc.)
- Include validation criteria that can be automatically verified

## Output File Specifications

- Save implementation plan files in `plans/` at the repository root unless the user specifies another location
- Use naming convention: `[purpose]-[component]-[version].md`
- Purpose prefixes: `upgrade|refactor|feature|data|infrastructure|process|architecture|design`
- Example: `upgrade-system-command-4.md`, `feature-auth-module-1.md`
- File must be valid Markdown with proper front matter structure

## Required Workflow

1. Retrieve prior context from available memory systems.
2. Inspect the repository and identify the relevant files or modules.
3. If the request changes existing code, use codebase intelligence tools repository context, impact analysis, execution flows, and change detection to assess blast radius.
4. State assumptions, unknowns, and constraints explicitly.
5. Include architecture tradeoffs and rejected alternatives when the task affects design, data flow, or infrastructure.
6. Produce a coding handoff section with implementation order, blast radius summary, and validation criteria.

## Mandatory Template Structure

All implementation plans must strictly adhere to the following template. Each section is required and must be populated with specific, actionable content. AI agents must validate template compliance before execution.

## Template Validation Rules

- All front matter fields must be present and properly formatted
- All section headers must match exactly (case-sensitive)
- All identifier prefixes must follow the specified format
- Tables must include all required columns
- No placeholder text may remain in the final output

## Status

The status of the implementation plan must be clearly defined in the front matter and must reflect the current state of the plan. The status can be one of the following (status_color in brackets): `Completed` (bright green badge), `In progress` (yellow badge), `Planned` (blue badge), `Deprecated` (red badge), or `On Hold` (orange badge). It should also be displayed as a badge in the introduction section.

```md
---
goal: [Concise Title Describing the Package Implementation Plan's Goal]
version: [Optional: e.g., 1.0, Date]
date_created: [YYYY-MM-DD]
last_updated: [Optional: YYYY-MM-DD]
owner: [Optional: Team/Individual responsible for this spec]
status: 'Completed'|'In progress'|'Planned'|'Deprecated'|'On Hold'
tags: [Optional: List of relevant tags or categories, e.g., `feature`, `upgrade`, `chore`, `architecture`, `migration`, `bug` etc]
---

# Introduction

![Status: <status>](https://img.shields.io/badge/status-<status>-<status_color>)

[A short concise introduction to the plan and the goal it is intended to achieve.]

## 1. Requirements & Constraints

[Explicitly list all requirements & constraints that affect the plan and constrain how it is implemented. Use bullet points or tables for clarity.]

- **REQ-001**: Requirement 1
- **SEC-001**: Security Requirement 1
- **[3 LETTERS]-001**: Other Requirement 1
- **CON-001**: Constraint 1
- **GUD-001**: Guideline 1
- **PAT-001**: Pattern to follow 1

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: [Describe the goal of this phase, e.g., "Implement feature X", "Refactor module Y", etc.]

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Description of task 1 | ✅ | 2025-04-25 |
| TASK-002 | Description of task 2 | |  |
| TASK-003 | Description of task 3 | |  |

### Implementation Phase 2

- GOAL-002: [Describe the goal of this phase, e.g., "Implement feature X", "Refactor module Y", etc.]

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-004 | Description of task 4 | |  |
| TASK-005 | Description of task 5 | |  |
| TASK-006 | Description of task 6 | |  |

## 3. Alternatives

[A bullet point list of any alternative approaches that were considered and why they were not chosen. This helps to provide context and rationale for the chosen approach.]

- **ALT-001**: Alternative approach 1
- **ALT-002**: Alternative approach 2

## 4. Dependencies

[List any dependencies that need to be addressed, such as libraries, frameworks, or other components that the plan relies on.]

- **DEP-001**: Dependency 1
- **DEP-002**: Dependency 2

## 5. Files

[List the files that will be affected by the feature or refactoring task.]

- **FILE-001**: Description of file 1
- **FILE-002**: Description of file 2

## 6. Testing

[List the tests that need to be implemented to verify the feature or refactoring task.]

- **TEST-001**: Description of test 1
- **TEST-002**: Description of test 2

## 7. Risks & Assumptions

[List any risks or assumptions related to the implementation of the plan.]

- **RISK-001**: Risk 1
- **ASSUMPTION-001**: Assumption 1

## 8. Related Specifications / Further Reading

[Link to related spec 1]
[Link to relevant external documentation]
```