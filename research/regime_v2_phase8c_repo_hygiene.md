# RegimeV2 Phase 8C Repo Hygiene / Commit Readiness

## Scope

Phase 8C is an inventory and readiness pass. No cleanup files were deleted.

## GitNexus

- Status: up-to-date
- Indexed commit: 7bce191
- Current commit: 7bce191

## Current inventory

| Area | Count / status |
|---|---:|
| `src/libs/models/regime_v2` files | 126 |
| `src/libs/selection/regime_v2_*.py` files | 27 |
| `tests/test_regime_v2*.py` files | 59 |
| Known cleanup files | 2 |

## Safe regression evidence

Command scope:

```bash
.venv/bin/python -m pytest \
  tests/test_regime_v2_orchestration_shadow_report.py \
  tests/test_regime_v2_playbook_orchestration_gate.py \
  tests/test_regime_v2_shadow_report.py \
  tests/test_regime_v2_transition_stop_gate.py \
  tests/test_selection_layer.py \
  tests/signals/test_regime_wiring.py
```

Result:

```text
57 passed in 4.15s
```

Docker/e2e tests were not run because the project pipeline is known to be unstable and the instruction is not to run Docker build paths right now.

## Modified tracked files

These are tracked files already modified in the working tree:

```text
AGENTS.md
CLAUDE.md
configs/models.yaml
configs/selection.yaml
docker-compose.yml
pyproject.toml
src/apps/signal_app/pipeline/regime.py
src/libs/common/constants.py
src/libs/selection/selection_layer.py
tests/e2e/test_docker_integration.py
tests/signals/test_regime_wiring.py
tests/test_selection_layer.py
```

Notes:

- `src/libs/selection/selection_layer.py`, `tests/test_selection_layer.py`, and `tests/signals/test_regime_wiring.py` are directly relevant to RegimeV2 shadow/selection wiring.
- `tests/e2e/test_docker_integration.py` is not validated in this pass.
- `docker-compose.yml` is intentionally not exercised in this pass.
- Alert-app related files appear in the working tree and should be treated as a separate commit/workstream unless intentionally bundled.

## Cleanup files

Per your instruction, I did not delete these. When you ask for cleanup files, share this list:

```text
research/p7v.json
research/p7v.md
```

## Suggested commit grouping

### 1. RegimeV2 core and policy/research

```text
src/libs/models/regime_v2/
tests/test_regime_v2*.py
research/regime_v2_*.json
research/regime_v2_*.md
```

This is the main RegimeV2 implementation and evidence bundle.

### 2. Selection shadow and PA safety wiring

```text
src/libs/selection/regime_v2_*.py
src/libs/selection/overlays/
src/libs/selection/selection_layer.py
tests/test_selection_layer.py
tests/signals/test_regime_wiring.py
```

This is the selection/shadow/paper integration layer.

### 3. Config and runtime wiring

```text
configs/models.yaml
configs/selection.yaml
src/apps/signal_app/pipeline/regime.py
src/libs/common/constants.py
```

This should be reviewed carefully because it touches application/runtime config.

### 4. Alert-app / unrelated workstream

```text
configs/alerts.yaml
docs/architecture/alert_app/
plans/alert_app_hld_lld_2026-06-21.md
src/apps/alert_app/
tests/alerts/
```

This should probably be separate from the RegimeV2 commit unless there is an intentional combined milestone.

## Current readiness conclusion

RegimeV2 is commit-ready as a diagnostic/shadow module after final human review of the modified tracked runtime files.

It is not live-promotion-ready. Runtime remains disabled/frozen according to 7Z/8A/8B.

## Recommended next phase

Phase 8D: runtime safety validator.

Goal:

- verify transition runtime is zero
- verify transition posture is frozen diagnostic
- verify PA paper runtime remains disabled
- verify trend gate is disabled unless explicitly enabled
- verify invalid horizons/scopes are not marked as validated
