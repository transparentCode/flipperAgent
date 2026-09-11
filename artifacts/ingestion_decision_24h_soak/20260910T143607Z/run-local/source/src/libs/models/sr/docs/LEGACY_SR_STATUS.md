# Legacy SR Status

## Status

`src/libs/sr` is legacy/reference-only. It contains older,
kernel-ensemble-oriented SR implementation with separate models, pipeline,
optimization, lifecycle, qualification, and documentation surfaces.

It is not canonical implementation for this SR model family. Canonical active
code is exclusively `src/libs/models/sr`.

## Boundary

Active `libs.models.sr` code must not import `libs.sr`. Architecture tests
enforce this boundary. Do not bridge implementations with adapters, shared
imports, configuration fallback, or migration shims during pre-V2 refactor.

Historical compatibility facades for canonical model live under
`src/libs/models/sr/scripts`, not under `src/libs/sr`.

## Maintenance policy

Preserve legacy files unchanged during this refactor. They may remain useful as
historical reference, but they are not evidence of current-model behavior and
must not revive as runtime dependency.

Future removal or archival requires separately approved plan that:

1. inventories direct and transitive callers outside active SR package;
2. proves no supported interface still depends on legacy code;
3. defines replacement or retirement semantics for each public entry point;
4. validates project-wide import, CLI, and regression impact; and
5. receives explicit approval independent of V2 model work.

No legacy deletion, revival, merge, or V2 authorization occurs here.
