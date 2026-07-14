# Trendline-Family Candidate Density Study v1

> Exploratory post-diagnostic evidence only. No threshold/lookback selection, runtime use, promotion, or holdout access.

## Source And Bias Identity

```json
{
  "asset": "BTCUSDT",
  "confirmed_rows": 732,
  "dataset_hash": "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53",
  "diagnosis_id": "trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf",
  "diagnosis_source_binding_id": "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a",
  "fresh_unseen_window_required_for_follow_up": true,
  "holdout_accessed": false,
  "phase_i_run_id": "trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7",
  "planned_holdout_start_position": 636,
  "recommendation_id": "trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc",
  "report_id": "trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41",
  "resolved_config_hash": "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f",
  "source_binding": {
    "diagnosis_id": "trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf",
    "diagnosis_inventory": {
      "files": [
        {
          "relative_path": "diagnosis_manifest.json",
          "sha256": "8530208d3a306e4ff802231e60eab53e4ca938cd7990564a43fa54b03045b389",
          "size_bytes": 1207
        },
        {
          "relative_path": "rejection_diagnosis.json",
          "sha256": "8a17b8b514d04c7ce12410906d9ef3169723a7549fc872878429c505fdf96c3a",
          "size_bytes": 4334810
        },
        {
          "relative_path": "rejection_diagnosis.md",
          "sha256": "a548e4815e9c0ca8d254199fce71c506c7f8a0bedd6ec176085bdfd94ff04fa3",
          "size_bytes": 115531
        },
        {
          "relative_path": "source_binding.json",
          "sha256": "96bcdd5ad07429e5021675326b344c1142318423bfcbe40929f72c047d600d7d",
          "size_bytes": 8264
        }
      ],
      "inventory_sha256": "a2b18b8e880518ad3902a64be885429afe598d95e3be3db0af03dac6a0d5f6fe",
      "root_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v2",
      "source_name": "approved_diagnosis_bundle"
    },
    "diagnosis_source_binding_id": "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a",
    "study_schema_version": "trendline_family_candidate_density_study_v1",
    "study_source_binding_id": "trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6"
  },
  "source_binding_id": "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a",
  "study_schema_version": "trendline_family_candidate_density_study_v1",
  "study_source_binding_id": "trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6",
  "study_status": "exploratory_post_diagnostic_not_promotional",
  "timeframe": "4h",
  "validation_windows": [
    {
      "bar_count": 96,
      "end_position": 347,
      "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
      "fold_index": 0,
      "start_position": 252
    },
    {
      "bar_count": 96,
      "end_position": 455,
      "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
      "fold_index": 1,
      "start_position": 360
    },
    {
      "bar_count": 96,
      "end_position": 563,
      "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
      "fold_index": 2,
      "start_position": 468
    }
  ]
}
```

## Canonical Exposure

```json
{
  "120": {
    "exposed_candidate_count": 576,
    "quality_method": "anchor_span_coverage_v1",
    "resistance_candidate_count": 288,
    "source_threshold": "0.40",
    "source_threshold_bps": 4000,
    "support_candidate_count": 288,
    "validation_bar_count": 288
  },
  "180": {
    "exposed_candidate_count": 576,
    "quality_method": "anchor_span_coverage_v1",
    "resistance_candidate_count": 288,
    "source_threshold": "0.40",
    "source_threshold_bps": 4000,
    "support_candidate_count": 288,
    "validation_bar_count": 288
  },
  "240": {
    "exposed_candidate_count": 576,
    "quality_method": "anchor_span_coverage_v1",
    "resistance_candidate_count": 288,
    "source_threshold": "0.40",
    "source_threshold_bps": 4000,
    "support_candidate_count": 288,
    "validation_bar_count": 288
  }
}
```

## Existing Threshold Reconciliation

```json
[
  {
    "accepted_candidate_count": 47,
    "lookback_bars": 120,
    "per_fold_accepted_candidate_count": [
      {
        "count": 18,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 12,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 17,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 47,
    "reconciled": true,
    "resistance_candidate_count": 12,
    "support_candidate_count": 35,
    "threshold": "0.30",
    "threshold_bps": 3000
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 120,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.40",
    "threshold_bps": 4000
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 180,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.30",
    "threshold_bps": 3000
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 180,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.35",
    "threshold_bps": 3500
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 180,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.40",
    "threshold_bps": 4000
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 240,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.30",
    "threshold_bps": 3000
  },
  {
    "accepted_candidate_count": 0,
    "lookback_bars": 240,
    "per_fold_accepted_candidate_count": [
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 0,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "producing_bar_count": 0,
    "reconciled": true,
    "resistance_candidate_count": 0,
    "support_candidate_count": 0,
    "threshold": "0.40",
    "threshold_bps": 4000
  }
]
```

## Minimum Sample Support Frontier

```json
{
  "120": {
    "accepted_candidate_count_per_fold_at_highest_support": [
      {
        "count": 34,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 41,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 40,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "current_threshold_deficits": {
      "3000": {
        "aggregate_deficit_to_100": 53,
        "per_fold_deficit_to_100": [
          82,
          88,
          83
        ],
        "per_fold_non_empty_deficit": [
          0,
          0,
          0
        ],
        "threshold": "0.30"
      },
      "3500": {
        "aggregate_deficit_to_100": 88,
        "per_fold_deficit_to_100": [
          100,
          88,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          0,
          1
        ],
        "threshold": "0.35"
      },
      "4000": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.40"
      }
    },
    "descriptive_only": true,
    "every_fold_non_empty_at_highest_support": true,
    "highest_grid_threshold_with_aggregate_support_at_least_100": "0.12",
    "highest_grid_threshold_with_aggregate_support_at_least_100_bps": 1200,
    "minimum_sample_count": 100,
    "thresholds_where_aggregate_support_crosses_below_100_bps": [
      1300
    ],
    "thresholds_with_aggregate_support_at_least_100_bps": [
      0,
      100,
      200,
      300,
      400,
      500,
      600,
      700,
      800,
      900,
      1000,
      1100,
      1200
    ]
  },
  "180": {
    "accepted_candidate_count_per_fold_at_highest_support": [
      {
        "count": 34,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 41,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 40,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "current_threshold_deficits": {
      "3000": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.30"
      },
      "3500": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.35"
      },
      "4000": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.40"
      }
    },
    "descriptive_only": true,
    "every_fold_non_empty_at_highest_support": true,
    "highest_grid_threshold_with_aggregate_support_at_least_100": "0.08",
    "highest_grid_threshold_with_aggregate_support_at_least_100_bps": 800,
    "minimum_sample_count": 100,
    "thresholds_where_aggregate_support_crosses_below_100_bps": [
      900
    ],
    "thresholds_with_aggregate_support_at_least_100_bps": [
      0,
      100,
      200,
      300,
      400,
      500,
      600,
      700,
      800
    ]
  },
  "240": {
    "accepted_candidate_count_per_fold_at_highest_support": [
      {
        "count": 34,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace"
      },
      {
        "count": 41,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de"
      },
      {
        "count": 40,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e"
      }
    ],
    "current_threshold_deficits": {
      "3000": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.30"
      },
      "3500": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.35"
      },
      "4000": {
        "aggregate_deficit_to_100": 100,
        "per_fold_deficit_to_100": [
          100,
          100,
          100
        ],
        "per_fold_non_empty_deficit": [
          1,
          1,
          1
        ],
        "threshold": "0.40"
      }
    },
    "descriptive_only": true,
    "every_fold_non_empty_at_highest_support": true,
    "highest_grid_threshold_with_aggregate_support_at_least_100": "0.06",
    "highest_grid_threshold_with_aggregate_support_at_least_100_bps": 600,
    "minimum_sample_count": 100,
    "thresholds_where_aggregate_support_crosses_below_100_bps": [
      700
    ],
    "thresholds_with_aggregate_support_at_least_100_bps": [
      0,
      100,
      200,
      300,
      400,
      500,
      600
    ]
  }
}
```

## Observations

```json
[
  "All values derive only from persisted validation diagnostic_records in the approved diagnosis bundle.",
  "Each 0.40 configuration supplies 288 validation bars and 576 threshold-zero exposed candidates with balanced roles.",
  "Existing 0.30, baseline 0.35, and 0.40 diagnosis records reconcile exactly against canonical exposure.",
  "Support frontiers are descriptive post-diagnostic summaries, not parameter selection or runtime evidence."
]
```

## Research Hypotheses

```json
[
  "Does anchor_span_coverage_v1 remain above observed density support on a separately approved fresh unseen window?",
  "Do shorter lookbacks alter exposed quality through anchor-span coverage on fresh data?",
  "Is observed candidate support concentrated by fold on a fresh validation window?",
  "Does a separately approved quality-definition architecture study merit investigation?"
]
```
