# RegimeV2 Phase 7K Follow-Through Context Gate Matrix

## Scope

- Asset/timeframe: BNBUSDT|1h
- Input rows: 720
- Thresholds tested: 0.25, 0.30
- Filter position: pre-confirmation context gate, before Phase 7F follow-through scoring
- Runtime posture: offline-only / diagnostic-only

## Default gate config

- min_context_score: 0.70
- max_risk_score: 0.72
- max_conflict_count: 1
- allow_watch_risk: true
- require_breakout_playbook: false
- require_confirmed_context: false

## Summary

- Recommendation: hold_off_context_gate_unstable
- Ready variants: 0/2
- Best ready variant: none
- Best variant threshold: 0.25
- Candidates before/after: 330/293
- Blocked candidate rows: 37
- Active total after 7F: 10
- Splits passed: 3/4
- Avg split directional return: 0.0035751228597196783
- Worst split directional return: -0.00765301617323444

## Variant matrix

| Threshold | Candidates before | Candidates after | Active total | Passed | Avg split dir | Worst split dir | Ready |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.25 | 330 | 293 | 10 | 3/4 | 0.0035751228597196783 | -0.00765301617323444 | False |
| 0.30 | 330 | 293 | 10 | 3/4 | 0.0035751228597196783 | -0.00765301617323444 | False |

## Split result

| Split | Active | Passing cells | Avg directional | Worst directional | Passed | Failure reasons |
|---:|---:|---:|---:|---:|---|---|
| 1 | 2 | 12/12 | 0.004423758027398304 | 0.0003227611267069431 | True | none |
| 2 | 2 | 0/12 | -0.005686912938308922 | -0.00765301617323444 | False | low_passing_rate, avg_return_too_low, worst_cell_too_negative |
| 3 | 2 | 12/12 | 0.01161973074472919 | 0.009907736689606804 | True | none |
| 4 | 4 | 10/12 | 0.003943915605060142 | 0.0012712894336871581 | True | none |

## Interpretation

Phase 7K is materially better than 7J for the breakout follow-through path. Moving the filter before confirmation keeps enough support and improves chronological stability from 0/4 splits in 7J to 3/4 splits in the default 7K retest.

It is still not promotion-ready. Split 2 remains structurally bad: both active rows fail directionally, passing 0/12 horizon/fee cells with a worst directional return of -0.00765301617323444. This suggests the next phase should focus on split-2-specific context/failure signatures or a direction-local transition rule, rather than making the context gate broadly stricter.

A stricter 0.72 context threshold improved average directional return but reduced support too much and passed only 1/4 splits. A strict breakout-only/confirmed-context gate blocked all candidates, so it is not useful with the current context model.
