---
goal: Return SR-V1.0 YAML-backed configuration patch for quant review
stage: coder-to-review
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Coder Agent
status: Ready
tags: [handoff, quant, sr, config, yaml]
source_agent: Coder Agent
target_agent: Quant Review
---

# Scope Executed

Implemented the requested SR-V1.0 configuration-source hardening on
`feature/sr-v1.0-foundation`:

- Moved the eight baseline parameter values to `configs/sr.yaml`.
- Removed numeric dataclass defaults from all four typed parameter groups.
- Made partial override validation merge against the validated global YAML
  defaults instead of constructing dataclass defaults.
- Preserved the three-layer resolver precedence:
  `defaults → timeframe → exact asset/timeframe`.
- Enabled `RuntimeConfig.max_active_zones` in timeframe and exact
  asset/timeframe YAML layers; kept separate call-time `runtime_override`
  layer absent.
- Kept asset-wide defaults rejected.
- Parameterized signed-zero hash coverage across all four zero-capable ATR
  fields.
- Rejected duplicate YAML keys at every mapping depth.
- Added explicit regression coverage proving `resolve()` has no call-time
  `runtime_override` parameter.

# Changes Made

Files added or changed for this patch:

- `configs/sr.yaml`
- `src/libs/models/sr/config/models.py`
- `src/libs/models/sr/config/resolver.py`
- `src/libs/models/sr/adapters/__init__.py`
- `src/libs/models/sr/adapters/yaml_config.py`
- `tests/models/sr/config/test_resolver.py`
- `tests/models/sr/adapters/test_import_boundaries.py`
- `tests/models/sr/adapters/test_yaml_config.py`

`load_sr_config()` is intentionally parse-only and uses a private subclass of
`yaml.SafeLoader` through `yaml.load` to reject duplicate keys recursively;
the existing `SRConfigResolver` remains responsible for schema validation and
precedence. The adapter is not imported from the SR package root, and YAML is
not imported by `domain/` or `config/`.

# Blast Radius Considered

The mandatory constructor change affects only the isolated
`libs.models.sr.config` typed groups and their resolver path. Codebase-memory
call tracing confirmed the validation helpers are internal to raw SR config
validation; no detector, lifecycle engine, trading, risk, or legacy
`libs.sr` flow was changed. The source index was refreshed after the patch.

# Validation Performed

- `.venv/bin/python -m pytest tests/models/sr -q` — 100 passed
- `.venv/bin/python -m pytest tests/models/sr/config tests/models/sr/adapters -q` — 55 passed
- `.venv/bin/python -m pytest tests/models/sr/adapters/test_import_boundaries.py -q` — 1 passed
- `.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q` — 2 passed
- `ruff check src/libs/models/sr tests/models/sr` — passed
- `.venv/bin/python -m compileall -q src/libs/models/sr` — passed
- package import — passed
- forbidden `app.sr` / `libs.sr` search — clean
- codebase-memory index refresh and scope check — completed

The project virtual environment does not contain `ruff`; the available
repository Ruff executable was used for the clean lint result.

# Not Changed

No detection, association, lifecycle execution, persistence, optimizer,
hyperparameter, trendline/regime, legacy migration, or SR-V1.1 work was added.
No merge to `master` was performed.

# Risks or Follow-Up Items

- Review should verify the adapter/resolver composition for missing, empty,
  malformed, non-mapping, incomplete, and unsupported-version YAML.
- Review should confirm runtime provenance is `timeframe:<tf>` and
  `asset_timeframe:<asset>:<tf>` at corresponding layers.
- Review should probe duplicate root, section, field, and nested override
  keys; all must fail before schema resolution.
- `timeframes` and `assets` remain empty in the committed baseline YAML as
  requested; no tuned values were introduced.

This package is complete enough for Quant Review to act without additional
implementation assumptions.
