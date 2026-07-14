---
goal: Implement SR-V1.3 explicit initialization, canonical state checkpoints, and deterministic replay parity
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Coder Agent
status: Ready
tags: [handoff, quant, sr, state, checkpoint, serialization, replay, causality]
source_agent: Coder Agent
target_agent: Quant Review Agent
---

# Coder To Review: SR-V1.3 Checkpoint And Replay v1

## Scope Executed

Implemented only SR-V1.3 from approved V1.2 commit `1e5e068` on
`feature/sr-v1.3-checkpoint-replay`.

Implementation commit: `a8a3606 feat(sr): add checkpoint replay`

Hardening commit: `f1ae181 fix(sr): reject oversized checkpoint integers`

Scope is complete enough for review without guessing. No merge performed.

## Changes Made

### Nullable initial aggregate and factory

- `src/libs/models/sr/domain/contracts.py`
  - Added single domain `SR_SCHEMA_VERSION = "1.0"` constant.
  - Changed `SRState.last_processed_bar` to `str | None`.
  - Enforced empty zones/buffer for null cursor and non-empty retained buffer
    for non-null cursor.
  - Enforced current schema version for `SRState` and `SRSnapshot`.
- `src/libs/models/sr/domain/factory.py`
  - Added exact-type `create_initial_state(state_key, resolved_config)`.
  - Enforces symbol/timeframe ownership, freezes resolved config hash, and
    performs no YAML or I/O.
- `libs.models.sr.domain` and `libs.models.sr` export
  `create_initial_state`; serialization/replay are not package-root imports.
- `SREngine.step` skips cursor duplicate comparison only for the nullable
  initial cursor. First successful step stores bar ID and retained bar.

### Canonical state codec

- `src/libs/models/sr/serialization/state_codec.py`
- `src/libs/models/sr/serialization/__init__.py`

Public API: `encode_state(state) -> str`, `decode_state(payload) -> SRState`.

Envelope:

```text
{
  "codec_name": "sr-state-json",
  "codec_version": 1,
  "payload_hash": SHA256(canonical state payload),
  "state": {...}
}
```

State payload explicitly contains schema version, full state key, config hash,
nullable cursor, every zone definition/runtime field, stored definition/runtime
zone IDs, every buffered bar including ATR, timestamps, enum values, and
nullable interaction timestamps. Snapshots, events, and configuration objects
are excluded.

Canonical rules:

- Existing deterministic canonical JSON/hash helpers are used.
- UTF-8 JSON, sorted keys, compact separators, finite numbers only.
- UTC timestamps use `...Z`; microseconds are preserved exactly.
- Decode requires exact envelope and nested key sets, recursively rejects
  duplicate keys, unknown keys, missing keys, malformed JSON, non-canonical
  text, non-finite values, unsupported codec identity/version, and non-UTC
  timestamps.
- Domain constructors validate enums, ownership, chronology, numeric types,
  and config hashes.
- Definition and runtime stored zone IDs are checked against reconstructed
  content/ownership; state payload hash is recomputed.
- Numeric conversion catches oversized integers at the domain boundary and
  translates them to `ContractValidationError`.
- No pickle, generic object reconstruction, migration, or recovery path.

### Pure replay

- `src/libs/models/sr/replay/runner.py`
- `src/libs/models/sr/replay/__init__.py`

`replay_bars(initial_state, bars, resolved_config)` validates the full exact
input batch before any engine call, then executes only:

```text
caller-ordered ClosedBar tuple -> SREngine.step -> one SRSnapshot per bar
```

Preflight rejects wrong types, state/config ownership mismatch, mixed keys,
duplicate IDs within batch, IDs in retained buffer, cursor duplication, and
equal/decreasing/out-of-order timestamps. It accepts positive timestamp gaps,
does not sort/fill/skip/deduplicate, leaves inputs unchanged, and returns no
partial result on contract failure. Empty input returns unchanged state and
empty snapshots.

Duplicate detection is bounded by retained `recent_bars`; IDs older than that
buffer remain an upstream ingestion responsibility. No unbounded seen-ID
history was added.

## Blast Radius Considered

- Existing `SREngine.step` flow remains authoritative; replay runner is its
  only new production caller.
- Existing lifecycle, detection, association, capacity, fakeout, expiry,
  event, and snapshot semantics are unchanged.
- Existing SR state construction sites/tests were updated to use nullable
  initial state or explicit retained bars.
- Domain/config/YAML boundaries remain independent of serialization/replay.
- No prohibited external dependency or cross-model import was introduced.

## Validation Performed

- `.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/serialization tests/models/sr/replay -q`
  - `123 passed`
- `.venv/bin/python -m pytest tests/models/sr -q`
  - `263 passed`
- `.venv/bin/python -m pytest tests/models/sr/lifecycle -q`
  - `55 passed`
- `.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q`
  - `2 passed`
- SR import boundaries: `2 passed`.
- SR YAML adapter boundary: `1 passed`.
- `ruff check src/libs/models/sr tests/models/sr`: passed.
- `.venv/bin/python -m compileall -q src/libs/models/sr`: passed.
- Package import of factory, codec, and replay APIs: `ok`.
- `git diff --check`: passed.
- Prohibited-import scan: no production matches for pickle, legacy SR,
  pandas/numpy/polars/scipy/sklearn/ML, storage, cache, or network modules;
  pandas mentions remain only in existing boundary-test denylist logic.
- Codebase-memory index refreshed after changes: `52,008 nodes`, `169,695 edges`.

Independent probes passed:

1. First engine step from true nullable-cursor factory state.
2. Canonical encode/decode/re-encode byte identity.
3. Nested duplicate/unknown-key and NaN/Infinity rejection.
4. Oversized integer rejection with a recomputed payload hash.
5. Corrupted payload and forged stored definition/runtime zone-ID rejection.
6. One-bar replay/direct-step equality.
7. Uninterrupted versus checkpoint-resume suffix parity.
8. Duplicate/equal/decreasing/out-of-order batch rejection.
9. Positive timestamp gap accepted without fill.
10. Config/state ownership mismatch rejection.
11. Input immutability and preflight failure before engine processing.

Parity sequence uses pivot warmup, support/resistance creation, touch,
breach-pending, fakeout, confirmed break, expiry, and two-bar buffer rollover.
Full replay equals prefix replay -> canonical checkpoint round-trip -> suffix
replay, including final state, zone IDs, snapshot IDs, suffix snapshots, events,
and event IDs.

## Not Changed

- No V1.4 or later SR phase.
- No filesystem/database/cache/network/storage adapter.
- No checkpoint scheduling, retention, locking, transactions, or event sourcing.
- No global seen-bar history, gap fill, cadence/calendar policy, sorting, or
  out-of-order recovery.
- No schema migration or legacy codec compatibility.
- No snapshots/event-history persistence.
- No alternate detector/association logic, features, scores, tuning, market
  evaluation, strategy, PnL, execution, risk, or runtime integration.
- Exact eight YAML configuration paths and values remain unchanged.
- Legacy `app.sr`/`libs.sr` remain isolated.
- Pre-existing `.codebase-memory` artifacts and unrelated untracked plan drafts
  were not staged or committed.

## Risks or Follow-Up Items

- Retained-buffer duplicate limitation is deliberate and must remain upstream
  ingestion responsibility.
- `payload_hash` detects accidental corruption; it is not authentication or
  tamper-proof security.
- Runtime `typing.get_type_hints(create_initial_state)` remains a non-blocking
  follow-up; normal imports and factory calls are unaffected.
- Review should independently inspect canonical text strictness and forged-ID
  rejection across nested payload levels.
- Do not begin storage, features, tuning, evaluation, or later SR phases until
  Quant Review approval.
