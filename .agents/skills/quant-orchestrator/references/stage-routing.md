# Three-Role Routing

| Situation | Owner | Next owner |
|---|---|---|
| Unclear hypothesis, evidence, experiment, architecture, or contract | Architect | Orchestrator |
| Complete implementation contract or bounded fix | Coder | Orchestrator |
| Review, remediation decision, final approval, integration | Orchestrator | Architect or coder only if needed |

Skip architect when objective, scope, non-goals, acceptance criteria, and validation
are already complete. Never create separate research, bounded-worker, review, or
approval agents.
