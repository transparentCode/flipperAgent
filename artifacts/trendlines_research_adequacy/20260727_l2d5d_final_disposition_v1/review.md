# L2-D5D Final Mature-Trendlines Research Disposition

This is the final mature-trendlines research disposition.
No provider call, model execution, replay or parameter trial occurred.
No favourable subset was selected.
All five canonical cohorts and all ten sensitivity capsules were included.
Random-pair and density-matched nulls were evaluated separately.
Decisive comparator: causal-density-matched-null-v1; it is the stronger utility comparator.
UTILITY_NOT_BETTER_THAN_NAIVE_NULL is legacy outcome vocabulary; the decisive failed comparator is the causal density-matched null.
Sensitivity comparisons were treated as different event populations.
The selected outcome followed the frozen decision hierarchy.
No production promotion was authorised.

Selected outcome: `utility_not_better_than_naive_null`.
Recommended action: `REDESIGN_GEOMETRY_SELECTION`.
Decisive rule: `RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL`.

## Evidence axes

- evidence_completeness: `COMPLETE`
- structural_non_triviality: `OBSERVED_NONTRIVIAL_STRUCTURE`
- null_relative_interaction_utility: `RANDOM_STRONG_DENSITY_FAILED`
- geometry_sensitivity: `PARAMETER_FRAGILE`

## Cohort scope

- reference-btcusdt-1h-20250101-v1: structure `OBSERVED_NONTRIVIAL_STRUCTURE`, random robust-positive cells `8`, density robust-positive cells `0`, parameter `fragile`.
- temporal-btcusdt-1h-20250401-v1: structure `OBSERVED_NONTRIVIAL_STRUCTURE`, random robust-positive cells `4`, density robust-positive cells `0`, parameter `fragile`.
- cross-asset-ethusdt-1h-20250401-v1: structure `OBSERVED_NONTRIVIAL_STRUCTURE`, random robust-positive cells `7`, density robust-positive cells `0`, parameter `fragile`.
- cross-asset-solusdt-1h-20250401-v1: structure `OBSERVED_NONTRIVIAL_STRUCTURE`, random robust-positive cells `8`, density robust-positive cells `0`, parameter `fragile`.
- cross-timeframe-btcusdt-4h-20250401-v1: structure `OBSERVED_NONTRIVIAL_STRUCTURE`, random robust-positive cells `8`, density robust-positive cells `0`, parameter `fragile`.

## Limitations

- Five bounded cohorts do not establish broad market universality.
- D3 and null comparisons preserve mature-model event timing.
- Sensitivity variants have different event populations and are descriptive.
- No P&L, promotion, production activation, or provider execution was evaluated.

Mature trendlines research formally closed: **yes**.
Any redesign, cleanup, merge or production work is a new programme.

## Validation closeout

{
  "canonical_mature_trendlines": "796 passed",
  "compileall": "passed",
  "consumer_bridge": "79 passed",
  "d4b_d3_regression": "144 passed",
  "d5c_d5a_regression": "130 passed",
  "d5d_focused": "32 passed",
  "git_diff_check": "passed",
  "model_executions": 0,
  "offline_workflows": "20 passed",
  "parameter_trials": 0,
  "provider_calls": 0,
  "provider_retries": 0,
  "replay_executions": 0,
  "ruff": "passed",
  "status": "PASS",
  "viewer_node": "20 passed",
  "viewer_python": "30 passed"
}
