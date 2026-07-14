# Trendline Family Model — Phase A Re-Review

Date: 2026-07-11
Status: Revision required before Phase B

## Current Mode

Quant review of the remediated Phase A implementation.

## Validation Reproduced

The following passed:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
35 passed

ruff check src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
Passed
```

Root collection, with the unrelated `tests/test_tv_browser_backfill.py` ignored, includes all new Phase-A tests.

Codebase-memory is healthy:

```text
project: Users-aloobhujia-flipperAgent
status: ready
nodes: 36,291
edges: 107,071
```

The main remediation goals are satisfied:

- tests moved under `tests/models/trendline_family`,
- no runtime imports from old trendline packages,
- YAML reads confined to `config_loader.py`,
- strict scalar/range config validation,
- causal `LineCandidate` anchors,
- frozen published family state,
- recursive metadata freezing,
- snapshot bucket and metadata checks,
- malformed deserialization normalized to `ContractValidationError`.

## Remaining Blocking Findings

### 1. `FamilyMember` permits impossible provenance

A `FamilyMember` can currently be created with zero anchors. It also does not independently require:

- at least two anchors,
- unique anchor IDs,
- anchor confirmation no later than `last_seen_at`.

A family member represents a persisted candidate line. It must not weaken the causal/provenance invariants already enforced by `LineCandidate`.

Required correction:

```text
len(anchors) >= 2
anchor IDs unique
all anchors are AnchorRef
anchor.confirmation_time <= last_seen_at
```

### 2. Initial repository snapshot permits non-birth family versions

`InMemoryTrendlineFamilyRepository._validate_lineage` returns immediately for the first snapshot and therefore accepts a newly introduced family with `version=2` or higher.

Every family absent from the previous repository head, including all families in the first snapshot, must start at version `1`.

Required correction:

- validate new-family versions before returning from the initial-snapshot branch,
- add an explicit first-snapshot version test.

### 3. Transition version and membership invariants are incomplete

The contracts currently accept:

- `BIRTH` with `previous_version=None` and `new_version=2`,
- `CONTINUE` with versions such as `7 -> 9`,
- duplicate `transition_id` values in one snapshot,
- a non-expiry transition referencing a family absent from the snapshot.

Required semantics:

```text
BIRTH:
  previous_version is None
  new_version == 1

all non-BIRTH transitions:
  previous_version is not None
  new_version == previous_version + 1

snapshot:
  transition IDs are unique
  every non-EXPIRE transition references a present active/dormant family
  for a present family, transition.new_version equals family.version
  EXPIRE may reference a family absent from the published active/dormant buckets
```

### 4. Config resolver is externally mutable after construction

`TrendlineFamilyConfigResolver` makes only a shallow copy of the raw config. Mutating the caller's nested dictionary after resolver construction changes future resolved output.

This violates deterministic resolved-config semantics.

Required correction:

- recursively copy/freeze the raw mapping during resolver construction,
- ensure later mutation of the caller-owned mapping cannot affect resolution,
- add an explicit regression test.

## Decision

Phase A is close, but **Phase B remains blocked** until the four invariant groups above are corrected and tested.

No architecture redesign is needed. This should be a small final Phase-A remediation.

## Required Validation

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
ruff check src/libs/models/trendline_family tests/models/trendline_family
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
codebase-memory-mcp cli index_status '{"project":"Users-aloobhujia-flipperAgent"}'
```

The codebase-memory index must remain ready with non-zero plausible node/edge counts.
