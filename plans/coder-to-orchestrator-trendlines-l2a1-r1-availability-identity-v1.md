# L2-A1-R1 — Availability Identity and Mode Contracts

## 1. Disposition

Complete. No commit created. Availability schedules now participate in dataset identity, timestamp
semantics are mandatory, and incompatible mode fields fail closed.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
commit: 0abb0b56b34816bd42e6aa705abc3189bbbda11f
subject: feat: enforce causal trendline signal inputs
```

## 3. Worktree proof

Existing L2-A1 implementation and handoff remained uncommitted. R1 changed only research
contracts/data validation, research exports, research tests/docs, and this handoff. No bridge,
pagination, model, YAML, replay, optimization, notebook, or viewer path changed.

## 4. Availability collision reproduction

Pre-remediation review used identical asset, timeframe, event index, OHLCV, provenance, and
timestamp semantics, but different schedules:

```text
Dataset A final availability: 2025-01-01 04:00 UTC
Dataset B final availability: 2025-01-01 05:00 UTC
source_id equal:              True
dataset_id equal:             True
```

## 5. Missing-semantics reproduction

Pre-remediation injected frame had `bar_available_at` and valid provenance, but no
`bar_timestamp_semantics`, with availability equal to event time:

```text
accepted: True
resolved semantics: open_time
```

## 6. Mode-field reproduction

Pre-remediation accepted all three irrelevant-field families:

```text
INJECTED + seed/start_time/bar_counts/knowledge_cutoff
BINANCE + seed/start_time/bar_counts
SYNTHETIC + event_start/knowledge_cutoff
```

## 7. Strict mode contracts

`TrendlineResearchDataSpec` now enforces:

```text
SYNTHETIC: seed, start_time, bar_counts only
BINANCE:   event_start, knowledge_cutoff only
INJECTED:  no source-selection fields
```

Incompatible fields raise `ValueError` naming field and mode. `to_dict()` emits only fields
relevant to selected mode.

## 8. Timestamp-semantics enforcement

Injected frames must explicitly provide `frame.attrs["bar_timestamp_semantics"]`. Missing and
unknown values fail closed.

```text
OPEN_TIME:  bar_available_at > event timestamp for every row
CLOSE_TIME: bar_available_at == event timestamp for every row
```

`CLOSE_TIME_INDEX` provenance requires `CLOSE_TIME` semantics. Existing timezone, ordering,
uniqueness, and cutoff validation remain strict.

## 9. Availability identity

Added `RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION`:

```text
trendlines.research-availability-id.v1
```

`build_research_availability_id()` hashes `source_id`, the complete UTC availability sequence as
native UTC nanoseconds, timestamp semantics, provenance, and the semantics version through the
canonical SHA-256 identity seam. No `repr()`, Python `hash()`, OHLCV rehash, or row dictionaries.

## 10. Dataset identity integration

`TrendlineResearchDatasetIdentity` now carries and serializes:

```text
availability_ids: Mapping[timeframe, availability_id]
```

Preparation validates each frame once, computes one source reference and one availability ID per
timeframe, and binds both to `dataset_id`.

```text
same source / same availability:
  source_id stable
  availability_id stable
  dataset_id stable

same source / changed availability:
  source_id stable
  availability_id changed
  dataset_id changed
```

## 11. Manifest evidence

Manifest metadata now contains compact `availability_evidence` per timeframe:

```text
availability_id
availability_start
availability_end
availability_source
timestamp_semantics
```

Full timestamp sequence is represented only by `availability_id`.

## 12. Dedicated tests

Added exactly eight non-parametrised tests to `test_research_data.py` covering missing semantics,
OPEN_TIME equality, CLOSE_TIME mismatch, stable/changed availability identity, and all three
mode-incompatible field families.

## 13. Performance evidence

Seven repetitions, seed `42`, UTC synthetic frames, two timeframes (`1h`, `4h`), total bars:

| total bars | synthetic median | injected median |
|---:|---:|---:|
| 1,000 | 6.794 ms | 5.994 ms |
| 10,000 | 26.359 ms | 34.064 ms |
| 100,000 | 225.622 ms | 260.160 ms |

Prior L2-A1 evidence was `4.719/4.327 ms`, `24.227/23.354 ms`, and `278.554/227.216 ms`.
R1 100,000-bar deltas: synthetic `-52.932 ms`, injected `+32.944 ms`; both satisfy the `100 ms`
budget. Direct availability digest medians were `0.075 ms`, `0.171 ms`, and `1.010 ms` for
1,000/10,000/100,000 timestamps. Configuration resolution median: `0.014 ms`.

Two-timeframe call counts:

```text
source hash calls:       2
availability hash calls: 2
```

## 14. Canonical regression

```text
395 collected
395 passed
```

## 15. Binance bridge regression

```text
8 passed
0 real provider calls
```

No application-layer bridge or pagination code changed.

## 16. Consumer regression

```text
71 passed
```

## 17. Offline regression

```text
20 passed
```

## 18. Static validation

```text
targeted Ruff: passed
compileall: passed
git diff --check: passed
repository-local Python caches removed
```

## 19. Files changed

R1 delta:

```text
src/libs/models/trendlines/workflows/research/contracts.py
src/libs/models/trendlines/workflows/research/data.py
src/libs/models/trendlines/workflows/research/__init__.py
src/libs/models/trendlines/tests/test_research_data.py
src/libs/models/trendlines/docs/research.md
src/libs/models/trendlines/docs/data.md
plans/coder-to-orchestrator-trendlines-l2a1-r1-availability-identity-v1.md
```

Existing L2-A1 dirty paths remain present. No unexpected path is authorized. No commit was
created.

## 20. Git status

Final status must contain only existing L2-A1 paths plus this R1 handoff. Repository-local Python
caches are removed.

## 21. Residual risks

Persistent evidence storage and replay diagnostics remain unimplemented and belong to L2-A2. No
real Binance validation was performed; bridge tests remain mocked.

## 22. Recommended next phase

```text
L2-A2 — Causal replay, diagnostics and evidence APIs
```

Do not begin L2-A2 in R1.
