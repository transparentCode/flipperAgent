# Mature Trendlines L1-B2-R1
## Fail-Closed RegimeV2 History-Limit Override

### 1. Disposition

Implemented the narrow L1-B2-R1 remediation. Explicit RegimeV2 history-limit
overrides now fail closed unless they are positive integers. Omitted overrides
use the history object's YAML-resolved per-key context policy. No commit was
created.

### 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
HEAD:   2fbeabb96099a62a145fc8905b800d3509dece8c
subject: feat: add causal trendline snapshot identities
```

The existing L1-B2 implementation and handoff were already uncommitted and
were preserved.

### 3. Worktree proof

Before R1, dirty paths were limited to the existing L1-B2 implementation,
tests and handoff. R1 added only the two RegimeV2 implementation changes, two
consumer-test changes and this handoff. No branch switch, reset, stash, merge,
rebase, cherry-pick or commit was performed.

### 4. Original invalid-limit reproduction

Using two recorded boundary snapshots, the pre-change adapter accepted both
invalid explicit values:

```text
valid 80 1.0 count 1
valid 100 1.0 count 2
limit 0 selected 1 error None
limit -1 selected 1 error None
```

The prior `max(int(resolved_limit), 1)` path silently converted both values
to a one-item query.

### 5. Typed validation

`TrendlineFeatureConfig.__post_init__()` now calls one shared constant-time
validator. The validator accepts `None` or a positive `int`, rejects `bool`,
non-integer values, zero and negative values, and raises `ValueError` with a
`history_limit` message. `_signal_history()` validates direct calls as well,
so its private seam cannot reintroduce clamping.

### 6. YAML-default behaviour

When `history_limit is None`, `_signal_history()` calls:

```python
snapshot_history.context_limit(asset, timeframe)
```

The history object owns the resolved YAML policy. The adapter no longer imports
or reloads `load_trendlines_config` or `resolve_snapshot_history_policy` during
history queries.

### 7. Explicit override behaviour

A positive explicit value is passed directly as the query limit. No conversion,
clamping or fallback occurs. Tests cover policy context-limit selection and a
positive explicit override that returns the requested shorter history.

### 8. CLI validation

`--trendline-history-limit` remains `None` by default and now uses the named
`_positive_history_limit` argparse parser:

```text
omitted:  None
8:        accepted
0:        argparse parse failure
-1:       argparse parse failure
```

The collector still constructs storage through the canonical YAML-backed
history policy and does not convert the query override into storage capacity.

### 9. Tests

Added exactly five tests:

```text
adapter:
  history_limit=None uses policy context_limit
  positive explicit limit overrides query length
  zero config limit rejected
  negative config limit rejected

collector:
  CLI rejects zero and negative explicit limits
```

Combined adapter and collector result:

```text
18 passed
```

This is the existing 13-test consumer set plus five R1 tests.

### 10. Canonical regression

```text
src/libs/models/trendlines/tests: 344 passed
```

History-focused regression:

```text
test_revision_history.py + test_boundary_history.py: 29 passed
```

### 11. Consumer regression

```text
tests/test_regime_v2_trendline_feature_producer.py
tests/test_regime_v2_shadow_binance_collector.py
18 passed
```

No trendline feature values or history identity semantics changed.

### 12. Offline regression

```text
test_optimizer.py
test_optimization_integration.py
test_trendlines_pipeline_workflow.py
20 passed
```

### 13. Static validation

```text
targeted compileall: passed
targeted Ruff:       passed
git diff --check:    passed
repository-local Python caches: removed
```

### 14. Files changed

R1 changed only:

```text
M  src/libs/models/regime_v2/adapters/trendline_feature_producer.py
M  src/libs/models/regime_v2/scripts/collect_shadow_binance.py
M  tests/test_regime_v2_trendline_feature_producer.py
M  tests/test_regime_v2_shadow_binance_collector.py
?? plans/coder-to-orchestrator-trendlines-l1b2-r1-history-limit-validation-v1.md
```

Existing L1-B2 dirty paths remain untouched and uncommitted.

### 15. Git status

Final status contains the existing L1-B2 dirty paths plus the four R1 changes
and this handoff. No unrelated path is present. No commit was created.

### 16. Residual risks

The Binance candle event label still uses candle `open_time` while completed
candle data becomes available at candle close time. Correcting `known_at` and
signal-context timestamps belongs to L1-B3 and was not changed here.

### 17. Recommended next phase

```text
L1-B3 — Signal history and OHLCV-context timestamp alignment
```

R1 is complete. Do not commit or begin L1-B3 in this phase.
