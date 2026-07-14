# Coder → Review: Trendline-Family Research Lab Final Remediation

## Scope Executed

Implemented only the four final research-layer gates from `plans/trendline-family-research-lab-final-rereview.md`:

1. Reject the deterministic smoke fixture configuration in local or remote research mode.
2. Bind replay and independently resolved MTF policy identities into one content-addressed export bundle.
3. Add typed cross-asset parameter/sample comparability policy and audit contracts.
4. Add a validation-only stage-specific Plotly sensitivity helper and remove notebook controls that did not drive a reviewed action.

No real-market trial, holdout opening, promotion, Binance adapter redesign, runtime integration, YAML mutation, or RegimeV2 work was performed.

## Files and Symbols Changed

| File | Change |
|---|---|
| `research/trendline_family_research_lab.ipynb` | Uses typed comparability policy/audit, validation-only sensitivity figures, separate MTF policy input/export, and removes dead controls. Default smoke, mocked remote, local/export, replay-position-zero, and MTF+export paths remain executable. |
| `src/libs/models/trendline_family/research_lab/contracts.py` | Added `parameter_policy_hash` to replay context; expanded export identity with replay tracking/MTF and composed MTF policy identities; added typed cross-asset policy, audit, comparison, and row contracts. |
| `src/libs/models/trendline_family/research_lab/replay.py` | Rejects `research_smoke_v1`/smoke provenance through `validate_research_config`; derives asset-independent parameter-policy hashes. |
| `src/libs/models/trendline_family/research_lab/artifacts.py` | Export derives selected replay evidence, binds dataset summary plus replay and MTF identities, and permits a distinct MTF policy only when asset, decision timeframe, model version, and selected decision timestamp match. |
| `src/libs/models/trendline_family/research_lab/tables.py` | Added deterministic cross-asset comparability audit and comparison builders using parameter policy, provider policy, timeframe, UTC window, and row-count evidence. |
| `src/libs/models/trendline_family/research_lab/plotting.py` | Added `build_validation_sensitivity_figure`, which rejects holdout/mixed-stage evidence and plots validation metrics only. |
| `src/libs/models/trendline_family/research_lab/__init__.py` | Exported the new typed contracts and helpers. |
| `tests/models/trendline_family/research_lab/` | Added smoke-config rejection, separate replay/MTF export, strict cross-asset comparability, validation-only sensitivity, dead-control, and combined notebook MTF+export regressions. |
| `.codebase-memory/{artifact.json,graph.db.zst}` | Refreshed required repository index. |

## Blast Radius Considered

- `run_canonical_replay` remains research-only; codebase-memory reports only the research causality helper as an inbound caller.
- `run_phase_i_evaluation` still has no inbound production callers.
- No application/runtime module imports `trendline_family.research_lab`.
- Export schema advances to `research_export_v2`; prior research exports are not mutated or read as runtime state.
- Cross-asset comparison permits asset-specific resolved hashes only when the derived parameter-policy hash, provider policy, timeframe, UTC sample window, and row count satisfy the explicit typed policy.
- MTF export may use a different MTF config version/hash from the replay config, but the composed snapshot must match the selected replay asset, decision timeframe, model version, and timestamp.

## Validation Performed

Focused research layer:

```text
22 passed
```

Full trendline family:

```text
344 passed
```

Trendline family plus RegimeV2 adapters and projected runtime:

```text
372 passed
```

Active non-interference slice:

```text
148 passed, 1 existing OpenTelemetry LoggingHandler deprecation warning
```

Static checks:

```text
Ruff: passed
compileall: passed
notebook JSON/cleared outputs: passed, 34 cells
git diff --check: passed
legacy/Regime/runtime import scan: passed
dead notebook control scan: passed
```

Codebase-memory after reindex:

```text
project: Users-aloobhujia-flipperAgent
nodes: 41,793
edges: 137,514
status: ready
run_phase_i_evaluation callers: none
```

## Not Changed

- `src/apps/ingestion_app/adapters/binance_native.py` and all Binance fetch semantics.
- Canonical candidate provider, tracker, matching, rail, corridor, interaction, event, or MTF compositor behavior.
- Phase-I optimization/evaluator/promotion semantics.
- `configs/trendline_family.yaml` or any runtime configuration.
- RegimeV2, its adapter, signals, selection, strategy, risk, execution, or portfolio paths.
- No real OHLCV was fetched and no real-data artifact was generated.

## Risks or Follow-Up Items

1. `BinanceNativeAdapter` remains Binance USD-M Futures only and uses one historical-kline request; multi-year research still requires a separately reviewed pagination/chunking task.
2. The sensitivity figure is descriptive validation evidence only. It does not rerank trials, read holdout evidence, or apply config patches.
3. Cross-asset comparability defaults to strict equal UTC windows and row counts. A future relaxed policy must be explicit and separately reviewed rather than silently accepting missing-population differences.
4. Final independent research-lab approval is still required before the first bounded candidate/geometry real-data trial.
