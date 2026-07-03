# RegimeV2 Phase 6T PA Paper Context Filter Discovery

## Summary

- Active changed rows: 40
- Failure window rows: 10
- Candidate filters: 2
- Recommendation: candidate_filter_found
- Best filter: {'rule': 'recent_window_position >= 0.75', 'kept_count': 30, 'rejected_count': 10, 'kept_avg_lift': 0.04459116659724163, 'rejected_avg_lift': -0.019160547889928922, 'all_avg_lift': 0.028653237975448997, 'kept_avg_lift_minus_all_avg_lift': 0.015937928621792635, 'kept_bad_rate': 0.0, 'rejected_bad_rate': 0.8, 'kept_outcome_labels': {'avoided_loss': 30}, 'rejected_outcome_labels': {'avoided_loss': 2, 'missed_win': 8}, 'failure_window_coverage_rate': 1.0, 'rejected_failure_count': 10}

## Baseline vs Failure Window

- All rows avg lift: 0.028653237975448997
- All rows bad rate: 0.2
- Failure avg lift: -0.019160547889928922
- Failure bad rate: 0.8

## Candidate Filters

| Rule | Kept | Rejected | Rejected bad rate | Kept bad rate | Lift improvement | Failure coverage |
|---|---:|---:|---:|---:|---:|---:|
| recent_window_position >= 0.75 | 30 | 10 | 0.8 | 0.0 | 0.015937928621792635 | 1.0 |
| timestamp >= failure_window_start | 30 | 10 | 0.8 | 0.0 | 0.015937928621792635 | 1.0 |
