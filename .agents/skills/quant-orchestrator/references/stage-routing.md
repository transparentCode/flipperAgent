# Stage Routing Matrix

- `research`: idea exploration, hypothesis testing, indicator/model comparison, experiment design, web research for external evidence.
- `architecture`: vague request, strategy idea, pipeline design, tradeoff analysis, missing implementation-ready scope.
- `coder`: approved handoff exists and execution scope is clear.
- `review`: implementation finished and needs correctness/risk review.
- `approval`: review complete; user requests sign-off/merge readiness.
- `write-handoff`: user asks to persist stage package in `plans/`.

Escalation rules:
- If coder/review/approval finds architectural ambiguity, route back to `architecture`.
- If review finds execution defects, route to `coder`.
- If research needs external evidence, invoke `search-specialist` skill for deep web research.
- If any stage produces a durable artifact, route to `write-handoff`.
