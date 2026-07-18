# SR Configuration

## Canonical model configuration

`configs/sr.yaml` is root SR model configuration. It is strict YAML with a
non-empty mapping root, duplicate-key rejection, schema validation, typed
sections, immutable resolver input, per-field provenance, and deterministic
resolved hashes.

V1 model surface contains exactly eight parameters:

| Group | Parameters |
| --- | --- |
| `detection` | `pivot_span_bars`, `zone_half_width_atr` |
| `association` | `merge_distance_atr` |
| `lifecycle` | `touch_tolerance_atr`, `break_buffer_atr`, `break_confirm_closes`, `max_age_bars` |
| `runtime` | `max_active_zones` |

Typed section fields are mandatory. No hidden Python numeric defaults or
call-time configuration layers. Missing YAML values fail closed.

## Resolution order

`SRConfigResolver.resolve(asset=..., timeframe=...)` applies four YAML layers:

```text
defaults
  → timeframes.<timeframe>
  → assets.<asset>.defaults
  → assets.<asset>.timeframes.<timeframe>
```

Later layers override earlier fields and update `field_provenance`. Runtime
parameters use same four layers. Resolver has no separate runtime-override
argument.

Existing `configs/sr.yaml` has empty `timeframes` and `assets` mappings.
Asset-wide resolution support must not alter current resolved values,
provenance, or hashes.

Example shape:

```yaml
assets:
  BTCUSDT:
    defaults:
      association:
        merge_distance_atr: 0.40
    timeframes:
      1h:
        detection:
          pivot_span_bars: 7
```

## Configuration ownership policy

Values capable of changing candidates, zones, lifecycle behavior, metrics,
dispositions, or artifact identity belong in typed configuration. This includes
lookbacks, ATR method/period/warm-up policy, geometry/tolerance/merge values,
confirmation and capacity limits, fold/window definitions, horizons, decision
gates, venue/asset/timeframe, stage paths, and identity bindings.

Code retains only invariants: enum values, schema rules, canonical ordering,
canonical serialization/hashing, and domain-state validity.

Research trial YAML lives under `configs/sr_trials/`. It is strict and
identity-bound; it does not add fallback layer to `configs/sr.yaml`. Frozen
trial/source/evidence fields validate before use and never silently regenerate
during refactor.
