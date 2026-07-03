# RegimeV2 Phase 6X PA Paper Horizon Slice

## Summary

- Variants: 8
- Long horizons: [12, 24]
- Short horizons: [3]
- Long-horizon candidate: True
- Recommendation: long_horizon_paper_candidate
- Best variant: {'name': 'rolling_avg_below_002_3', 'long_passing_cell_count': 6, 'long_cell_count': 6, 'long_avg_improvement': 0.003234266325851628, 'long_lost_avoided_loss_count': 0, 'short_failed_cell_count': 3, 'mid_failed_cell_count': 0, 'long_horizon_candidate': True}

## Variants

| Variant | Long pass | Long lost | Long improvement | Short pass | Short lost | Mid pass | Candidate |
|---|---:|---:|---:|---:|---:|---:|---|
| rolling_avg_below_002_3 | 6/6 | 0 | 0.003234266325851628 | 0/3 | 3 | 3/3 | True |
| rolling_avg_below_005_3 | 6/6 | 0 | 0.003054695193784221 | 0/3 | 3 | 3/3 | True |
| rolling_avg_neg_3_and_missed_streak_2 | 6/6 | 0 | 0.002630719771688767 | 0/3 | 3 | 3/3 | True |
| rolling_avg_below_002_5 | 6/6 | 0 | 0.002630719771688767 | 0/3 | 3 | 3/3 | True |
| rolling_avg_neg_3_and_miss_gt_avoid_3 | 6/6 | 0 | 0.003234266325851628 | 0/3 | 3 | 0/3 | True |
| miss_gt_avoid_3 | 6/6 | 0 | 0.003234266325851628 | 0/3 | 3 | 0/3 | True |
| missed_streak_2 | 6/6 | 0 | 0.002630719771688767 | 0/3 | 3 | 0/3 | True |
| rolling_avg_neg_3 | 6/6 | 0 | 0.003234266325851628 | 0/3 | 5 | 0/3 | True |
