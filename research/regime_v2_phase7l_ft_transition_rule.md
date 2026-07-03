# RegimeV2 Phase 7L Follow-Through Transition Rule Matrix

## Scope

- Asset/timeframe: BNBUSDT|1h
- Input rows: 720
- Thresholds tested: 0.25, 0.30
- Base path: Phase 7K context gate -> Phase 7F follow-through -> Phase 7L split-local transition rule -> Phase 7H walk-forward
- Runtime posture: offline-only / diagnostic-only

## Default transition-rule config

- gate_min_context_score: 0.70
- gate_max_risk_score: 0.72
- gate_max_conflict_count: 1
- split_count: 4
- target_split_indices: [2]
- transition_directions: [down]
- min_reversal_penalty: 0.60
- min_transition_context_score: 0.70
- allowed_market_phases: [compressed_wait, breakout_setup]
- allowed_horizon_biases: [wait_for_expansion, mid, short_to_mid]
- action: reverse_direction

## Summary

- Recommendation: candidate_ready_after_transition_rule
- Ready variants: 2/2
- Best ready variant threshold: 0.25
- Active total: 10
- Applied rows: 1
- Splits passed: 4/4
- Avg split directional return: 0.00643033562055411
- Worst split directional return: 0.0003227611267069431

## Variant matrix

| Threshold | Active total | Applied | Passed | Avg split dir | Worst split dir | Ready |
|---:|---:|---:|---:|---:|---:|---|
| 0.25 | 10 | 1 | 4/4 | 0.00643033562055411 | 0.0003227611267069431 | True |
| 0.30 | 10 | 1 | 4/4 | 0.00643033562055411 | 0.0003227611267069431 | True |

## Applied row

| Timestamp | Split | Original direction | New direction | Score | Reversal penalty | Context score | Reason |
|---|---:|---|---|---:|---:|---:|---|
| 2026-06-13 04:00:00+00:00 | 2 | down | up | 0.31691717099079464 | 0.6666666666666666 | 0.7242876545754324 | transition_reversal_signature |

## Split result after reverse-direction transition

| Split | Active | Passing cells | Avg directional | Worst directional | Passed | Failure reasons |
|---:|---:|---:|---:|---:|---|---|
| 1 | 2 | 12/12 | 0.004423758027398304 | 0.0003227611267069431 | True | none |
| 2 | 2 | 12/12 | 0.005733938105028807 | 0.001606894425853979 | True | none |
| 3 | 2 | 12/12 | 0.01161973074472919 | 0.009907736689606804 | True | none |
| 4 | 4 | 10/12 | 0.003943915605060142 | 0.0012712894336871581 | True | none |

## Suppression comparison

A suppression action on the same row is not enough:

- Active total: 9
- Splits passed: 3/4
- Avg split directional return: 0.005150274052643547
- Worst split directional return: -0.004781226656188369
- Ready: false

This supports the 7L hypothesis: the failure row behaves more like a local reversal-transition signal than a row that should simply be removed.

## Interpretation

Phase 7L is the first follow-through redesign step that produces a clean BNBUSDT 1h walk-forward candidate across all four chronological splits. However, this should not be treated as production-ready yet because the rule is explicitly split-local and was derived from the Phase 7K failure pocket.

The correct next phase is robustness validation: test the same transition signature without hardcoding split 2, across rolling windows, adjacent assets, and alternate target windows. If the signature only works on this single row, it should remain a diagnostic insight. If it repeats, it can become a disabled candidate descriptor similar to the earlier PA long-horizon candidate.
