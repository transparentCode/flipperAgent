# RegimeV2 Operator Runbook

This runbook captures the current safe operating posture for RegimeV2 after Phase 8D.

## Current posture

RegimeV2 is safe for diagnostic and shadow usage only.

| Area | Current status |
|---|---|
| Live RegimeV2 trend gate | Disabled |
| Controlled shadow rollout | Enabled for selected pairs only |
| PA paper guardrail runtime | Disabled |
| Long-horizon PA candidate | Metadata-only, disabled |
| Transition micro-states | Frozen diagnostic metadata |
| 3-bar PA horizon | Invalid / not validated |
| Runtime logs in `logs/` | Do not commit |

## Safe commands

Use `.venv/bin/python` from the repository root unless explicitly running through another configured environment.

### 1. Runtime safety check

Run this before any release, config review, or runtime toggle discussion.

```bash
.venv/bin/python -m libs.models.regime_v2.scripts.report_8d_safety \
  --selection-config configs/selection.yaml \
  --orchestration-json research/regime_v2_phase8a_playbook_orchestration_gate.json \
  --stop-gate-json research/regime_v2_phase7z_transition_stop_gate.json \
  --output-json research/regime_v2_phase8d_runtime_safety.json \
  --output-md research/regime_v2_phase8d_runtime_safety.md
```

Expected safe result:

```text
safe = true
blockers = []
trend_gate_live_enabled_count = 0
pa_guardrail_enabled_count = 0
transition_runtime_enabled_count = 0
transition_postures = ["frozen_diagnostic"]
invalid_horizon_issues = []
```

If `safe` is false, do not proceed with runtime/paper changes. Read the blockers first.

### 2. Playbook orchestration gate

Use this to regenerate the Phase 8A base playbook orchestration posture.

```bash
.venv/bin/python -m libs.models.regime_v2.scripts.report_playbook_orchestration_gate \
  --stop-gate-json research/regime_v2_phase7z_transition_stop_gate.json \
  --output-json research/regime_v2_phase8a_playbook_orchestration_gate.json \
  --output-md research/regime_v2_phase8a_playbook_orchestration_gate.md
```

Expected current interpretation:

```text
base playbook state machine remains routeable
transition branch remains frozen_diagnostic
transition_runtime_enabled_count = 0
```

### 3. Shadow report with orchestration posture

Use this to combine Phase 5 shadow replay with Phase 8A orchestration posture.

```bash
.venv/bin/python -m libs.models.regime_v2.scripts.report_orchestration_shadow \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --orchestration-json research/regime_v2_phase8a_playbook_orchestration_gate.json \
  --output-json research/regime_v2_phase8b_orchestration_shadow_report.json \
  --output-md research/regime_v2_phase8b_orchestration_shadow_report.md
```

Expected current interpretation:

```text
runtime_action = base_shadow_report_with_transition_diagnostics_frozen
transition_runtime_enabled_count = 0
```

### 4. Base shadow replay report

Use this when you only need the historical Phase 5 shadow replay summary.

```bash
.venv/bin/python -m libs.models.regime_v2.scripts.report_shadow_decisions \
  --log logs/regime_v2_shadow_decisions.jsonl \
  --output-json research/regime_v2_phase5_shadow_report.json \
  --output-md research/regime_v2_phase5_shadow_report.md
```

### 5. PA paper safety and diagnostics

The PA paper branch remains disabled by default. Useful diagnostic commands are:

```bash
.venv/bin/python -m libs.models.regime_v2.scripts.pa_paper_safety
.venv/bin/python -m libs.models.regime_v2.scripts.pa_paper_monitor
.venv/bin/python -m libs.models.regime_v2.scripts.pa_paper_hzc
```

Do not enable PA paper runtime from these diagnostics alone.

## How to interpret the gates

### 7Z transition stop-gate

Artifact:

```text
research/regime_v2_phase7z_transition_stop_gate.json
research/regime_v2_phase7z_transition_stop_gate.md
```

Current decision:

```text
freeze_transition_micro_states_diagnostic
```

Meaning:

- Transition micro-states may appear in diagnostic reports.
- They must not route selection/execution.
- Promotion is blocked by support/robustness/context-tag issues.

### 8A orchestration gate

Artifact:

```text
research/regime_v2_phase8a_playbook_orchestration_gate.json
research/regime_v2_phase8a_playbook_orchestration_gate.md
```

Meaning:

- Base playbook state machine is the only routeable RegimeV2 state layer.
- Transition micro-states are frozen diagnostic metadata.

### 8B orchestration shadow report

Artifact:

```text
research/regime_v2_phase8b_orchestration_shadow_report.json
research/regime_v2_phase8b_orchestration_shadow_report.md
```

Meaning:

- Shadow replay now carries 8A posture metadata.
- Existing Phase 5 shadow report behavior is not changed.

### 8D safety validator

Artifact:

```text
research/regime_v2_phase8d_runtime_safety.json
research/regime_v2_phase8d_runtime_safety.md
```

Meaning:

- This is the first report to check before any operator/release decision.
- A non-empty blocker list means runtime posture is unsafe.

## Safe vs unsafe changes

### Safe

- Regenerate research reports.
- Run shadow report and safety validator.
- Collect shadow logs if the pipeline is available.
- Review diagnostics offline.
- Use `regime_v2` as an offline analyzer and shadow evidence system.

### Unsafe without a new validation phase

- Enabling `regime_v2_trend_gate.enabled` globally.
- Enabling PA paper runtime.
- Enabling long-horizon PA candidate runtime.
- Promoting transition micro-states into routing/execution.
- Treating the 3-bar PA horizon as validated.
- Broad/global PriceAction suppression.
- Committing runtime logs from `logs/`.

## Current validated PA scope

Valid descriptor scope:

```text
asset = BNBUSDT
timeframe = 1h
model = PriceAction
direction = 1
valid_horizons_bars = 6, 12, 24
rule = rolling_avg_below_002_3
```

Invalid scope:

```text
3-bar horizon
any broad/global PriceAction suppression
any other asset/timeframe promotion
```

## Cleanup list

Do not delete automatically. When cleanup is requested, share this list:

```text
research/p7v.json
research/p7v.md
```

## Commit grouping

Recommended groups:

1. RegimeV2 core, policy, evaluation, scripts, tests, and research evidence.
2. Selection-layer shadow/PA safety integration.
3. Runtime/config wiring.
4. Alert-app files as a separate workstream if present.

## Release checklist

Before any merge/release:

1. Run the 8D safety validator.
2. Confirm `safe = true` and blockers are empty.
3. Confirm live trend gate count is zero.
4. Confirm PA guardrail enabled count is zero.
5. Confirm transition runtime count is zero.
6. Confirm transition posture is `frozen_diagnostic`.
7. Run a focused safe regression pack.
8. Do not run Docker build paths unless the pipeline is fixed and explicitly requested.

Suggested safe regression pack:

```bash
.venv/bin/python -m pytest \
  tests/test_regime_v2_runtime_safety_validator.py \
  tests/test_regime_v2_orchestration_shadow_report.py \
  tests/test_regime_v2_playbook_orchestration_gate.py \
  tests/test_regime_v2_transition_stop_gate.py \
  tests/test_selection_layer.py \
  tests/signals/test_regime_wiring.py
```

## Current conclusion

RegimeV2 is diagnostic/shadow complete for the current milestone.

It is not live-production promotion-ready.

The next meaningful work after this runbook is either:

1. Commit/readiness review and cleanup, or
2. A separate future feature-enrichment branch for transition diagnostics, or
3. Runtime pipeline hardening outside RegimeV2.
