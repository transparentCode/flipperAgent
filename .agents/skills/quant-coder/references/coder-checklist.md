# Quant Coder Implementation Checklist

## Before editing

- [ ] For delegated workspace writes, read the approved durable handoff under
      `plans/`; use an inline contract only for read-only analysis or trivial
      root-session work.
- [ ] Verify objective, scope, non-goals, acceptance criteria, and validation plan.
- [ ] Check repository status and preserve unrelated user changes.
- [ ] Confirm paths, symbols, and config from the live checkout.
- [ ] Inspect impact: callers, callees, affected flows, and blast radius.
- [ ] Escalate to `quant-architect` if design judgment is required.

## While editing

- [ ] Make the smallest safe change that satisfies the contract.
- [ ] Preserve typing, public contracts, and deterministic behavior.
- [ ] Guard point-in-time correctness, data identity, timing, calendars, and costs.
- [ ] Avoid look-ahead bias, leakage, survivorship bias, and configuration drift.
- [ ] Do not invent parameters, schemas, lifecycle states, or paths.
- [ ] Add or update focused tests, docs, and config wiring as needed.
- [ ] Run Ruff for Python changes.

## After editing

- [ ] Run focused validation first, then broader checks in proportion to risk.
- [ ] Inspect the final diff for scope drift and hidden behavior.
- [ ] Self-review for failure paths, compatibility, and test gaps.
- [ ] Pass 1: verify the contract, diff, tests, scope, configuration, and evidence.
- [ ] Pass 2: independently challenge edge cases, API/schema errors, security,
      concurrency/resource handling, compatibility, and unnecessary complexity.
- [ ] Fix material Pass 2 findings and rerun only the affected validation; record
      the rectification rather than silently changing the conclusion.
- [ ] Record exact changed files, commands, and results.
- [ ] Note unresolved risks and anything not completed.
- [ ] If the orchestrator requests a `coder-to-orchestrator` handoff, provide it in
      the orchestrator-owned format under `plans/`.
