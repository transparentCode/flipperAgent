# SR Research Boundaries

## Ownership

Reusable research infrastructure lives under `research/`, not inside study:

- artifact publication, validation, canonical JSON, and path safety;
- strict research configuration, frozen identities, and repository provenance;
- verified frozen-file reads plus source-bar/grid identities;
- `SourceBar`, `CohortFold`, `CandidateReplay`, and `FirstTouchOutcome`;
- shared replay, first-touch metric, cohort, evidence, and viewer-payload
  services.

Study-specific protocol, gates, dispositions, and semantic artifact validation
remain in canonical `research/studies/<study>` package or explicitly named
evidence service. Shared code must not become generic upstream-evidence model.

## Allowed dependencies

```text
core/evaluation APIs → research shared → one canonical study → scripts/tooling
```

- Canonical study may import core/evaluation APIs, neutral research services,
  and its own implementation.
- Canonical study may not import another study or historical script path.
- Historical `scripts/<study>` paths forward to matching canonical study and
  retain public imports/CLI entry points.
- Viewer tools consume immutable public payloads. Research does not import
  viewer tools.
- Shared research code does not import studies, providers, network clients,
  databases, sealed/holdout services, or viewer code.

Provider acquisition, if separately authorized by study protocol, stays at
explicit study boundary. This refactor never authorizes provider calls, source
refreshes, holdout access, or evidence regeneration.

## Frozen evidence

Research artifacts are deterministic, content-addressed, and fail closed.
Validation checks safe repository-relative paths, symlink/non-regular members,
exact member sets, hashes, byte lengths, configuration identities,
implementation-commit bindings, and study-specific semantic recomputation.

Frozen evidence is input boundary. Refactors may validate it but must not
rewrite, normalize, move, republish, or regenerate it. V1.12 remains protected:

- bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
- audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
- disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.

## Research constraints

No study outcome authorizes trading, production promotion, model expansion,
parameter tuning, provider access, or holdout consumption unless approved
protocol says so. Negative findings remain findings; modularization does not
reinterpret them.
