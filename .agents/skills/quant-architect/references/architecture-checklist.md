# Architecture Checklist

Run this before finalizing any coder-ready contract. Each gate must be addressed;
do not hand off a design with unchecked items.

## Quant Safety Gates

- Point-in-time correctness constraints (no look-ahead or leakage)
- Data contracts and interface boundaries
- Calendar/timezone/symbol mapping integrity
- Failure modes and rollback path
- Validation gates for implementation
- For research/model work: determine whether ML is warranted against a deterministic
  baseline; define ontology/representation, labels, PIT semantics, temporal and
  asset splits, holdout policy, generalization, compute/configuration boundaries,
  research-vs-production status, experiment multiplicity/tuning, and
  sensitivity/uncertainty.

## Scope and Simplicity Gates

- Smallest design that satisfies the constraints; no gold-plating or speculative
  abstraction
- Reuse of existing modules, functions, and configs before new ones are proposed
- Reuse the existing configuration authority. Externalize behavior only when it is
  expected to vary across assets, environments, deployments, or supported runtime
  policy. Keep domain/model invariants close to their owning module. Do not add
  configuration or shared constants solely to avoid literals.
- No invented parameters, schemas, benchmarks, or acceptance criteria

## Communication Gate

- Use a concise diagram when it materially clarifies a non-trivial architecture,
  pipeline, data-flow, ownership, or state relationship; do not add diagram ritual
  to simple decisions.
- Return unresolved questions and alternatives to the Quant Orchestrator, which
  owns the user-facing grilling and approval gate.
