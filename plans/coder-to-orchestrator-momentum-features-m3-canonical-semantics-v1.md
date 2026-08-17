---
goal: Remediate M3 Momentum RSI/MACD evidence with repository market history
stage: coder-to-orchestrator
date_created: 2026-08-17
last_updated: 2026-08-17
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, momentum, rsi, macd, feature-semantics, m3, remediation]
source_base: 6feedc278db5fe077ac94a30dc72195e9fcafcc1
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-momentum-features-m3-canonical-semantics
---

# M3R Momentum RSI/MACD canonical-semantics remediation

## Result

The evidence remediation is complete in the existing isolated M3 worktree. The
pure RSI/MACD calculators and Momentum core boundary are unchanged. The
certification now combines the retained synthetic edge corpus with four
explicit, independently identified repository market members, selects horizons
over the union, records actual legacy startup lookbacks, and proves the
selected capacities fit the current bounded Decision BarStore.

```text
MOMENTUM_M3_CANONICAL_FEATURE_SEMANTICS_REMEDIATION_READY_FOR_REVIEW
```

M3 still stops before Decision registration, lane creation, publication, and
any signal/strategy/config/model changes.

## Starting state and scope

```text
base SHA: 6feedc278db5fe077ac94a30dc72195e9fcafcc1
worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-momentum-features-m3-canonical-semantics
checkout: detached, existing M3 worktree
```

Only these M3-owned paths were changed or regenerated:

- `scripts/certify_momentum_features_m3.py`
- `tests/decision/certification/test_m3_momentum_feature_semantics.py`
- `artifacts/decision_m3/m3_momentum_feature_semantics_certification.json`
- this coder handoff

`src/apps/decision_app/features/momentum.py` remains unchanged. No Decision
catalog/runtime registration, config, legacy app, risk/execution, Docker, or
model-math change was made. No commit, merge, or push was performed.

## Repository evidence members

Each member is parsed independently; no unrelated files are concatenated into a
synthetic continuous series. The harness validates finite closes, strict UTC
ordering, exact 1h/4h spacing, and complete-row filtering where the CSV exposes
`complete`.

| Member | Asset/TF | Rows | Provenance | SHA-256 |
| --- | --- | ---: | --- | --- |
| `btc_1h_temporal_normalized` | BTCUSDT/1h | 312 | canonical normalized artifact | `763637b593f42923eda67fcb1d7a0ed2bf176b7dc55865f24b72a252ba00bd4f` |
| `btc_4h_saturating_normalized` | BTCUSDT/4h | 726 | canonical normalized artifact | `2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42` |
| `btc_4h_candidate_normalized` | BTCUSDT/4h | 732 | canonical normalized artifact | `b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150` |
| `eth_4h_tv_research_input` | ETHUSDT/4h | 3124 | research input, not canonical ingestion | `49359cc6c94919767830ded5a008edf6ed8299663ac9ffe3868546f776c75964` |

Relative paths and source metadata are included in the artifact. The ETH
research CSV is labeled as research input; it is not promoted to a canonical
ingestion fixture. No better repository-owned normalized ETHUSDT/4h artifact
was found in the explicit repository search.

## Combined horizon selection

The candidate ladder remains multipliers `1, 2, 4, 8, 16` over RSI
`period + 1` and MACD `slow + signal - 1`. A candidate must be eligible for
every required repository member and have exact zero direction and
tradable/neutral disagreements over the complete synthetic plus applicable
repository corpus. Numerical p95 convergence remains visible and no arbitrary
floating-point tolerance was added.

| Route | Old synthetic-only candidate | Combined selected candidate | RSI bars | MACD bars |
| --- | --- | --- | ---: | ---: |
| BTCUSDT/1h | x2 | **x4** | 60 | 136 |
| BTCUSDT/4h | x4 | **x8** | 120 | 272 |
| ETHUSDT/4h | x16 | **x16** | 208 | 544 |

The combined hard-gate results are:

- BTCUSDT/1h: x2 retains 6 repository direction/tradable disagreements; x4
  reaches 0.
- BTCUSDT/4h: x4 retains 4 and 1 disagreements across the two independent
  repository members; x8 reaches 0 for both.
- ETHUSDT/4h: the repository member reaches 0 at x8, while the synthetic
  trend-reversal family requires x16; the union therefore selects x16.

The artifact separately reports synthetic versus repository error and
score/conviction drift, as well as combined route metrics. Short members are
explicitly marked ineligible rather than contributing a false zero.

## Legacy configuration and restart evidence

Resolved intended parameters remain:

| Route | RSI | MACD |
| --- | ---: | --- |
| BTCUSDT/1h | 14 | 12/26/9 |
| BTCUSDT/4h | 14 | 12/26/9 |
| ETHUSDT/4h | 12 | 12/26/9 via ConfigManager fallback |

The legacy `RawIndicatorPipeline` discrepancy remains explicit: ETHUSDT/4h
instantiates RSI period 12 but no MACD, while ConfigManager resolves the
intended MACD fallback. `signal_app` was not modified.

Observed legacy pipeline startup lookbacks, recomputed from live code:

```text
BTCUSDT/1h  250
BTCUSDT/4h   34
ETHUSDT/4h   13
```

The artifact includes indicator-level lookbacks and actual-lookback
prime/update restart cases where the indicator exists. ETH's actual MACD
restart evidence is explicitly `not instantiated`; intended Decision MACD is
covered only by the stateless full-prefix/bounded evidence. The generic
1x/2x/4x restart sensitivity study remains alongside the actual-lookback
study.

## BarStore practicality

The current Decision `BarStore` was instantiated with one distinct
`MarketSeriesKey` per certified route and each selected effective capacity was
filled completely. Capacity uses `max(RSI bars, MACD bars)` per route, not a
sum within a series:

```text
BTCUSDT/1h: 136 retained
BTCUSDT/4h: 272 retained
ETHUSDT/4h: 544 retained
total:       952 retained bars
```

All `capacity_for()` and retained counts match exactly; the three series are not
cross-route summed. The in-memory history interface accepted positive limits
for the selected capacities. A platform-dependent tracemalloc measurement is
not part of deterministic artifact identity. Final model-mix resource
certification remains deferred:

`FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED`

## Artifact integrity

```text
artifact: artifacts/decision_m3/m3_momentum_feature_semantics_certification.json
artifact SHA-256: 6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c
deterministic identity SHA-256: d1a09f827f4814dc13b06e8f0061d270c29d3c47d4c852fc5fc3e76d1740fa63
measurement payload SHA-256: d73ef1555fb874990ab6d92a0c36f3378b13bb28d4e4dccb7bb0db6b1d6656b5
```

The certification script was run twice from the same source SHA; the complete
artifact bytes and SHA-256 matched. Identity covers source/config/corpus and
recommendation identity. Measurement coverage includes route evidence,
repository identities, discrepancy evidence, BarStore practicality, and
recommendation evidence. Focused regressions prove that tampering either a
measurement, repository identity, or BarStore evidence changes the measurement
digest.

## Validation

```text
M3R focused certification tests                 25 passed
tests/models/momentum + affected feature/config  74 passed
tests/decision                                  386 passed
```

Static checks already passing on M3-owned Python:

```text
Ruff check                         passed
Ruff format --check                passed
compileall                         passed
git diff --check                   passed
artifact determinism               passed; identical full SHA-256 on rerun
artifact identity/measurement      passed
repo-local cache cleanup           passed; no generated M3 caches retained
```

The M3R focused certification suite includes the final repository-identity and
BarStore measurement-digest regressions.

## Two-pass self-review

### Pass 1 — quantitative/evidence correctness

- Repository members are explicit, hashed, separately evaluated, and not
  concatenated.
- Timestamp spacing, UTC identity, finite closes, complete-row filtering, and
  causal cutoffs are validated.
- Selection uses the full required synthetic + repository union and fails closed
  for short/missing members.
- Route parameters and the ETH legacy MACD omission remain visible.
- Actual legacy startup lookbacks are measured rather than inferred from the
  candidate ladder.
- Score/conviction drift is reported by evidence class; no profitability claim
  is made.

### Pass 2 — architecture/scope

- RSI/MACD calculators remain pure and stateless.
- No generic fixture framework or feature-state/checkpoint machinery was added.
- BarStore proof is a bounded certification probe, not a capacity subsystem.
- No Decision registration, lane, publication, config, legacy-app, model-math,
  or D11 work was performed.
- M4 remains responsible for integration and final model-mix recertification.

## Residual risks and next gate

- Selected histories are evidence-backed M4 candidates, not production feature
  definitions until M4 reviews and freezes them.
- The ETH sparse-feature legacy discrepancy remains a separate compatibility
  decision and was intentionally not fixed here.
- Final Decision LIVE/REPLAY/restart parity and final model-mix resource
  recertification remain M4 gates.

MOMENTUM_M3_CANONICAL_FEATURE_SEMANTICS_REMEDIATION_READY_FOR_REVIEW
