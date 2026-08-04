# Architecture Checklist

Run this before finalizing any coder-ready contract. Each gate must be addressed;
do not hand off a design with unchecked items.

## Quant Safety Gates

- Point-in-time correctness constraints (no look-ahead or leakage)
- Data contracts and interface boundaries
- Calendar/timezone/symbol mapping integrity
- Failure modes and rollback path
- Validation gates for implementation

## Scope and Simplicity Gates

- Smallest design that satisfies the constraints; no gold-plating or speculative
  abstraction
- Reuse of existing modules, functions, and configs before new ones are proposed
- Configurable behavior externalized to YAML; constants centralized in a constants
  file, not hard-coded
- No invented parameters, schemas, benchmarks, or acceptance criteria

## Communication Gate

- Architecture, pipeline, or data-flow decisions rendered as concise Mermaid
  diagrams so the user can validate direction early and flag problems before they
  go sloppy
