# RegimeV2 Repo Review

This file captures Phase 6Z repository hygiene and commit-readiness notes.

## Working-tree snapshot

Observed before this review note was added:

- Modified tracked files: 12.
- Untracked files overall: 129.
- RegimeV2 core files: 67.
- RegimeV2 selection helper files: 28.
- RegimeV2 focused tests: 30.
- RegimeV2 research artifacts: 66.
- Separate Alert App work is present and should not be mixed with a RegimeV2 commit.

## Runtime posture

The current RegimeV2 posture is disabled by default:

- Live trend gate: disabled.
- PA paper runtime: disabled.
- PA paper logging/persistence: disabled.
- Long-horizon candidate descriptor: present, metadata-only, disabled.
- Latest descriptor validation: safe with zero violations.

## Recommended staging groups

### 1. RegimeV2 core

- `src/libs/models/regime_v2/`

This includes the deterministic engine, feature modules, policy/fusion/evaluation layers, scripts, and docs.

### 2. Selection integration

- `configs/selection.yaml`
- `src/libs/selection/selection_layer.py`
- `src/libs/selection/overlays/regime_v2_trend_gate.py`
- `src/libs/selection/regime_v2_*.py`

Review that all runtime switches remain disabled before staging.

### 3. Tests

- `tests/test_regime_v2*.py`
- `tests/test_selection_layer.py`

Latest validation notes:

- Broad focused suite before 6X: 154 passed.
- 6X focused tests: 3 passed.
- 6Y focused tests: 4 passed.
- Some later broad commands were blocked by the local safety checker, not by failing assertions.

### 4. Research summaries

Prefer committing Markdown summaries only:

- `research/regime_v2_*.md`

JSON reports are generated evidence. Commit them only if exact report reproduction matters for review.

## Keep local by default

- Runtime logs under `logs/`.
- Generated JSONL outcome files in `research/`.
- Unrelated Alert App files under `src/apps/alert_app`, `tests/alerts`, `configs/alerts.yaml`, and the alert app plan.
- Pre-existing tracked changes outside the narrow RegimeV2 path unless reviewed separately.

## High-signal evidence files

Useful review artifacts:

- `research/regime_v2_pa_paper_robustness.md`
- `research/regime_v2_pa_paper_window_diag.md`
- `research/regime_v2_pa_paper_ctx.md`
- `research/regime_v2_pa_paper_dg.md`
- `research/regime_v2_pa_paper_dg_matrix.md`
- `research/regime_v2_pa_paper_gs.md`
- `research/regime_v2_pa_paper_hz.md`
- `research/regime_v2_pa_paper_hzc.md`
- `research/regime_v2_pa_paper_safety.md`
- `research/regime_v2_pa_paper_monitor.md`
- `research/regime_v2_pa_paper_disable.md`

## Commit readiness conclusion

RegimeV2 is ready to stage as a disabled, offline-first and shadow-first module if the commit is scoped carefully.

The long-horizon PA candidate is explicit but not enabled:

- Asset/timeframe: BNBUSDT 1h.
- Target: PriceAction direction 1.
- Rule: rolling_avg_below_002_3.
- Valid horizons: 6, 12, 24 bars.
- Invalid horizon: 3 bars.

Next work should either collect more out-of-sample paper evidence for this long-horizon candidate or move into deterministic playbook redesign.
