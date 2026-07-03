# RegimeV2 Phase 6P PA Paper Disable Recommendation

## Summary

- Recommendation: continue_monitoring_insufficient_sample
- Disable recommended: False
- Pause recommended: False
- Actionable failures: 0
- Insufficient failures: 1
- Low-sample segments: 1

## Segments

| Name | Role | Changed | Enough sample | Avg lift | Avoided | Missed | Action | Reasons |
|---|---|---:|---|---:|---:|---:|---|---|
| all_time | all_time | 40 | True | 0.019337334305283522 | 31 | 9 | continue_monitoring |  |
| last_24h | action_window | 3 | False | -0.010979592596494184 | 0 | 3 | continue_monitoring_insufficient_sample | insufficient_changed_sample, negative_avg_lift, missed_wins_exceed_avoided_losses |
| last_168h | action_window | 37 | True | 0.02002004587635331 | 29 | 8 | continue_monitoring |  |
| last_720h | observation_window | 40 | True | 0.019337334305283522 | 31 | 9 | continue_monitoring |  |
