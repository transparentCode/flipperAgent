# Trendline Family Model — Phase A Review

Date: 2026-07-11
Reviewer mode: Quant review / architecture gate
Status: **REVISION REQUIRED — Phase B is not approved yet**

Reviewed against:

- `plans/trendline-family-model-architecture-plan.md`
- `plans/trendline-family-codex-phase-execution-plan.md`
- repository `AGENTS.md`

Reviewed implementation:

- `src/libs/models/trendline_family/`
- `configs/trendline_family.yaml`
- Phase-A tests

## 1. Validation reproduced

The submitted targeted suite is green:

```text
PYTHONPATH=src .venv/bin/python -m pytest src/libs/models/trendline_family/tests -q
18 passed
```

Ruff is also green when invoked from the installed user binary:

```text
ruff check src/libs/models/trendline_family
All checks passed
```

Package import and bytecode compilation pass.

These results are necessary but not sufficient for Phase-A approval.

## 2. Blocking findings

### A-01 — Candidate causality is not enforced

Severity: BLOCKER

`LineCandidate.__post_init__` does not verify that every anchor was confirmed on or before `observed_at`.

A candidate with:

```text
observed_at = 2024-01-01 04:00 UTC
anchor.confirmation_time = 2024-01-01 08:00 UTC
```

is currently accepted.

This violates the locked no-future-data rule and would allow Phase B to emit causally invalid candidates even if the pivot implementation makes a mistake.

Required correction:

- require at least two anchors for a line candidate,
- require unique anchor IDs,
- require every `anchor.confirmation_time <= candidate.observed_at`,
- reject negative `source_line_index`,
- add explicit causal rejection tests.

### A-02 — Configuration is dataclass-typed but not runtime type-safe

Severity: BLOCKER

Python dataclass annotations are not runtime validators. Current config classes accept invalid YAML/runtime values such as:

```text
lookback_bars: true
min_candidate_quality: 2.0
minimum_match_score: 2.0
reactivation_min_score: 2.0
```

Boolean values are accepted as integers, and unit-interval scores are only checked for non-negativity.

Required correction:

- reject `bool` for integer and floating-point numeric fields,
- reject strings and other incompatible scalar types with `ContractValidationError`,
- require strict positive/non-negative integer semantics where applicable,
- require quality, confidence, match, decay and reactivation scores to be in `[0, 1]`,
- require `birth_quality_threshold >= min_candidate_quality`,
- require `approaching_distance_atr >= tolerance_atr`,
- validate `model.enabled` is a real boolean,
- validate provider/fitter/model version fields are non-empty strings,
- validate config `version` is a non-empty scalar rather than coercing arbitrary mappings/lists to strings,
- add wrong-type and out-of-range tests for every config section.

### A-03 — Repository-wide pytest does not collect the new tests

Severity: BLOCKER

`pyproject.toml` defines:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

The Phase-A tests were placed under:

```text
src/libs/models/trendline_family/tests/
```

Therefore normal root execution does not collect them. This also conflicts with `AGENTS.md`, which says tests should remain easily runnable under `tests/`.

Required correction:

- move the Phase-A tests to:

```text
tests/models/trendline_family/
```

- remove the source-package test copies,
- verify both targeted and ordinary repository collection find them,
- update both planning files so all future phase tests use the top-level test tree.

Do not solve this by silently relying on a special test command only.

### A-04 — Codebase-memory index was replaced by a zero-node artifact

Severity: BLOCKER / repository integrity

Observed tracked changes:

```text
.codebase-memory/artifact.json
  nodes: 39071 -> 0
  edges: 123830 -> 0

.codebase-memory/graph.db.zst
  compressed size: ~15 MB -> 1.4 KB
```

The CLI currently reports no indexed projects.

This contradicts the completion claim that no unrelated files changed and prevents required blast-radius analysis in later phases.

Required correction:

1. Restore the two codebase-memory files from the valid Git baseline.
2. Reindex from the repository root using the documented CLI command.
3. Verify `list_projects` shows `Users-aloobhujia-flipperAgent`.
4. Verify node and edge counts are non-zero and plausible.
5. Stop and report rather than committing another zero-node index if indexing fails.

## 3. Contract hardening required in Phase A

These should be corrected now because later phases will build directly on these public contracts.

### A-05 — Diagnostic and state score semantics are under-validated

Severity: HIGH

Current contracts accept examples such as:

```text
normalized_quality = 2.0
coverage = -1.0
effective_touch_count > touch_count
estimated_width_atr = -1.0
confidence = 5.0
association_score = 3.0
```

Required minimum invariants:

- `normalized_quality`, `coverage`, `inlier_ratio`, `cut_fraction`, `fitter_consensus`, `anchor_stability` in `[0, 1]` when present,
- `r_squared <= 1` when present; negative values remain allowed,
- `residual_scale_atr >= 0` when present,
- touch and breach counters are strict non-negative integers, excluding booleans,
- `effective_touch_count <= touch_count`,
- `confidence`, `structural_importance`, `current_relevance` in `[0, 1]`,
- `association_score` in `[0, 1]` when present,
- `estimated_width_atr >= 0`,
- all bar-count fields are strict non-negative integers.

Do not impose a `[0, 1]` bound on `raw_score` because its provider-specific scale is intentionally unspecified.

### A-06 — Malformed deserialization leaks arbitrary Python errors

Severity: HIGH

`LineDiagnostics.from_dict({})` and `LineUncertainty.from_dict({})` currently fail with `TypeError` rather than a domain-level `ContractValidationError` or applying declared optional defaults.

Required correction:

- use required-key access for required fields,
- preserve dataclass defaults for omitted optional fields,
- wrap malformed persisted payload errors at the repository/deserialization boundary in `ContractValidationError`,
- test missing required fields, wrong field types, malformed enums, malformed timestamps and non-finite values.

### A-07 — Representative-line and family invariants are not enforced

Severity: HIGH

The architecture requires the representative to be an actual member, not a synthetic average. Current state accepts a missing `representative_member_id` and unrelated representative geometry.

Required correction:

- require at least one member,
- require unique member IDs,
- require `representative_member_id` to identify an existing member,
- require `representative` to equal that member’s exact `LineGeometry`,
- require family member asset/time semantics through surrounding state checks,
- require `created_at <= last_confirmed_at <= updated_at`,
- require member visibility/confirmation timestamps not to exceed family update timestamps.

### A-08 — Published snapshot invariants are incomplete

Severity: HIGH

Required correction:

- active bucket may contain only `ACTIVE` families,
- dormant bucket may contain only `DORMANT` families,
- every family `updated_at` and `last_confirmed_at` must be `<= snapshot.timestamp`,
- transition model/config/hash metadata must match the containing snapshot,
- transition timestamp must not exceed snapshot timestamp,
- validate hash strings as 64-character lowercase hexadecimal values,
- preserve the ability for an expiry transition to refer to a family omitted from active/dormant output.

### A-09 — Frozen mapping fields are only shallowly protected

Severity: MEDIUM

`metadata`, `diagnostics` and `features` copy only the outer mapping. Nested lists/dicts can still be mutated after contract construction, changing canonical serialization.

Required correction:

- deep-copy and recursively freeze canonical mapping/list values, or
- reject nested mutable types and document a flat canonical metadata contract.

The preferred solution is a small recursive canonical freeze helper using mapping proxies and tuples.

### A-10 — Import-boundary test is not future-proof

Severity: MEDIUM

The current test scans only top-level `*.py` files. It will miss forbidden imports when later phases introduce subpackages.

Required correction:

- scan recursively with `rglob("*.py")`,
- exclude test paths,
- keep all three forbidden prefixes,
- add a static test that YAML imports/reads occur only in `config_loader.py`.

## 4. Architecture clarification

The public snapshot is described as immutable, while `TrendlineFamilyState` is mutable and is embedded directly inside it.

Recommended resolution before Phase C:

- make persisted/published `TrendlineFamilyState` immutable with tuple collections,
- let the future tracker use a private mutable working accumulator or `dataclasses.replace`,
- publish only immutable states.

This is not needed by Phase B candidate generation, but Phase A is the cheapest point to settle it. Do not add a second public state contract unless necessary.

## 5. Phase-A remediation scope

Allowed source changes:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_loader.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/repository.py
src/libs/models/trendline_family/__init__.py
configs/trendline_family.yaml
```

Test changes:

```text
move tests to tests/models/trendline_family/
expand contract/config/repository/import-boundary tests
```

Planning changes:

```text
plans/trendline-family-model-architecture-plan.md
plans/trendline-family-codex-phase-execution-plan.md
```

Repository repair:

```text
restore and validly reindex .codebase-memory artifacts
```

Forbidden during remediation:

- pivots,
- fitters,
- candidate providers,
- matching,
- tracking loop,
- interaction classification,
- RegimeV2 integration,
- MTF,
- optimization.

## 6. Remediation exit gate

All must pass before Phase B approval:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q
ruff check src/libs/models/trendline_family tests/models/trendline_family
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_family
```

Additionally:

- root `pytest --collect-only` must show the Phase-A tests,
- future-confirmed anchors must be rejected,
- wrong config scalar types must be rejected with `ContractValidationError`,
- unit-interval violations must be rejected,
- malformed snapshot payloads must raise `ContractValidationError`,
- representative/member and snapshot bucket invariants must be tested,
- recursive old-import scan must pass,
- codebase-memory project/node/edge checks must be non-zero.

## 7. Reviewer decision

**REVISION REQUIRED.**

The overall structure is good and the implementation stayed within Phase-A feature scope. Phase B must not start until the blocking causality, configuration, test-discovery and repository-index issues are corrected and the foundational contract invariants are hardened.
