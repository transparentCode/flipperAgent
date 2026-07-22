# Quant Coder Implementation Checklist

## Before editing

- [ ] Read the approved handoff or inline contract.
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
- [ ] Record exact changed files, commands, and results.
- [ ] Note unresolved risks and anything not completed.
- [ ] If the orchestrator requests a `coder-to-orchestrator` handoff, provide it in
      the orchestrator-owned format under `plans/`.
