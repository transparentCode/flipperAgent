# RegimeV2 PA Paper Rollout Runbook

Candidate:

- `BNBUSDT|1h`
- `PriceAction`
- direction `1`
- paper action: suppress to flat
- live selection: unchanged

## Default state

Checked-in config must stay disabled:

```yaml
paper_enabled: false
paper_log_enabled: false
paper_persist_enabled: false
```

RegimeV2 live gate must stay disabled:

```yaml
enabled: false
```

## Safety check

Default disabled check:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_safety \
  --config configs/selection.yaml \
  --output-json research/regime_v2_pa_paper_safety.json \
  --output-md research/regime_v2_pa_paper_safety.md
```

Expected:

- `safe: true`
- `rollout_ready: false`
- `enabled_pair_count: 0`
- `violation_count: 0`

## Temporary runtime paper switch

Only for controlled paper observation, set the `BNBUSDT -> 1h -> regime_v2_pa_asset_guardrail` block to:

```yaml
paper_enabled: true
paper_log_enabled: true
paper_persist_enabled: true
paper_persist_path: logs/regime_v2_pa_asset_paper_decisions.jsonl
model_name: PriceAction
asset: BNBUSDT
timeframe: 1h
direction: 1
```

Then run the required enabled check:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_safety \
  --config configs/selection.yaml \
  --require-enabled
```

Expected:

- `safe: true`
- `rollout_ready: true`
- `enabled_pairs: ["BNBUSDT|1h"]`
- `live_gate_enabled_pairs: []`

If this command exits non-zero, do not run paper observation.

## Snapshot and action checks

After generating paper decisions, run the `pa_paper_snapshots` CLI to confirm whether changed rows have usable alternate candidates. Latest refreshed result: snapshot schema is present, but changed rows currently have no alternate paper candidate after suppression.

After generating labeled outcomes, run the `pa_paper_actions` CLI to compare hard suppression with reduced-size variants. The latest offline result still recommends keeping `suppress_to_paper` over scaled baseline variants.

Current rollout posture after refreshed robustness: hold off. Average lift is still positive, but a recent rolling window is negative.

Run the `pa_paper_window_diag` CLI to diagnose the negative rolling window before any runtime paper observation. Latest result: the failure window is a real localized miss where PriceAction longs worked and flat suppression missed the move.

Run the `pa_paper_ctx` CLI to discover simple context filters. Latest result: only recency/time-window filters separated the failure pocket cleanly; score, edge, and conviction thresholds did not. This suggests temporal drift rather than a stable confidence-score filter.

Run the `pa_paper_dg` CLI to simulate non-live drift/streak pause gates. Latest result: `rolling_avg_neg_3` is the best diagnostic gate, recovering 6 missed wins with 0 lost avoided losses on the refreshed sample.

Run the `pa_paper_dg_matrix` CLI to validate that gate across horizons/fees. Latest result: the gate improves all 12 cells, but only 6/12 cells pass strict validation because short horizons lose avoided-loss rows and some rolling windows remain unstable.

Run the `pa_paper_gs` CLI to search stricter pause-rule variants. Latest result: `rolling_avg_below_002_3` improves all 12 cells and passes 9/12, but the remaining 3-bar cells still lose one avoided-loss row each.

Run the `pa_paper_hz` CLI to slice the 6W report by horizon. Latest result: `rolling_avg_below_002_3` passes all 12/24-bar long-horizon cells and all 6-bar mid cells; only 3-bar cells fail. This makes it a long-horizon-only paper candidate, still disabled by default.

Run the `pa_paper_hzc` descriptor check before any paper observation. Latest result: descriptor exists for BNBUSDT 1h PriceAction direction 1, valid horizons are 6/12/24, invalid horizon is 3, candidate/runtime flags remain disabled, live gate remains disabled, and safety recommendation is `metadata_candidate_disabled_ok`.

For phase navigation and commit hygiene, see `PHASE_INDEX.md` and `REPO_REVIEW.md`.

## Disable recommendation check

After generating monitor output, run:

```bash
PYTHONPATH=src python -m libs.models.regime_v2.scripts.pa_paper_disable \
  --monitor research/regime_v2_pa_paper_monitor.json \
  --output-json research/regime_v2_pa_paper_disable.json \
  --output-md research/regime_v2_pa_paper_disable.md
```

Possible recommendations:

- `continue_monitoring`
- `continue_monitoring_insufficient_sample`
- `pause_for_review`
- `disable_paper_observation`

The recommendation layer does not edit config.

## Kill switch

Set back to:

```yaml
paper_enabled: false
paper_log_enabled: false
paper_persist_enabled: false
```

## Hard rules

- Do not enable live gate.
- Do not enable this globally.
- Do not enable for BTCUSDT, ETHUSDT, or SOLUSDT.
- Paper log path must remain separate from `logs/regime_v2_shadow_decisions.jsonl`.
- No live promotion before monitoring and automatic disable criteria exist.
