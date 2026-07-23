---
goal: profile confirmed extrema provider public path without optimization
stage: coder-to-orchestrator
date_created: 2026-07-23
last_updated: 2026-07-23
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, trendline-v2, profiling]
---

# Trendline V2 Phase 7A Profiling

## Status

`READY_FOR_ORCHESTRATOR_REVIEW`

## Scope

Offline synthetic profiling only. Provider source, configuration, YAML, runtime,
registry and public API were unchanged. No network, market data, Numba, discovery
API, TVLC, tracking, interactions, MTF, Regime integration or parameter promotion.

## Branch

- Branch: `perf/trendline-v2-phase-7-profiling-v1`.
- Base: merged-main commit `a9d0e492ebe91b9c54f60d0b9f594e24a63873eb`.
- Working tree: root checkout only; no new worktree.

## Changed Files

- `scripts/benchmark_trendline_v2_provider.py`
- `tests/models/trendline_v2/test_provider_benchmark_harness.py`
- This handoff.

## Harness

Command shape:

```text
PYTHONPATH=src .venv/bin/python scripts/benchmark_trendline_v2_provider.py \
  --repeats 20 --output /tmp/trendline_v2_profile.json
```

The harness constructs immutable requests before timing, performs one warm-up,
measures complete `ConfirmedExtremaPairProvider.generate(request)` calls with
`perf_counter_ns`, validates identical semantic digests and input immutability,
profiles representative calls with `cProfile`, and measures selected calls with
`tracemalloc`. JSON writes are atomic and output path is explicit.

## Workloads

- `sparse_no_candidate_scan`: flat input; rows `7, 14, 28, 56, 112, 224`;
  `ABSTAINED / INSUFFICIENT_INPUT`.
- `normal_success`: two support extrema; rows `7, 14, 28, 56, 112, 224`;
  `SUCCESS` with one candidate.
- `candidate_rich_below_cap`: alternating support/resistance extrema; rows
  `7, 15, 31, 63`; complete pair construction below configured caps.
- `hypothesis_limit`: same dense fixture; rows `7, 15, 31, 63, 127, 255`;
  `max_hypotheses=100`, guard activates at row `31`.
- `output_limit`: same dense fixture; rows `7, 15, 31, 63`;
  `max_output_candidates=10`, guard activates at row `15`.
- `irregular_timestamp_space`: nonuniform elapsed UTC timestamps; rows
  `7, 14, 28, 56, 112`; successful timestamp-space path.

Every case uses explicit six-field provider configuration. Lookback is derived
only for each synthetic request to include its fixture history; no value enters
provider defaults or model configuration.

## Validation

Focused harness tests: `4 passed`.

Full Trendline V2 suite: `89 passed` (`85` provider baseline plus four harness
tests). Protected Trendline Family suite: `399 passed`. Ruff, compileall and
`git diff --check`: passed.

Profile execution completed once with `--repeats 20 --warmups 1`. Output was
written to `/tmp/trendline_v2_profile_phase7a.json`; it is not repository
evidence and is not committed.

Required after implementation:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q -ra
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
ruff check src/libs/models/trendline_v2 tests/models/trendline_v2 scripts/benchmark_trendline_v2_provider.py tests/models/trendline_v2/test_provider_benchmark_harness.py
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2 scripts/benchmark_trendline_v2_provider.py
git diff --check
```

The generated profile JSON is benchmark evidence, not committed source or
protected research artifact.

## Provider Configuration Matrix

All requests used:

```text
left_confirmation_bars=1
right_confirmation_bars=1
min_extrema_per_role=2
```

Workload-specific caps:

```text
sparse/normal/irregular: max_hypotheses=100000, max_output_candidates=100000
candidate_rich:          max_hypotheses=10000,  max_output_candidates=10000
hypothesis_limit:        max_hypotheses=100,    max_output_candidates=100000
output_limit:            max_hypotheses=100000, max_output_candidates=10
```

`lookback_duration_seconds` was request-local and equal to fixture elapsed span
plus `3600.0`; no value entered provider defaults or YAML.

## Timing Evidence

Values are p50/p95 nanoseconds in ladder order. Repeats: `20`.

| Workload | Rows | Candidates | p50 ns | p95 ns |
|---|---:|---:|---|---|
| sparse scan | 7,14,28,56,112,224 | 0,0,0,0,0,0 | 27520,25042,38812,67374,124333,238708 | 56875,46000,54584,78250,138709,263208 |
| normal success | 7,14,28,56,112,224 | 1,1,1,1,1,1 | 173104,195312,220208,282062,406146,664917 | 186500,231375,258791,340958,427000,716583 |
| candidate rich | 7,15,31,63 | 6,42,210,930 | 889875,5979437,31370375,157948041 | 1071666,6110916,39695541,167297625 |
| hypothesis guard | 7,15,31,63,127,255 | 6,42,0,0,0,0 | 838312,5762083,106583,207625,410708,842479 | 881958,5877500,120416,238333,427125,932375 |
| output guard | 7,15,31,63 | 6,0,0,0 | 868562,4673749,24728708,130112625 | 970917,4784625,26363875,143470958 |
| irregular UTC | 7,14,28,56,112 | 1,1,1,1,1 | 169041,190354,216333,280417,404750 | 188833,296083,235167,319833,415625 |

Min/max were retained in JSON. Timing includes complete provider calls only;
fixture construction, profiling and JSON output were outside timed regions.

## Memory Evidence

One representative call per required path:

| Workload | Rows | Status/reason | Current bytes | Peak bytes |
|---|---:|---|---:|---:|
| normal success | 224 | success | 3457 | 8952 |
| candidate rich | 63 | success | 865618 | 1052888 |
| hypothesis guard | 63 | abstained / hypothesis_limit_exceeded | 280 | 13324 |

## cProfile Evidence

Representative cumulative leaders:

- Normal success, 224 rows: `_candidate_record` `0.001228s`,
  `_confirmed_extrema` `0.000667s`, `LineGeometry.value_at` `0.000512s`,
  `primitive` `0.000310s`.
- Candidate rich, 63 rows / 930 candidates: `_candidate_record`
  `0.428194s`, `primitive` `0.259639s`, `LineCandidate.create` `0.240861s`,
  `deterministic_hash` `0.201287s`.
- Output guard, 63 rows / 930 constructed candidates:
  `_candidate_record` `0.549450s`, `LineCandidate.create` `0.348999s`,
  `primitive` `0.321535s`, `LineCandidate.__post_init__` `0.228912s`.
- Hypothesis guard, 63 rows: `_confirmed_extrema` `0.000458s`,
  `_datetime_from_ns` `0.000118s`, built-in `all` `0.000112s`.

The dense `_candidate_record` region includes body validation plus candidate and
evidence construction. It is not an isolated numeric bottleneck.

## Scaling And Decision

Sparse and hypothesis-guard paths scale approximately with row count. Normal and
irregular one-candidate paths also grow with row count. Dense paths grow with pair
count and intermediate validation; 930 candidates at 63 rows reached roughly
158 ms p50 in final run. Synthetic results are not production latency claims.

Measured Numba study targets, ordered by evidence:

1. `_candidate_record` body-validation segment: highest provider-side region, but
   mixed with construction; isolate before any kernel study.
2. `_confirmed_extrema`: repeated linear scan and guard-path work; retain Python
   until isolated cost is measured.
3. `LineGeometry.value_at`: repeated intermediate projection; candidate only after
   body-validation isolation.

Remain Python-owned: `generate`, `ProviderResult` validation, candidate/evidence
construction, deterministic identity hashing, and semantic serialization.

Cold start: one untimed warm-up per request. Cold-start cost was not separately
quantified. Residual uncertainty: synthetic density, timestamp spacing and small
ladder sizes do not represent market distributions or production workloads.

Recommendation: `RETAIN_PYTHON`. No isolated numeric loop dominates public path;
Phase 7B Numba study remains unauthorized.

## Decision Boundary

No Numba authorization is issued by this handoff. Any Phase 7B kernel study
requires separate orchestrator approval after reviewing measured profiles,
memory, scaling and cold-start evidence.
