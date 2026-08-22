---
name: code-review
description: 'Quant-aware implementation review for the root Quant Orchestrator. Use to verify a diff against its contract, blast radius, validation, and quantitative safety before approval.'
user-invocable: true
---

# Code Review

Canonical owner: `quant-orchestrator`.
Canonical policy: `.agents/skills/quant-orchestrator/SKILL.md`.

Apply two distinct review lenses rather than running the same checklist twice:
Pass 1 validates contract, diff, scope, tests, and evidence. Pass 2 independently
challenges assumptions, compatibility, security, resource/concurrency behavior,
over/under-engineering, and residual risk. For research/model changes add Quant
Validity: causality/PIT, leakage, labels, splits, holdout, baselines, numerics,
reproducibility, multiplicity/tuning, and sensitivity/uncertainty.

1. Read the request, approved contract, actual diff, and validation evidence.
2. Use code intelligence per `mcp-tiered-code-intelligence` to verify affected
   callers, contracts, and execution flows. Start with `codebase-memory-mcp`;
   escalate to `gitnexus` only for whole-repo structural impact.
3. Check correctness, typing, compatibility, configuration drift, failure paths, and
   test quality.
4. Check point-in-time correctness, leakage, survivorship, timing, costs, calendars,
   timezones, symbol identity, and reproducibility where relevant.
5. List findings by severity with exact file/symbol references.
6. Decide `APPROVED`, `REMEDIATE`, or `NOT_APPROVED`. Send implementation defects
   to Quant Coder and design ambiguity to Quant Architect.

Do not create a separate review or approval agent.
