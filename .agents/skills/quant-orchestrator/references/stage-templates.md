# Three-Role Handoff Templates

## Orchestrator to Architect

1. Objective and decision needed
2. Known context and evidence
3. Scope, constraints, and non-goals
4. Questions the architect must resolve
5. Expected coder-ready output
6. Current state and gate (`DISCOVERY`, `REQUIREMENTS_CONFIRMED`, or `DESIGN_OPTIONS`)
7. Explicit Phase 1, Deferred, and Rejected scope where relevant

## Architect to Coder

1. Objective and evidence
2. Scope and non-goals
3. Affected files, symbols, contracts, and flows
4. Selected design and implementation order
5. Acceptance criteria and validation
6. Risks, compatibility, and rollback
7. Design gate: `DESIGN_APPROVED`, `CONTRACT_READY`, or `IMPLEMENTATION_AUTHORIZED`
8. Quant Validity controls when research/model behavior is in scope

## Coder to Orchestrator

1. Scope executed and not changed
2. Files and symbols changed
3. Blast radius considered
4. Validation commands and exact results
5. Self-review findings
6. Blockers and residual risks
7. Pass 1 evidence and Pass 2 adversarial findings/rectifications

## Orchestrator Decision

1. Reviewed scope and contract
2. Findings by severity
3. Validation sufficiency and blast-radius conclusion
4. Pass 1 findings and Pass 2 independent challenge
5. Standards, Spec, and Quant Validity findings where applicable
6. Research conclusion: positive, negative, or inconclusive
7. Promotion decision, if applicable
8. Decision: APPROVED, REMEDIATE, or NOT_APPROVED
9. Required next action and accepted residual risk
