# Mature Trendlines L1-B1-R1 — Direct Component Identity Handoff

## 1. Disposition

L1-B1-R1 remediation is complete. Direct extractor and fitter state now
participate in configuration and checkpoint identity. Unsupported canonical
values fail closed. L1-B2 has not started. No commit was created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- HEAD: `989a64c71ebfa1811cf795cbce0f51e2abba6922`
- Subject: `feat: enforce trendline extractor execution policy`
- L1-B1 implementation remained uncommitted throughout R1.

## 3. Worktree proof

Pre-change dirty scope matched authorised L1-B1 implementation and:

```text
plans/coder-to-orchestrator-trendlines-l1b1-snapshot-identity-v1.md
```

No reset, restore, stash, merge, rebase, cherry-pick, branch switch, dependency
installation, or network call was performed.

## 4. Direct extractor defect reproduction

Two classified custom extractor instances with different pivot indexes were
run through otherwise identical pipelines. Before R1:

```text
extractor config_id equal:      True
extractor checkpoint_id equal:  True
extractor revision_id equal:    False
```

The output changed, but checkpoint configuration identity did not.

## 5. Direct fitter defect reproduction

Two custom fitter instances with different behaviour markers were run with the
same extractor and source. Before R1:

```text
fitter config_id equal:      True
fitter checkpoint_id equal:  True
fitter revision_id equal:    False
```

## 6. Unsupported-value reproduction

Before R1, `canonical_json(object())` returned a process-dependent value such
as:

```text
{"__repr__":"<object object at 0x1228f3ed0>"}
```

## 7. Strict canonicalisation remediation

`identity.py` now defines `UnsupportedIdentityValueError` and raises it for
unsupported Python types. Arbitrary `repr()`, `str()` fallback, process hash,
pickle, and object-address identity are absent. Stable `pathlib.Path`
canonicalisation was added for supported configuration values.

## 8. Component identity provider contract

Added public `TrendlineIdentityProvider` protocol:

```python
def trendline_identity_payload(self) -> Mapping[str, Any]: ...
```

`resolve_component_identity_payload()` is the single resolver. It validates
component role, module, qualified class name, canonical registered name,
non-empty mapping payload, and canonical value support.

## 9. Registered component identity

Named components retain canonical registry names and resolved parameters. The
resolver additionally records deterministic built-in component state, so
omitting or explicitly supplying equivalent constructor defaults cannot omit
behaviour-affecting state from configuration identity.

## 10. Direct built-in identity

Registered built-in extractors and fitters are dataclasses. Their constructor
fields are resolved centrally. Nested component fields recurse through the
same resolver. Direct `FractalPivotExtractor` and `PathfindingFitter` instances
with identical state are stable; changing extractor or fitter fields changes
configuration and checkpoint IDs.

## 11. Direct custom extractor identity

Classified custom extractors must provide a non-empty
`trendline_identity_payload()` mapping. Missing, empty, non-mapping, or
unsupported payloads fail closed. Existing execution-capability validation
remains independent and still rejects unclassified extractors first.

## 12. Direct custom fitter identity

Custom fitters follow the same explicit provider contract. A fitter without a
provider is rejected before fitting. Different provider payloads change
configuration and checkpoint IDs; separate instances with identical payloads
remain stable.

## 13. Configuration/checkpoint evidence

After R1, deterministic custom component reproduction produced:

```text
extractor config_id changed: True
extractor checkpoint_id changed: True
extractor revision_id changed: True
fitter config_id changed: True
fitter checkpoint_id changed: True
fitter revision_id changed: True
```

Pipeline metadata now includes `extractor_identity` and `fitter_identity`
mirrors; typed checkpoint fields remain authoritative.

## 14. Dedicated tests

Added `test_component_identity.py` with exactly 10 non-parametrised tests:

```text
10 collected
10 passed
```

Coverage includes strict unsupported values, address-free output, named and
direct built-in stability, extractor/fitter state changes, missing custom
providers, distinct custom payloads, and identical custom payload stability.

## 15. Canonical regression

```text
322 tests collected
322 passed
```

Pre-R1 canonical count was 312; R1 adds exactly 10 dedicated tests.

## 16. Consumer regression

```text
tests/test_regime_v2_trendline_feature_producer.py
6 passed
```

RegimeV2 feature semantics were not modified.

## 17. Offline regression

Required workflow group:

```text
test_optimizer.py
test_optimization_integration.py
test_trendlines_pipeline_workflow.py
20 passed
```

Research RDP remains explicit research mode.

## 18. Performance evidence

One deterministic 100,000-bar fixture was used for pre-R1 L1-B1 and R1 paths.
Fixture SHA-256:

```text
799ff2728c1a6f34630b52f5a711dc8c57caed08c018961c3a083d288da56bc9
```

Seven timed repetitions per path, with two warmups:

```text
path                 computed       provided
pre-R1 L1-B1         4.557583 ms     2.551209 ms
R1                   4.563833 ms     2.621541 ms
delta                +0.006250 ms    +0.070332 ms
relative delta       +0.137%         +2.756%
```

Computed-source added median is below `0.5 ms`. Provided-source path does not
regress by both more than `5%` and more than `0.5 ms`. No additional frame,
pivot, ATR, or per-bar identity pass was introduced.

## 19. Static validation

- Targeted Ruff over every changed/new Python file: passed.
- Canonical-package compileall: passed.
- `git diff --check`: passed.
- Repository-local Python caches removed.
- Full-package Ruff remains outside gate because pre-existing package debt is
  unchanged.

## 20. Files changed

```text
M  src/libs/models/trendlines/__init__.py
M  src/libs/models/trendlines/api.py
M  src/libs/models/trendlines/boundary/contracts.py
M  src/libs/models/trendlines/boundary/history.py
M  src/libs/models/trendlines/contracts/__init__.py
M  src/libs/models/trendlines/contracts/contracts.py
A  src/libs/models/trendlines/contracts/identity.py
M  src/libs/models/trendlines/docs/architecture.md
M  src/libs/models/trendlines/docs/boundary.md
M  src/libs/models/trendlines/docs/pipeline.md
M  src/libs/models/trendlines/pipeline/orchestrator.py
M  src/libs/models/trendlines/pivots/capabilities.py
A  src/libs/models/trendlines/tests/test_component_identity.py
M  src/libs/models/trendlines/tests/test_extractor_execution_policy.py
M  src/libs/models/trendlines/tests/test_pipeline_executor.py
A  src/libs/models/trendlines/tests/test_snapshot_identity.py
?? plans/coder-to-orchestrator-trendlines-l1b1-r1-component-identity-v1.md
?? plans/coder-to-orchestrator-trendlines-l1b1-snapshot-identity-v1.md
```

No algorithm, YAML, Trendline V2, boundary geometry, signal calculation,
history policy, evidence, artifact, or RegimeV2 implementation path changed.

## 21. Git status

Final status contains only paths listed in section 20. No commit was made;
L1-B1 remains intentionally uncommitted for review.

## 22. Residual risks

- Custom providers must truthfully include every behaviour-affecting value;
  the contract cannot infer omitted custom state.
- Built-in dataclass identity currently covers all declared dataclass fields;
  future runtime-only fields should be excluded explicitly if introduced.
- L1-B2 still owns ordered, revision-aware history insertion and selection.
- L1-B3 still owns signal context timestamp alignment and future-history checks.

## 23. Recommended next phase

`L1-B2 — Ordered, revision-aware point-in-time snapshot history`.
