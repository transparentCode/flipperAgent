---
goal: Example architect-to-coder handoff for a quant pipeline change
stage: architect-to-coder
date_created: 2026-05-22
last_updated: 2026-05-22
owner: Quant Research Architect
status: 'Draft'
tags: [handoff, quant, example, pipeline]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Introduction

This is a template-style example of an architect-to-coder handoff for `flipperAgent`. It demonstrates the expected structure and level of detail for a durable handoff file in `plans/`.

## Objective

Add a reusable normalization stage for market data ingestion so downstream research code consumes a stable, point-in-time-safe dataset interface.

## Scope Boundaries

- In scope: ingestion normalization boundary, schema validation, timezone normalization, and a narrow validation path for the affected ingestion slice.
- Out of scope: new strategy logic, factor modeling, order simulation, position sizing, or changes to live execution behavior.

## Affected Symbols, Modules, and Execution Flows

- Affected modules: ingestion adapters, normalization layer, and downstream dataset-loading interface.
- Affected flows: raw market data ingestion to normalized research dataset loading.
- Blast radius note: shared ingestion contracts and downstream dataset consumers should be checked with GitNexus before implementation.

## Data Contracts or Interfaces

- Preserve the external dataset-loading interface unless a contract change is explicitly approved.
- Normalize timestamps to the agreed canonical timezone.
- Ensure symbol mapping and calendar alignment remain explicit and testable.

## Implementation Order

1. Identify the current ingestion and normalization boundary.
2. Add or refine the normalization layer without broadening downstream interfaces.
3. Update the affected ingestion-to-dataset path.
4. Run narrow validation for the touched ingestion slice.

## Acceptance Criteria

- Normalized output is consistent for the touched ingestion path.
- Point-in-time correctness is preserved.
- No silent contract change reaches downstream research consumers.
- GitNexus blast radius for the touched shared symbols is reviewed before final sign-off.

## Validation Checklist

- Targeted validation runs for the touched ingestion slice.
- Data contract checks cover timestamps, symbols, and required fields.
- Blast radius and affected execution flows are documented.
- Not changed areas are explicitly listed in the coder summary.

## Explicit Non-Goals

- No strategy alpha changes.
- No backtest engine changes.
- No live trading or broker integration changes.
- No unrelated refactors outside the ingestion-to-normalization slice.