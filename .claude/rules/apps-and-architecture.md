---
paths:
  - "src/apps/**"
  - "configs/**"
  - "docker-compose.yml"
  - "Dockerfile*"
  - "docs/architecture/**"
---

# Application and architecture rules

- Inspect the owning app's live code, tests, configuration, and existing `docs/architecture/<app>/` records before proposing structural changes.
- Preserve explicit ownership boundaries, lifecycle/state transitions, failure behavior, idempotency, resource limits, and persistence authority.
- Reuse the existing configuration authority. Keep invariants in the owning module unless they genuinely vary by asset, environment, deployment, or supported runtime policy.
- A material architecture change must keep canonical D2, catalog, and README records synchronized as required by `AGENTS.md`; do not create an independent diagram truth.
- Do not update architecture diagrams for changes that do not alter architecture.
- Prefer focused validation first, then broader validation proportional to blast radius.
