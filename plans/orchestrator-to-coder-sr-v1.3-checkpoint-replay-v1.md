---
goal: Implement explicit SR initialization, canonical state checkpoints, and deterministic replay/restart parity.
stage: orchestrator-to-coder
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, state, checkpoint, serialization, replay, causality]
source_agent: Quant Orchestrator
target_agent: Coder Agent
source_branch: feature/sr-v1.2-detection-association
source_commit: 1e5e06849102
target_branch: feature/sr-v1.3-checkpoint-replay
---

# Orchestrator To Coder: SR-V1.3 Checkpoint And Replay v1

## Decision And Phase Gate

SR-V1.0 foundation/configuration, SR-V1.1 lifecycle, and SR-V1.2 causal
detection/association are approved. Implement **SR-V1.3 explicit
initialization, canonical state serialization, and deterministic replay parity
only**, then stop for Quant Review.

Start from the exact approved V1.2 head:

```text
1e5e068  docs(sr): correct V1.2 test count
3d7d961  docs(sr): record V1.2 test hardening
bb4444b  test(sr): harden V1.2 follow-ups
4b6b77e  feat(sr): add V1.2 detection association
```

Create `feature/sr-v1.3-checkpoint-replay` from `1e5e068`. Do not merge
V1.2 or V1.3.

This is an engineering-correctness phase. Do not begin market evaluation,
features, tuning, storage integration, or runtime wiring.

## Why This Phase Exists

The SR model is stateful. Before empirical evaluation or production
integration, uninterrupted incremental processing and checkpoint-resume
processing must produce identical model states, zone identities, snapshots,
and events.

V1.3 must establish one authoritative execution path:

```text
ClosedBar sequence -> replay_bars -> SREngine.step
```

The replay layer must not reimplement detection, association, capacity, or
lifecycle behavior.

## Approved V1.3 Policy

These decisions are fixed:

- Initial state uses an explicit nullable cursor; no arbitrary `"seed"`
  sentinel.
- Replay input is processed only in caller-provided order.
- Duplicate, equal-time, decreasing-time, and out-of-order input fails closed.
- Replay never silently sorts, skips, deduplicates, fills, or repairs bars.
- Positive timestamp gaps are accepted. Calendar/session/gap-fill policy stays
  upstream.
- A checkpoint's final bar must not be replayed again; the caller supplies only
  the suffix after the checkpoint.
- State serialization is canonical JSON with an explicit codec version and
  content hash.
- Decode rejects malformed, non-canonical, corrupted, unknown-version,
  missing-key, duplicate-key, and unknown-key payloads.
- V1.3 provides a pure codec only. It does not read or write files, databases,
  caches, object stores, or network services.
- The exact eight model/configuration parameters remain unchanged.
- V1.2 detection, association, capacity, fakeout, expiry, and event semantics
  remain unchanged.

## Required File Structure

```text
src/libs/models/sr/
  domain/
    contracts.py
    factory.py
  serialization/
    __init__.py
    state_codec.py
  replay/
    __init__.py
    runner.py

tests/models/sr/
  domain/
    test_factory.py
  serialization/
    __init__.py
    test_state_codec.py
  replay/
    __init__.py
    test_runner.py
```

Use these descriptive boundaries. Do not place codec or replay logic in
`lifecycle/engine.py`, `domain/contracts.py`, or the YAML adapter.

## Initial-State Contract

Change:

```python
SRState.last_processed_bar: str
```

to:

```python
SRState.last_processed_bar: str | None
```

Required domain invariants:

1. If `last_processed_bar is None`:
   - `zones == ()`;
   - `recent_bars == ()`.
2. If `last_processed_bar is not None`:
   - it is a valid non-empty bar ID;
   - `recent_bars` is non-empty;
   - the final recent bar ID equals `last_processed_bar`.
3. Existing recent-bar ownership, exact-type, unique-ID, and strictly
   increasing timestamp validation remains.
4. Any state produced by a successful engine step has a non-null cursor.
5. Do not retain compatibility with arbitrary seed strings for a truly empty
   state.

This is an intentional isolated-package contract correction. Update all SR
construction sites explicitly.

## Initial-State Factory

Implement:

```python
create_initial_state(
    state_key: SRStateKey,
    resolved_config: ResolvedSRConfig,
) -> SRState
```

Place it in `domain/factory.py` and export it from `libs.models.sr.domain`
and the SR package root.

The factory must:

- require exact input types;
- require `state_key.symbol == resolved_config.asset`;
- require `state_key.timeframe == resolved_config.timeframe`;
- use the single approved SR schema-version constant;
- freeze `resolved_config.resolved_config_hash`;
- set `last_processed_bar=None`;
- set `zones=()`;
- set `recent_bars=()`;
- read no YAML and perform no I/O.

Define the schema version once in the SR domain boundary; do not scatter
literal schema versions across runtime code.

## Engine Cursor Changes

Preserve the public engine API:

```python
new_state, snapshot, events = SREngine().step(
    previous_state,
    closed_bar,
    resolved_config,
)
```

Update only cursor-aware preconditions:

- duplicate comparison with `last_processed_bar` occurs only when it is not
  `None`;
- the initial state has no previous timestamp;
- after the first step, current V1.2 buffer and chronology checks apply
  unchanged;
- a successful first step stores the bar ID and the bar in `recent_bars`;
- do not weaken config-hash, state-key, zone ownership, lifecycle, capacity, or
  numeric validation.

## Canonical State Codec

Public API:

```python
encode_state(state: SRState) -> str
decode_state(payload: str) -> SRState
```

Export only from `libs.models.sr.serialization`, not the package root.

### Envelope

Use an explicit envelope equivalent to:

```text
codec_name
codec_version
payload_hash
state
```

Requirements:

- `codec_name` is a fixed SR-state codec identity.
- `codec_version` is integer version 1.
- `payload_hash` is the existing deterministic SHA-256 helper applied to the
  complete canonical state payload.
- Unknown codec names or versions fail closed.
- The hash detects accidental corruption; do not describe it as authentication
  or tamper-proof security.

### Explicit State Payload

Encode fields explicitly. Do not use pickle, generic object reconstruction, or
module/class names.

The payload must include:

- state schema version;
- full `SRStateKey`;
- config hash;
- nullable last-processed bar ID;
- every `ZoneRecord` definition and runtime field;
- stored/derived zone IDs required for identity verification;
- every buffered `ClosedBar`, including `atr_at_close`;
- all timestamps;
- enum values;
- nullable interaction timestamps.

Do not serialize snapshots, candidate history, association history, or
configuration objects.

### Canonical Encoding

- Use UTF-8-compatible JSON text.
- Use deterministic field ordering and separators.
- Encode UTC timestamps in one documented canonical representation.
- Preserve microseconds exactly.
- Reject non-UTC timestamps on decode through the domain boundary.
- Reject NaN, positive infinity, and negative infinity.
- Reject duplicate JSON keys recursively.
- Reject booleans where numeric values are required.
- Reject every missing or unknown key at every envelope/state/nested-object
  level.
- Encoding the same state twice must produce byte-identical text.
- `encode_state(decode_state(encode_state(state)))` must be byte-identical to
  the first encoding.

### Decode And Identity Verification

Decode into the existing immutable domain types so all domain validation runs.

For every stored derived ID:

1. construct the underlying domain object;
2. recompute its deterministic identity;
3. require equality with the stored ID.

Then recompute the state payload hash and require equality with
`payload_hash`.

Support only the current SR schema and codec version. Do not implement legacy
migration, permissive fallback, aliases, or best-effort recovery.

## Pure Replay Runner

Implement:

```python
replay_bars(
    initial_state: SRState,
    bars: tuple[ClosedBar, ...],
    resolved_config: ResolvedSRConfig,
) -> tuple[SRState, tuple[SRSnapshot, ...]]
```

Export only from `libs.models.sr.replay`.

### Replay Preconditions

Before the first engine step, validate the complete supplied batch:

- exact `SRState`, tuple, exact `ClosedBar`, and exact
  `ResolvedSRConfig` types;
- state/config hash and asset/timeframe ownership;
- every bar belongs to the state key;
- bar IDs are unique within the supplied replay batch;
- no supplied bar ID appears in the state's retained `recent_bars`;
- the first bar ID does not equal a non-null last-processed cursor;
- timestamps are strictly increasing within the supplied batch;
- the first timestamp is strictly later than the final buffered bar when the
  state is non-initial.

Global duplicate detection for IDs older than the bounded retained buffer is
not possible inside this KISS state model and remains an upstream ingestion
responsibility. Do not add unbounded seen-ID history.

Positive timestamp gaps are valid. Do not parse timeframe strings, infer
expected cadence, or apply exchange calendars in V1.3.

### Replay Execution

- Call `SREngine.step` once per bar in the supplied order.
- Do not duplicate engine rules.
- Collect one snapshot per processed bar.
- Snapshot events remain the authoritative per-bar event output; do not return
  a second flattened event collection.
- Empty input returns the unchanged initial state and `()`.
- Inputs remain unmodified.
- On any contract error, raise `ContractValidationError` and return no result.
  The runner is pure, so locally constructed intermediate objects are not
  externally observable.

## Required Parity Proof

Construct at least one sequence that exercises:

- detector warmup;
- support and resistance creation;
- association suppression;
- touch;
- breach pending;
- fakeout;
- confirmed break or expiry;
- bounded recent-bar rollover.

Prove:

```text
full replay from initial state
==
prefix replay -> encode -> decode -> suffix replay
```

Compare:

- final `SRState`;
- complete zone definitions and runtime states;
- zone IDs;
- suffix snapshots;
- snapshot IDs;
- suffix events and event IDs;
- buffered bars and final cursor.

The resumed suffix outputs must equal the corresponding suffix of the
uninterrupted replay, not merely have the same counts.

## Required Tests

### Initial State

- factory returns the exact empty initial aggregate;
- wrong types and asset/timeframe mismatches fail;
- nullable cursor is valid only for empty zones/buffer;
- non-null cursor requires non-empty buffer and matching tail ID;
- first engine step from factory state succeeds;
- the arbitrary seed-state pattern is removed.

### Codec

- empty initial state round-trip;
- active, pending, broken, and expired zone round-trips;
- line and rectangular geometry round-trips;
- recent-bar ATR and timestamps round-trip;
- nullable timestamps round-trip;
- deterministic identical encoding;
- encode/decode/re-encode byte identity;
- zone/event-independent state identities remain unchanged;
- wrong codec name/version rejection;
- payload-hash mismatch rejection;
- missing/unknown/duplicate keys at nested levels;
- malformed JSON and wrong top-level type;
- NaN/infinity rejection;
- invalid enum, timestamp, state key, config hash, zone ID, and runtime/definition
  ownership rejection;
- input state remains unchanged.

### Replay

- empty replay;
- one-bar replay equals direct engine step;
- multi-bar uninterrupted replay is deterministic;
- checkpoint/resume parity against uninterrupted suffix;
- one snapshot per bar;
- snapshot event ownership remains valid;
- duplicate ID within batch rejection;
- duplicate ID against retained buffer rejection;
- equal/decreasing/out-of-order timestamp rejection;
- mixed state-key rejection;
- state/config mismatch rejection;
- positive time gaps are accepted without fill;
- exact input ordering is preserved;
- invalid batch returns no result and inputs remain unchanged.

### Regression And Boundaries

- all approved V1.0-V1.2 tests remain green;
- exact eight configuration paths remain unchanged;
- no new YAML fields or asset/timeframe values;
- serialization/replay imports satisfy the approved SR allowlist;
- no pickle, pandas, NumPy, Polars, TA/ML, filesystem, database, cache, network,
  trendline, regime, strategy, execution, risk, portfolio, or optimizer
  dependency is introduced.

## Explicit Non-Goals

Do not implement:

- filesystem or database repositories;
- Redis/Valkey, Timescale, object storage, or cloud adapters;
- atomic write/locking/transaction semantics;
- checkpoint scheduling or retention;
- event sourcing;
- global seen-bar history;
- gap detection/fill or exchange calendars;
- silent duplicate skipping;
- out-of-order buffering, sorting, or recovery;
- schema migration or legacy codec compatibility;
- snapshot/event-history persistence;
- terminal-zone pruning;
- alternate detectors or association variants;
- features, scores, strength, confidence, ranking, or quality;
- hyperparameter tuning or per-asset/timeframe values;
- strategy, PnL, execution, risk, or trading-readiness evaluation;
- integration with legacy `app.sr` or `libs.sr`.

## Exact Configuration Surface

The following eight paths must remain the complete model configuration:

```text
detection.pivot_span_bars
detection.zone_half_width_atr
association.merge_distance_atr
lifecycle.touch_tolerance_atr
lifecycle.break_buffer_atr
lifecycle.break_confirm_closes
lifecycle.max_age_bars
runtime.max_active_zones
```

Codec/schema versions are software protocol constants, not YAML configuration
or hyperparameters.

## Acceptance Commands

Run and report:

```bash
.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/serialization tests/models/sr/replay -q
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q
ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr
.venv/bin/python -c "from libs.models.sr import create_initial_state; from libs.models.sr.serialization import encode_state, decode_state; from libs.models.sr.replay import replay_bars; print('ok')"
rg -n "pickle|app\.sr|libs\.sr|pandas|numpy|polars|scipy|sklearn|tensorflow|torch|sqlalchemy|redis|valkey|requests|httpx" src/libs/models/sr tests/models/sr
git diff --check
```

Run independent probes for:

1. first step from a true nullable-cursor initial state;
2. canonical encode/decode/re-encode byte identity;
3. nested duplicate/unknown-key and non-finite JSON rejection;
4. corrupted payload and forged stored-zone-ID rejection;
5. one-bar replay/direct-step equality;
6. uninterrupted versus checkpoint-resume suffix parity;
7. duplicate/equal/decreasing/out-of-order batch rejection;
8. a positive timestamp gap being accepted without fill;
9. config/state ownership mismatch rejection;
10. input immutability and no returned partial replay result.

## Mandatory Coder Handoff

Return a coder-to-review handoff containing:

- target branch and implementation commit;
- exact approved base commit `1e5e068`;
- exact files added/changed;
- nullable-cursor compatibility impact;
- factory contract and schema-version ownership;
- exact codec envelope and canonical timestamp/JSON rules;
- hash and derived-ID verification;
- replay preflight and processing-order map;
- explicit bounded duplicate-detection limitation;
- uninterrupted/checkpoint-resume parity evidence;
- call/callee and blast-radius analysis;
- all tests, lint, compile, import, diff, and independent-probe outputs;
- confirmation that the exact eight-parameter/YAML surface is unchanged;
- confirmation that no storage, I/O, migration, gap fill, features, tuning,
  evaluation, runtime integration, or legacy imports were added;
- known risks and deliberately deferred work.

Stop after V1.3 implementation and handoff. Do not begin storage adapters,
market evaluation, features, tuning, or a later SR phase without explicit
Quant Review approval.
