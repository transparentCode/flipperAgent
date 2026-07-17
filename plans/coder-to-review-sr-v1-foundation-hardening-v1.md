---
goal: Return SR-V1.0 foundation hardening patch for quant review
stage: coder-to-review
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Coder Agent
status: Ready
tags: [handoff, quant, sr, foundation, hardening]
source_agent: Coder Agent
target_agent: Quant Review
---

# Scope Executed

Closed four review findings only:

- `require_utc()` now rejects datetimes whose `utcoffset()` is `None`.
- Snapshot events now satisfy `zone.available_at <= event.timestamp <= snapshot.as_of`.
- Canonical numeric serialization normalizes signed zero to `0.0`.
- Geometry rejects non-finite derived lower or upper bounds.

Added adversarial regression tests and removed the remaining Ruff failure.

# Changes Made

Files changed:

- `src/libs/models/sr/domain/identity.py`
- `src/libs/models/sr/domain/contracts.py`
- `src/libs/models/sr/config/models.py`
- `tests/models/sr/domain/test_identity.py`
- `tests/models/sr/domain/test_contracts.py`
- `tests/models/sr/config/test_resolver.py`

`SRSnapshot` retains explicit V1.0 ownership policy: events must reference a zone present in the snapshot; no tombstone or lineage representation exists.

# Blast Radius Considered

Codebase-memory index was refreshed through CLI fallback because MCP transport was closed. Direct callers/callees were traced for `require_utc`, canonical serialization, geometry, snapshot construction, and resolved-config hashing.

Impact is critical inside the isolated SR foundation because IDs, snapshots, and resolved hashes depend on these paths. No production signal, strategy, risk, execution, portfolio, trendline-family, or legacy S/R flow imports this package.

# Validation Performed

- `.venv/bin/python -m pytest tests/models/sr -q` — 77 passed
- `.venv/bin/python -m pytest tests/models/sr/adapters/test_import_boundaries.py -q` — 1 passed
- `.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q` — 2 passed
- `ruff check src/libs/models/sr tests/models/sr` — passed
- `.venv/bin/python -m compileall -q src/libs/models/sr` — passed
- package import — passed
- forbidden `app.sr` / `libs.sr` search — clean

# Not Changed

No detection, association, lifecycle execution, persistence, YAML loading, optimizer/search-space, trendline/regime integration, legacy migration, or SR-V1.1 work. No merge performed.

# Risks or Follow-up Items

Review should re-run signed-zero identity probes, custom `tzinfo` with `utcoffset() is None`, event-before-availability probes, and overflowing geometry probes. Approval remains blocked until Quant Review confirms these invariants and the existing foundation findings remain closed.
