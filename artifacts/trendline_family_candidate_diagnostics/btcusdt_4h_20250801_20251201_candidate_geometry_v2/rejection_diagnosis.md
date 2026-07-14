# Trendline-Family Candidate Rejection Diagnosis v1

## Source And Execution Identity

```json
{
  "actual_provider_call_count": 2016,
  "dataset_hash": "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53",
  "diagnosis_schema_version": "trendline_family_candidate_rejection_diagnosis_v1",
  "input_manifest_sha256": "089d1c743100a0a5591cb615ae453c19992cd3534fe274b8eef91e2af582fc48",
  "normalized_input_sha256": "b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150",
  "phase_i_run_id": "trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7",
  "planned_holdout_exclusion": {
    "all_replayed_positions_before_holdout": true,
    "maximum_replayed_position": 563,
    "planned_holdout_start_position": 636
  },
  "recommendation_id": "trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc",
  "report_id": "trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41",
  "resolved_config_hash": "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f",
  "shadow_provider_call_count": 1969,
  "source_binding_id": "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a",
  "source_inventories": {
    "approved_report_inventory": {
      "files": [
        {
          "relative_path": "evidence_report.json",
          "sha256": "07e50ea26318db77ecd034085bd068792227a165d5872cb71f9d818a2e533242",
          "size_bytes": 510191
        },
        {
          "relative_path": "evidence_report.md",
          "sha256": "b68adbb22707097ea352b3fb8baa238c5b2a88542a7b24d9bc6744703c6a4cf0",
          "size_bytes": 767741
        },
        {
          "relative_path": "report_manifest.json",
          "sha256": "7c6bd0d76501296dde5353d389daa5a0695a986468f59bb205298c84aae5378d",
          "size_bytes": 4839
        },
        {
          "relative_path": "source_inventory.json",
          "sha256": "45197651e25e65561fdb16e2676117ac6409527e233dbb5c7055fcd27efcf6ab",
          "size_bytes": 7088
        }
      ],
      "inventory_sha256": "15c374bd5b85638d01ecbc6c0d96b69eb50a89e730041206b5089a24b4c5b62e",
      "root_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v2",
      "source_name": "approved_report_bundle"
    },
    "config_inventory": {
      "relative_path": "configs/trendline_family.yaml",
      "sha256": "7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8",
      "size_bytes": 2029
    },
    "diagnosis_schema_version": "trendline_family_candidate_rejection_diagnosis_v1",
    "source_binding_id": "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a",
    "trial_inventories": {
      "report_schema_version": "trendline_family_candidate_evidence_report_v1",
      "source_inventory_id": "trendline-family-candidate-source-inventory_2711380b554260b5ccff67ede6aa060faf124ed76b8369a97be54edb78dfd8d8",
      "sources": {
        "v1": {
          "files": [
            {
              "relative_path": "execution_scope.json",
              "sha256": "20df6747ee9098e5cf6a5b507521944d06262debbdd31e3a68ac304c0f58c901",
              "size_bytes": 219
            }
          ],
          "inventory_sha256": "48ad089646b395641b5c7d28d75705a01490b7564248aed5231aba6ce602e892",
          "source_name": "v1",
          "trial_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
        },
        "v2": {
          "files": [
            {
              "relative_path": "execution_scope.json",
              "sha256": "d872568f285a782d0404c5de69e88549a4e57ac24c0bea7f9d00452056eddcc0",
              "size_bytes": 494
            },
            {
              "relative_path": "input/input_manifest.json",
              "sha256": "089d1c743100a0a5591cb615ae453c19992cd3534fe274b8eef91e2af582fc48",
              "size_bytes": 1121
            },
            {
              "relative_path": "input/normalized_ohlcv.csv",
              "sha256": "b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150",
              "size_bytes": 83644
            },
            {
              "relative_path": "input/raw_binance_response.csv",
              "sha256": "aff33fd802c1ca4727ae3a9ded7add445f8e48605c8fc7b20f5c6ab4b959501b",
              "size_bytes": 50232
            },
            {
              "relative_path": "input/raw_fetch_manifest.json",
              "sha256": "cea9ab7913770e8fc57f33e7b2c33753dc6373c695a0cd4fa9450d0a9f54f2be",
              "size_bytes": 772
            },
            {
              "relative_path": "phase_i/baseline/trendline-family-trial-result_4c0ee504de21ee66528c0a5c1b401ef90f901aa45c3e9ccdd843e33f81896310.json",
              "sha256": "a1d97f9468cb25610a07821daf6cd0ef5aca33daf573423ca834a049abbf1755",
              "size_bytes": 19091
            },
            {
              "relative_path": "phase_i/candidate_geometry/recommendation.json",
              "sha256": "c3e2b9aa669c7c26b7440eb2ff0619145a24b118007fff73682002bd65829ec1",
              "size_bytes": 27698
            },
            {
              "relative_path": "phase_i/candidate_geometry/summary.json",
              "sha256": "d3e45fb03c544f94f79cca6fce1343f48abaec71163006e8f40dc415b0ef8aae",
              "size_bytes": 1121
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_14c67c7fe212e0f2170b5e94973e1eb9ad41398d25a30b4ef2d2c2c029a9a267.json",
              "sha256": "e6b289207e926994f9a49af0a1ff146c1f7782eea49e224b9d7743b19ac513b5",
              "size_bytes": 19272
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_2e0e98ad3fdb089018ef9aab9d47eb193b86bf9878dfb9d19d128ee4b0f0ee53.json",
              "sha256": "ceb9444a1a1829999212571344770d5a6a7bf794ce07769f693ccb2958be46b5",
              "size_bytes": 19281
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_3d9547ebb42967d74a21397916fe6c73c255c767c067a5c190908fac1b1a3bb3.json",
              "sha256": "b3ed315dcad148e794ab6e589cbb6ca26684834b787a3f95226b08b4c8fbd9bd",
              "size_bytes": 26588
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_4bbc2c018e559810db94e03ee8b2ca1e8fd722c355108ce222b462216229d9fb.json",
              "sha256": "4f6813f3fc5c02310f46dd19fdcad87992812de371d206268b0a3e74d0a61201",
              "size_bytes": 26589
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_577086b36d02337432e47e52170659bcdde2488927dd435b7acab38a2af0fe8b.json",
              "sha256": "685157962e788d814048d9b807b1bb43d38f35ff9ea5f34a66a87bd581880d33",
              "size_bytes": 19282
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_60513b273f6013acb014f0015f3afef6a955e4aeedc638fd3020c75e09868a39.json",
              "sha256": "38ededa439170d4cf88f72e75b98c2bbbb3e4ebb1a26e65501362bc7daa096a5",
              "size_bytes": 19272
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_731818ab22d07e1a42af1de3ae285dc40b0b4c5f1a438003105f144fb8df7eb6.json",
              "sha256": "5597888b1b9b51d8d0e4bca2dd1d2619116e898973f3f1b42f9fee3d1000ad1d",
              "size_bytes": 19273
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_77c3e82511de2c9b0e873867a8b87d353e0855cd811a4c9cb53c3ecd02ff761c.json",
              "sha256": "2af4eea8a9229c0904d0993e20e3ea74fc7e7106a394a5c700af6bc32c6e6d11",
              "size_bytes": 19273
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_80ed8d9c1c2961413ca215090162d72bba16452651342bb28a1fbfdf46ae72ca.json",
              "sha256": "a3ca5965ef8f84a39038db437dc331261a15001328708cd7046e8ac0077cd910",
              "size_bytes": 19281
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_82ef1afae06e0dd64229184bca3d99d0c2554ce5061c06dc4c043a75bd1e123e.json",
              "sha256": "407a980c222d535978187f2c7ce6db685faa10646bf098e57972807789653cc4",
              "size_bytes": 19282
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_99e249e82b5c6a815c3539e523a0112b9b51f6122b0347dda3d01c79cb9787dc.json",
              "sha256": "e63d84494be916971232ccaece4e37bd53ea9397b006c89e645a97e4ff90bb40",
              "size_bytes": 19271
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/counterfactuals/trendline-family-trial_e774b16a3083de88fac1e1b1cf44a065da79e5a31212f8556cfc96d1d973b0f1.json",
              "sha256": "48944a4118e27bde6fd2d8373b68a77ebaf1215739acc66701f56edf6c731f7a",
              "size_bytes": 19272
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b.json",
              "sha256": "e69d1c05ec91d071b357aa10cc60645c50b1d75df40e4bc3cbba216b3e38e301",
              "size_bytes": 58151
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7.json",
              "sha256": "6bb0b648168c16e932571eb21bb0e8d879d5a22a7d9bbfa10347f5854cbb661c",
              "size_bytes": 58148
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149.json",
              "sha256": "8a0357e0765b5c2a392aaa3ef013ec0edf40bead56fe1a770b65d1bd16413701",
              "size_bytes": 58150
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548.json",
              "sha256": "562e79ec2ebb30b8e9db476d1677410f4d85e055405492c1b0261b11d4c0ff37",
              "size_bytes": 58149
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb.json",
              "sha256": "66f7ee8d7dbea9c9a672a6941d94ce863201d9ad8a668c147973378d0d53272a",
              "size_bytes": 72937
            },
            {
              "relative_path": "phase_i/candidate_geometry/trials/trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8.json",
              "sha256": "9ab50bf952b076a616c030a3ac3b3e352e2417da52a9b8936ef37cfbb9226b99",
              "size_bytes": 65482
            },
            {
              "relative_path": "phase_i/completion_index.json",
              "sha256": "a8de545126b2b81cddfc707c53fd3bd331ee38861b646033a505df9a445f7813",
              "size_bytes": 4714
            },
            {
              "relative_path": "phase_i/final_report.md",
              "sha256": "184aba6dd1bd65db047bf1f2afd22aa41ca7bf686d3740edb207c0c8173a247d",
              "size_bytes": 494
            },
            {
              "relative_path": "phase_i/fold_plan.json",
              "sha256": "78d2faa58d44a83c5c35494e7c0b61e9132553dadbbd56e1f5ea50a52d242220",
              "size_bytes": 3347
            },
            {
              "relative_path": "phase_i/run_manifest.json",
              "sha256": "004eb1b2a17a253f23e0b1b90a8b8f4af74755b66b3380a13e716be3220e4b94",
              "size_bytes": 3616
            }
          ],
          "inventory_sha256": "d5d02fa4537f334d36d2b84d92b820eb0e1677d150f1d9cd345fa169d471ace5",
          "source_name": "v2",
          "trial_name": "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
        }
      }
    }
  }
}
```

## Dataset And Fold Boundaries

```json
{
  "asset": "BTCUSDT",
  "dataset_hash": "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53",
  "fold_plan_id": "trendline-family-fold-plan_9bf0223c4c1e89088b67b188205826d20c1741504843c356683bbc3d42e62dbc",
  "label_horizon_bars": 12,
  "purge_bars": 12,
  "row_count": 732,
  "timeframe": "4h",
  "validation_position_count": 288,
  "validation_windows": [
    {
      "bar_count": 96,
      "end": "2025-09-27T20:00:00Z",
      "end_position": 347,
      "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
      "fold_index": 0,
      "start": "2025-09-12T00:00:00Z",
      "start_position": 252
    },
    {
      "bar_count": 96,
      "end": "2025-10-15T20:00:00Z",
      "end_position": 455,
      "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
      "fold_index": 1,
      "start": "2025-09-30T00:00:00Z",
      "start_position": 360
    },
    {
      "bar_count": 96,
      "end": "2025-11-02T20:00:00Z",
      "end_position": 563,
      "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
      "fold_index": 2,
      "start": "2025-10-18T00:00:00Z",
      "start_position": 468
    }
  ]
}
```

## Configuration Matrix

```json
[
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 120,
      "min_bars": 40,
      "min_candidate_quality": 0.3,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
    "objective_gate_id": "trendline-family-objective-gate_12765c16eca0e966b42b905acad9670fd8ca19265a00d6385860dcfea4d59b27",
    "parameter_overrides": {
      "candidate.lookback_bars": 120,
      "candidate.min_candidate_quality": 0.3
    },
    "resolved_config_hash": "58d4cd36599f7f8d227f12142e2e6b30141800ad107459845779de5a7c3a5776",
    "result_id": "trendline-family-trial-result_64c2b7ef5ecd1ea872a1fd057856543163109317dda1a6b5b437d07cd66fcc64",
    "trial_id": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 120,
      "min_bars": 40,
      "min_candidate_quality": 0.4,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
    "objective_gate_id": "trendline-family-objective-gate_2a713089558057aa61a136bf343040403ea2c1dbc9437f601ddaafbc09ba3737",
    "parameter_overrides": {
      "candidate.lookback_bars": 120,
      "candidate.min_candidate_quality": 0.4
    },
    "resolved_config_hash": "ebe5a885afef66cd4d7036f986540e312a7ef474202d5bc32a5770d365900dd8",
    "result_id": "trendline-family-trial-result_9ed8493694e50915d7af78f6decf7716a2e9f8a8c8722a60804a831259d30d0f",
    "trial_id": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 180,
      "min_bars": 40,
      "min_candidate_quality": 0.3,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
    "objective_gate_id": "trendline-family-objective-gate_2a713089558057aa61a136bf343040403ea2c1dbc9437f601ddaafbc09ba3737",
    "parameter_overrides": {
      "candidate.lookback_bars": 180,
      "candidate.min_candidate_quality": 0.3
    },
    "resolved_config_hash": "5c0f1294c509aa1799bc6fe8ed200998a465cd3ca35ac277272f5edcb5f2bd94",
    "result_id": "trendline-family-trial-result_8177d00c54f5fdddc6b005dc90ec9c6c6f7d50282b2fea1251e5dee50526e209",
    "trial_id": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 180,
      "min_bars": 40,
      "min_candidate_quality": 0.4,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
    "objective_gate_id": "trendline-family-objective-gate_2a713089558057aa61a136bf343040403ea2c1dbc9437f601ddaafbc09ba3737",
    "parameter_overrides": {
      "candidate.lookback_bars": 180,
      "candidate.min_candidate_quality": 0.4
    },
    "resolved_config_hash": "aa197d11faec9be727ba32753185c6b655cd12f39b3b4b8a8a2f97fb006db14c",
    "result_id": "trendline-family-trial-result_d82ceb669a4ef021e705b8b960dd9b238c450a6fcdf4826a5dfbebaae7284652",
    "trial_id": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 240,
      "min_bars": 40,
      "min_candidate_quality": 0.3,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b",
    "objective_gate_id": "trendline-family-objective-gate_2a713089558057aa61a136bf343040403ea2c1dbc9437f601ddaafbc09ba3737",
    "parameter_overrides": {
      "candidate.lookback_bars": 240,
      "candidate.min_candidate_quality": 0.3
    },
    "resolved_config_hash": "9d9e78933b35b5c477011ab5da94cb9ce27cabb3f283402c6916c031c3854b5d",
    "result_id": "trendline-family-trial-result_9ee25bd1c5398b7698ac482af3a89f8ebbfb6bcc1833eb3eb14e0bb6da64d4c5",
    "trial_id": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 240,
      "min_bars": 40,
      "min_candidate_quality": 0.4,
      "min_pivots_per_side": 2
    },
    "label": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149",
    "objective_gate_id": "trendline-family-objective-gate_2a713089558057aa61a136bf343040403ea2c1dbc9437f601ddaafbc09ba3737",
    "parameter_overrides": {
      "candidate.lookback_bars": 240,
      "candidate.min_candidate_quality": 0.4
    },
    "resolved_config_hash": "d68574291cb3b2e329333e044da5102e5e92f6007e82cb4fe2aa7cf3348c9ac5",
    "result_id": "trendline-family-trial-result_2ebe87a1e4473ff7f4e816c3c29797a38519ae5614f36198e935fd7fa2d8b271",
    "trial_id": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149"
  },
  {
    "candidate_config": {
      "fractal_left_bars": 3,
      "fractal_right_bars": 3,
      "lookback_bars": 180,
      "min_bars": 40,
      "min_candidate_quality": 0.35,
      "min_pivots_per_side": 2
    },
    "label": "baseline",
    "objective_gate_id": "trendline-family-objective-gate_5a7221c9d2fd32fd6e8298bd1ac0a8d3adbd3208e962e4dc92602540ebbca482",
    "parameter_overrides": {},
    "resolved_config_hash": "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f",
    "result_id": "trendline-family-trial-result_4c0ee504de21ee66528c0a5c1b401ef90f901aa45c3e9ccdd843e33f81896310",
    "trial_id": "trendline-family-trial_00974389012896f1ea5f7ca6a815238a644ed4e133c5ff044411c2342079e0cf"
  }
]
```

## Status Funnel

```json
[
  {
    "configuration_label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 78,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 0.8125
          },
          "valid": {
            "count": 18,
            "first_observed_at": "2025-09-16T00:00:00Z",
            "last_observed_at": "2025-09-27T00:00:00Z",
            "ratio": 0.1875
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 84,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 0.875
          },
          "valid": {
            "count": 12,
            "first_observed_at": "2025-10-08T04:00:00Z",
            "last_observed_at": "2025-10-10T00:00:00Z",
            "ratio": 0.125
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 79,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-10-31T00:00:00Z",
            "ratio": 0.8229166666666666
          },
          "valid": {
            "count": 17,
            "first_observed_at": "2025-10-31T04:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 0.17708333333333334
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb"
  },
  {
    "configuration_label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8"
  },
  {
    "configuration_label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7"
  },
  {
    "configuration_label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548"
  },
  {
    "configuration_label": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b"
  },
  {
    "configuration_label": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149"
  },
  {
    "configuration_label": "baseline",
    "folds": [
      {
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-12T00:00:00Z",
            "last_observed_at": "2025-09-27T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-09-30T00:00:00Z",
            "last_observed_at": "2025-10-15T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      },
      {
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "reconciled": true,
        "statuses": {
          "insufficient_data": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_confirmed_pivots": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "no_valid_fitted_paths": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "provider_config_error": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          },
          "rejected_low_quality_candidates": {
            "count": 96,
            "first_observed_at": "2025-10-18T00:00:00Z",
            "last_observed_at": "2025-11-02T20:00:00Z",
            "ratio": 1.0
          },
          "valid": {
            "count": 0,
            "first_observed_at": null,
            "last_observed_at": null,
            "ratio": 0.0
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_00974389012896f1ea5f7ca6a815238a644ed4e133c5ff044411c2342079e0cf"
  }
]
```

## Low Quality Rejection Decomposition

```json
[
  {
    "configuration_label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 156,
          "max": 244800.0,
          "mean": 126276.92307692308,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 72000.0,
            "0.5": 129600.0,
            "0.75": 162000.0,
            "0.9": 187200.0
          }
        },
        "fitted_path_count": 156,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 78,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 156,
          "max": 13.0,
          "mean": 11.10897435897436,
          "median": 11.0,
          "min": 9.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 10.0,
            "0.25": 10.0,
            "0.5": 11.0,
            "0.75": 12.0,
            "0.9": 12.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 156
        },
        "quality_summary": {
          "count": 156,
          "max": 0.14285714285714285,
          "mean": 0.07369101486748546,
          "median": 0.07563025210084033,
          "min": 0.03361344537815126,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.03361344537815126,
            "0.25": 0.04201680672268908,
            "0.5": 0.07563025210084033,
            "0.75": 0.09453781512605042,
            "0.9": 0.1092436974789916
          }
        },
        "role_counts": {
          "RESISTANCE": 78,
          "SUPPORT": 78
        },
        "shadow_candidate_count": 156,
        "threshold_gap_summary": {
          "count": 156,
          "max": 0.26638655462184874,
          "mean": 0.22630898513251452,
          "median": 0.22436974789915964,
          "min": 0.15714285714285714,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.1907563025210084,
            "0.25": 0.20546218487394957,
            "0.5": 0.22436974789915964,
            "0.75": 0.2579831932773109,
            "0.9": 0.26638655462184874
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 168,
          "max": 388800.0,
          "mean": 148200.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 86400.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 158400.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 168,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 84,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 3
        },
        "path_length_summary": {
          "count": 168,
          "max": 15.0,
          "mean": 10.458333333333334,
          "median": 10.0,
          "min": 8.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 8.0,
            "0.25": 9.0,
            "0.5": 10.0,
            "0.75": 12.0,
            "0.9": 13.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 168
        },
        "quality_summary": {
          "count": 168,
          "max": 0.226890756302521,
          "mean": 0.08648459383753501,
          "median": 0.07563025210084033,
          "min": 0.03361344537815126,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.05042016806722689,
            "0.25": 0.05042016806722689,
            "0.5": 0.07563025210084033,
            "0.75": 0.09243697478991597,
            "0.9": 0.16806722689075632
          }
        },
        "role_counts": {
          "RESISTANCE": 84,
          "SUPPORT": 84
        },
        "shadow_candidate_count": 168,
        "threshold_gap_summary": {
          "count": 168,
          "max": 0.26638655462184874,
          "mean": 0.21351540616246498,
          "median": 0.22436974789915964,
          "min": 0.07310924369747898,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.13193277310924367,
            "0.25": 0.20756302521008402,
            "0.5": 0.22436974789915964,
            "0.75": 0.2495798319327731,
            "0.9": 0.2495798319327731
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 158,
          "max": 504000.0,
          "mean": 178632.91139240508,
          "median": 144000.0,
          "min": 72000.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 86400.0,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 331200.0
          }
        },
        "fitted_path_count": 158,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 79,
        "near_miss_counts": {
          "0.01": 15,
          "0.02": 15,
          "0.05": 15,
          "0.1": 15
        },
        "path_length_summary": {
          "count": 158,
          "max": 13.0,
          "mean": 10.89873417721519,
          "median": 11.0,
          "min": 9.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 9.0,
            "0.25": 10.0,
            "0.5": 11.0,
            "0.75": 12.0,
            "0.9": 12.300000000000011
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 158
        },
        "quality_summary": {
          "count": 158,
          "max": 0.29411764705882354,
          "mean": 0.10424422933730455,
          "median": 0.08403361344537816,
          "min": 0.04201680672268908,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.05042016806722689,
            "0.25": 0.058823529411764705,
            "0.5": 0.08403361344537816,
            "0.75": 0.1092436974789916,
            "0.9": 0.19327731092436976
          }
        },
        "role_counts": {
          "RESISTANCE": 79,
          "SUPPORT": 79
        },
        "shadow_candidate_count": 158,
        "threshold_gap_summary": {
          "count": 158,
          "max": 0.2579831932773109,
          "mean": 0.19575577066269545,
          "median": 0.21596638655462183,
          "min": 0.00588235294117645,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.10672268907563023,
            "0.25": 0.1907563025210084,
            "0.5": 0.21596638655462183,
            "0.75": 0.24117647058823527,
            "0.9": 0.2495798319327731
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb"
  },
  {
    "configuration_label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 18
        },
        "path_length_summary": {
          "count": 192,
          "max": 13.0,
          "mean": 10.895833333333334,
          "median": 11.0,
          "min": 9.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 10.0,
            "0.25": 10.0,
            "0.5": 11.0,
            "0.75": 12.0,
            "0.9": 12.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.3025210084033613,
          "mean": 0.09593837535014005,
          "median": 0.07563025210084033,
          "min": 0.03361344537815126,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.03361344537815126,
            "0.25": 0.05042016806722689,
            "0.5": 0.07563025210084033,
            "0.75": 0.1092436974789916,
            "0.9": 0.14285714285714285
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.36638655462184877,
          "mean": 0.30406162464986,
          "median": 0.3243697478991597,
          "min": 0.0974789915966387,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.2571428571428572,
            "0.25": 0.2907563025210084,
            "0.5": 0.3243697478991597,
            "0.75": 0.34957983193277314,
            "0.9": 0.36638655462184877
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 12,
          "0.1": 12
        },
        "path_length_summary": {
          "count": 192,
          "max": 15.0,
          "mean": 10.234375,
          "median": 10.0,
          "min": 7.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 8.0,
            "0.25": 9.0,
            "0.5": 10.0,
            "0.75": 12.0,
            "0.9": 12.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.3697478991596639,
          "mean": 0.10184698879551822,
          "median": 0.07563025210084033,
          "min": 0.03361344537815126,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.04201680672268908,
            "0.25": 0.05042016806722689,
            "0.5": 0.07563025210084033,
            "0.75": 0.10084033613445378,
            "0.9": 0.16806722689075632
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.36638655462184877,
          "mean": 0.29815301120448184,
          "median": 0.3243697478991597,
          "min": 0.030252100840336138,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.2319327731092437,
            "0.25": 0.29915966386554627,
            "0.5": 0.3243697478991597,
            "0.75": 0.34957983193277314,
            "0.9": 0.35798319327731093
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 17
        },
        "path_length_summary": {
          "count": 192,
          "max": 13.0,
          "mean": 10.640625,
          "median": 11.0,
          "min": 8.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 9.0,
            "0.25": 10.0,
            "0.5": 11.0,
            "0.75": 12.0,
            "0.9": 12.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.31092436974789917,
          "mean": 0.11812850140056023,
          "median": 0.08403361344537816,
          "min": 0.03361344537815126,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.04285714285714287,
            "0.25": 0.058823529411764705,
            "0.5": 0.08403361344537816,
            "0.75": 0.1092436974789916,
            "0.9": 0.29411764705882354
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.36638655462184877,
          "mean": 0.2818714985994398,
          "median": 0.31596638655462184,
          "min": 0.08907563025210086,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.10588235294117648,
            "0.25": 0.2907563025210084,
            "0.5": 0.31596638655462184,
            "0.75": 0.3411764705882353,
            "0.9": 0.3571428571428572
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8"
  },
  {
    "configuration_label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 18
        },
        "path_length_summary": {
          "count": 192,
          "max": 20.0,
          "mean": 17.473958333333332,
          "median": 17.0,
          "min": 14.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 17.0,
            "0.25": 17.0,
            "0.5": 17.0,
            "0.75": 18.0,
            "0.9": 19.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.2011173184357542,
          "mean": 0.06378026070763501,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.0223463687150838,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.07262569832402235,
            "0.9": 0.09497206703910614
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.2776536312849162,
          "mean": 0.23621973929236498,
          "median": 0.24972067039106144,
          "min": 0.09888268156424579,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.20502793296089383,
            "0.25": 0.22737430167597764,
            "0.5": 0.24972067039106144,
            "0.75": 0.26648044692737427,
            "0.9": 0.2776536312849162
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 12
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.53125,
          "median": 16.0,
          "min": 13.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 14.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 17.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.24581005586592178,
          "mean": 0.06770833333333333,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.027932960893854747,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.0670391061452514,
            "0.9": 0.11173184357541899
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.2776536312849162,
          "mean": 0.23229166666666667,
          "median": 0.24972067039106144,
          "min": 0.05418994413407821,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.188268156424581,
            "0.25": 0.2329608938547486,
            "0.5": 0.24972067039106144,
            "0.75": 0.26648044692737427,
            "0.9": 0.27206703910614527
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 17
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.807291666666666,
          "median": 16.0,
          "min": 12.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 15.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 18.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.20670391061452514,
          "mean": 0.07853235567970206,
          "median": 0.055865921787709494,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.028491620111731848,
            "0.25": 0.03910614525139665,
            "0.5": 0.055865921787709494,
            "0.75": 0.07262569832402235,
            "0.9": 0.19553072625698323
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.2776536312849162,
          "mean": 0.22146764432029795,
          "median": 0.2441340782122905,
          "min": 0.09329608938547485,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.10446927374301676,
            "0.25": 0.22737430167597764,
            "0.5": 0.2441340782122905,
            "0.75": 0.2608938547486033,
            "0.9": 0.2715083798882682
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7"
  },
  {
    "configuration_label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 20.0,
          "mean": 17.473958333333332,
          "median": 17.0,
          "min": 14.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 17.0,
            "0.25": 17.0,
            "0.5": 17.0,
            "0.75": 18.0,
            "0.9": 19.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.2011173184357542,
          "mean": 0.06378026070763501,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.0223463687150838,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.07262569832402235,
            "0.9": 0.09497206703910614
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.37765363128491625,
          "mean": 0.336219739292365,
          "median": 0.34972067039106147,
          "min": 0.19888268156424582,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.30502793296089387,
            "0.25": 0.3273743016759777,
            "0.5": 0.34972067039106147,
            "0.75": 0.3664804469273743,
            "0.9": 0.37765363128491625
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.53125,
          "median": 16.0,
          "min": 13.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 14.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 17.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.24581005586592178,
          "mean": 0.06770833333333333,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.027932960893854747,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.0670391061452514,
            "0.9": 0.11173184357541899
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.37765363128491625,
          "mean": 0.3322916666666667,
          "median": 0.34972067039106147,
          "min": 0.15418994413407824,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.28826815642458103,
            "0.25": 0.33296089385474864,
            "0.5": 0.34972067039106147,
            "0.75": 0.3664804469273743,
            "0.9": 0.37206703910614525
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.807291666666666,
          "median": 16.0,
          "min": 12.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 15.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 18.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.20670391061452514,
          "mean": 0.07853235567970206,
          "median": 0.055865921787709494,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.028491620111731848,
            "0.25": 0.03910614525139665,
            "0.5": 0.055865921787709494,
            "0.75": 0.07262569832402235,
            "0.9": 0.19553072625698323
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.37765363128491625,
          "mean": 0.321467644320298,
          "median": 0.34413407821229053,
          "min": 0.19329608938547488,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.2044692737430168,
            "0.25": 0.3273743016759777,
            "0.5": 0.34413407821229053,
            "0.75": 0.36089385474860336,
            "0.9": 0.3715083798882682
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548"
  },
  {
    "configuration_label": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 27.0,
          "mean": 21.979166666666668,
          "median": 22.0,
          "min": 19.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 20.0,
            "0.25": 21.0,
            "0.5": 22.0,
            "0.75": 23.0,
            "0.9": 24.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.1506276150627615,
          "mean": 0.04776847977684798,
          "median": 0.03765690376569038,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.016736401673640166,
            "0.25": 0.02510460251046025,
            "0.5": 0.03765690376569038,
            "0.75": 0.05439330543933055,
            "0.9": 0.07112970711297072
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.28326359832635983,
          "mean": 0.25223152022315204,
          "median": 0.2623430962343096,
          "min": 0.14937238493723848,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.22887029288702926,
            "0.25": 0.24560669456066944,
            "0.5": 0.2623430962343096,
            "0.75": 0.27489539748953973,
            "0.9": 0.28326359832635983
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 27.0,
          "mean": 21.583333333333332,
          "median": 21.0,
          "min": 19.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 20.0,
            "0.25": 21.0,
            "0.5": 21.0,
            "0.75": 22.0,
            "0.9": 24.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.18410041841004185,
          "mean": 0.050710425383542534,
          "median": 0.03765690376569038,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.02092050209205021,
            "0.25": 0.02510460251046025,
            "0.5": 0.03765690376569038,
            "0.75": 0.0502092050209205,
            "0.9": 0.08368200836820083
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.28326359832635983,
          "mean": 0.24928957461645743,
          "median": 0.2623430962343096,
          "min": 0.11589958158995814,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.21631799163179916,
            "0.25": 0.2497907949790795,
            "0.5": 0.2623430962343096,
            "0.75": 0.27489539748953973,
            "0.9": 0.2790794979079498
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 24.0,
          "mean": 21.026041666666668,
          "median": 21.0,
          "min": 18.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 19.0,
            "0.25": 20.0,
            "0.5": 21.0,
            "0.75": 23.0,
            "0.9": 23.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.15481171548117154,
          "mean": 0.058817119944211994,
          "median": 0.04184100418410042,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.02133891213389122,
            "0.25": 0.029288702928870293,
            "0.5": 0.04184100418410042,
            "0.75": 0.05439330543933055,
            "0.9": 0.14644351464435146
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.28326359832635983,
          "mean": 0.241182880055788,
          "median": 0.2581589958158996,
          "min": 0.14518828451882845,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.15355648535564853,
            "0.25": 0.24560669456066944,
            "0.5": 0.2581589958158996,
            "0.75": 0.2707112970711297,
            "0.9": 0.2786610878661088
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b"
  },
  {
    "configuration_label": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 27.0,
          "mean": 21.979166666666668,
          "median": 22.0,
          "min": 19.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 20.0,
            "0.25": 21.0,
            "0.5": 22.0,
            "0.75": 23.0,
            "0.9": 24.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.1506276150627615,
          "mean": 0.04776847977684798,
          "median": 0.03765690376569038,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.016736401673640166,
            "0.25": 0.02510460251046025,
            "0.5": 0.03765690376569038,
            "0.75": 0.05439330543933055,
            "0.9": 0.07112970711297072
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.38326359832635987,
          "mean": 0.3522315202231521,
          "median": 0.36234309623430966,
          "min": 0.2493723849372385,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.3288702928870293,
            "0.25": 0.3456066945606695,
            "0.5": 0.36234309623430966,
            "0.75": 0.37489539748953976,
            "0.9": 0.38326359832635987
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 27.0,
          "mean": 21.583333333333332,
          "median": 21.0,
          "min": 19.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 20.0,
            "0.25": 21.0,
            "0.5": 21.0,
            "0.75": 22.0,
            "0.9": 24.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.18410041841004185,
          "mean": 0.050710425383542534,
          "median": 0.03765690376569038,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.02092050209205021,
            "0.25": 0.02510460251046025,
            "0.5": 0.03765690376569038,
            "0.75": 0.0502092050209205,
            "0.9": 0.08368200836820083
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.38326359832635987,
          "mean": 0.3492895746164575,
          "median": 0.36234309623430966,
          "min": 0.21589958158995817,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.3163179916317992,
            "0.25": 0.3497907949790795,
            "0.5": 0.36234309623430966,
            "0.75": 0.37489539748953976,
            "0.9": 0.3790794979079498
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 24.0,
          "mean": 21.026041666666668,
          "median": 21.0,
          "min": 18.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 19.0,
            "0.25": 20.0,
            "0.5": 21.0,
            "0.75": 23.0,
            "0.9": 23.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.15481171548117154,
          "mean": 0.058817119944211994,
          "median": 0.04184100418410042,
          "min": 0.016736401673640166,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.02133891213389122,
            "0.25": 0.029288702928870293,
            "0.5": 0.04184100418410042,
            "0.75": 0.05439330543933055,
            "0.9": 0.14644351464435146
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.38326359832635987,
          "mean": 0.34118288005578806,
          "median": 0.3581589958158996,
          "min": 0.2451882845188285,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.25355648535564856,
            "0.25": 0.3456066945606695,
            "0.5": 0.3581589958158996,
            "0.75": 0.3707112970711297,
            "0.9": 0.37866108786610886
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149"
  },
  {
    "configuration_label": "baseline",
    "folds": [
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 518400.0,
          "mean": 164400.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 57600.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 187200.0,
            "0.9": 244800.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
        "fold_index": 0,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 20.0,
          "mean": 17.473958333333332,
          "median": 17.0,
          "min": 14.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 17.0,
            "0.25": 17.0,
            "0.5": 17.0,
            "0.75": 18.0,
            "0.9": 19.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.2011173184357542,
          "mean": 0.06378026070763501,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.0223463687150838,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.07262569832402235,
            "0.9": 0.09497206703910614
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.3276536312849162,
          "mean": 0.28621973929236494,
          "median": 0.29972067039106143,
          "min": 0.14888268156424578,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.2550279329608938,
            "0.25": 0.27737430167597765,
            "0.5": 0.29972067039106143,
            "0.75": 0.31648044692737426,
            "0.9": 0.3276536312849162
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 633600.0,
          "mean": 174525.0,
          "median": 129600.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 72000.0,
            "0.25": 86400.0,
            "0.5": 129600.0,
            "0.75": 172800.0,
            "0.9": 288000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
        "fold_index": 1,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.53125,
          "median": 16.0,
          "min": 13.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 14.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 17.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.24581005586592178,
          "mean": 0.06770833333333333,
          "median": 0.05027932960893855,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.027932960893854747,
            "0.25": 0.0335195530726257,
            "0.5": 0.05027932960893855,
            "0.75": 0.0670391061452514,
            "0.9": 0.11173184357541899
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.3276536312849162,
          "mean": 0.28229166666666666,
          "median": 0.29972067039106143,
          "min": 0.1041899441340782,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.238268156424581,
            "0.25": 0.2829608938547486,
            "0.5": 0.29972067039106143,
            "0.75": 0.31648044692737426,
            "0.9": 0.3220670391061452
          }
        }
      },
      {
        "anchor_span_seconds_summary": {
          "count": 192,
          "max": 532800.0,
          "mean": 202425.0,
          "median": 144000.0,
          "min": 57600.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 73440.00000000001,
            "0.25": 100800.0,
            "0.5": 144000.0,
            "0.75": 187200.0,
            "0.9": 504000.0
          }
        },
        "fitted_path_count": 192,
        "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
        "fold_index": 2,
        "low_quality_rejected_bar_count": 96,
        "near_miss_counts": {
          "0.01": 0,
          "0.02": 0,
          "0.05": 0,
          "0.1": 0
        },
        "path_length_summary": {
          "count": 192,
          "max": 19.0,
          "mean": 15.807291666666666,
          "median": 16.0,
          "min": 12.0,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 13.0,
            "0.25": 15.0,
            "0.5": 16.0,
            "0.75": 17.0,
            "0.9": 18.0
          }
        },
        "quality_methods": {
          "anchor_span_coverage_v1": 192
        },
        "quality_summary": {
          "count": 192,
          "max": 0.20670391061452514,
          "mean": 0.07853235567970206,
          "median": 0.055865921787709494,
          "min": 0.0223463687150838,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.028491620111731848,
            "0.25": 0.03910614525139665,
            "0.5": 0.055865921787709494,
            "0.75": 0.07262569832402235,
            "0.9": 0.19553072625698323
          }
        },
        "role_counts": {
          "RESISTANCE": 96,
          "SUPPORT": 96
        },
        "shadow_candidate_count": 192,
        "threshold_gap_summary": {
          "count": 192,
          "max": 0.3276536312849162,
          "mean": 0.27146764432029796,
          "median": 0.2941340782122905,
          "min": 0.14329608938547483,
          "quantile_method": "linear_interpolation_v1",
          "quantiles": {
            "0.1": 0.15446927374301675,
            "0.25": 0.27737430167597765,
            "0.5": 0.2941340782122905,
            "0.75": 0.3108938547486033,
            "0.9": 0.32150837988826814
          }
        }
      }
    ],
    "trial_id": "trendline-family-trial_00974389012896f1ea5f7ca6a815238a644ed4e133c5ff044411c2342079e0cf"
  }
]
```

## Parameter Contrasts

```json
{
  "baseline_180_0_35_neighbors": [
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "baseline",
        "overrides": {}
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": 0.0,
          "0.25": 0.0,
          "0.5": 0.0,
          "0.75": 0.0,
          "0.9": 0.0
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "valid_to_rejected_low_quality": 0
    },
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "baseline",
        "overrides": {}
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": 0.0,
          "0.25": 0.0,
          "0.5": 0.0,
          "0.75": 0.0,
          "0.9": 0.0
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 0
    }
  ],
  "lookback_120_vs_180_or_240": [
    {
      "accepted_candidate_count_delta_right_minus_left": -47,
      "bars_with_status_change": 47,
      "left": {
        "label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": -0.016900614994601194,
        "mean": -0.049762921928547955,
        "median": -0.036617999154969244,
        "min": -0.1239378432937421,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": -0.10224872071733719,
          "0.25": -0.06478569081263791,
          "0.5": -0.036617999154969244,
          "0.75": -0.028167691657668664,
          "0.9": -0.019717384160368057
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "valid_to_rejected_low_quality": 47
    },
    {
      "accepted_candidate_count_delta_right_minus_left": -47,
      "bars_with_status_change": 47,
      "left": {
        "label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": -0.02531556555676664,
        "mean": -0.07454027636159066,
        "median": -0.05485039203966105,
        "min": -0.18564748074962203,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": -0.15315917161843814,
          "0.25": -0.09704300130093879,
          "0.5": -0.05485039203966105,
          "0.75": -0.04219260926127774,
          "0.9": -0.029534826482894412
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b",
        "overrides": {
          "candidate.lookback_bars": 240,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "valid_to_rejected_low_quality": 47
    },
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": -0.016900614994601194,
        "mean": -0.049762921928547955,
        "median": -0.036617999154969244,
        "min": -0.1239378432937421,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": -0.10224872071733719,
          "0.25": -0.06478569081263791,
          "0.5": -0.036617999154969244,
          "0.75": -0.028167691657668664,
          "0.9": -0.019717384160368057
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 0
    },
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": -0.02531556555676664,
        "mean": -0.07454027636159066,
        "median": -0.05485039203966105,
        "min": -0.18564748074962203,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": -0.15315917161843814,
          "0.25": -0.09704300130093879,
          "0.5": -0.05485039203966105,
          "0.75": -0.04219260926127774,
          "0.9": -0.029534826482894412
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149",
        "overrides": {
          "candidate.lookback_bars": 240,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 0
    }
  ],
  "threshold_0_30_vs_0_40": [
    {
      "accepted_candidate_count_delta_right_minus_left": -47,
      "bars_with_status_change": 47,
      "left": {
        "label": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": 0.0,
          "0.25": 0.0,
          "0.5": 0.0,
          "0.75": 0.0,
          "0.9": 0.0
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_fe0a931f6c1ed339940bb6cfeb1d5d6b7e6f72b24358ceb56f1c4eb4182190f8",
        "overrides": {
          "candidate.lookback_bars": 120,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 47
    },
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "trendline-family-trial_47fa2862f6f14bf9acc738b891573b484c5d40b84a90e36474e08667dd06e7c7",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": 0.0,
          "0.25": 0.0,
          "0.5": 0.0,
          "0.75": 0.0,
          "0.9": 0.0
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_fc689697ebec2ba9ab66c15fabf9d6832680b77b13751319492e7941c5802548",
        "overrides": {
          "candidate.lookback_bars": 180,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 0
    },
    {
      "accepted_candidate_count_delta_right_minus_left": 0,
      "bars_with_status_change": 0,
      "left": {
        "label": "trendline-family-trial_342de46b5b9a17d0b14080cf1113bcf2411634e281b5faeffa8886cd490a0f0b",
        "overrides": {
          "candidate.lookback_bars": 240,
          "candidate.min_candidate_quality": 0.3
        }
      },
      "maximum_pre_threshold_quality_delta_right_minus_left": {
        "count": 288,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "quantile_method": "linear_interpolation_v1",
        "quantiles": {
          "0.1": 0.0,
          "0.25": 0.0,
          "0.5": 0.0,
          "0.75": 0.0,
          "0.9": 0.0
        }
      },
      "rejected_low_quality_to_valid": 0,
      "right": {
        "label": "trendline-family-trial_6fa8c34fe0f14756e5aad05dd26404d9b8f3a7ad8ac04bc6691b575b9c48d149",
        "overrides": {
          "candidate.lookback_bars": 240,
          "candidate.min_candidate_quality": 0.4
        }
      },
      "valid_to_rejected_low_quality": 0
    }
  ]
}
```

## Productive Trial Gate Deficit

```json
{
  "accepted_candidate_count": 47,
  "accepted_producing_bar_count": 47,
  "aggregate_reaction_quality": {
    "denominator": 3.0,
    "excluded_row_count": 19,
    "metric_version": "aggregate_v1",
    "name": "reaction_quality",
    "numerator": 0.8787878787878787,
    "sample_count": 47,
    "undefined_reason": null,
    "valid_row_count": 28,
    "value": 0.29292929292929293
  },
  "defined_primary_fold_count": 3,
  "failure_rate": 0.0,
  "fold_coverage_ratio": 1.0,
  "objective_gate_rejection_reasons": [
    "minimum_sample_count_not_met"
  ],
  "outcome_horizon_exclusions": 19,
  "overrides": {
    "candidate.lookback_bars": 120,
    "candidate.min_candidate_quality": 0.3
  },
  "per_fold_reaction_quality": [
    {
      "excluded_reasons": {
        "outcome_horizon_unavailable": 0
      },
      "fold_id": "trendline-family-walk-forward-fold_490553766b7f1f1ed90602b84779ee2df8edce16d271d1f94a98283f849e22de",
      "reaction_quality": {
        "denominator": 12.0,
        "excluded_row_count": 0,
        "metric_version": "v1",
        "name": "reaction_quality",
        "numerator": 4.0,
        "sample_count": 12,
        "undefined_reason": null,
        "valid_row_count": 12,
        "value": 0.3333333333333333
      }
    },
    {
      "excluded_reasons": {
        "outcome_horizon_unavailable": 12
      },
      "fold_id": "trendline-family-walk-forward-fold_bc14c9421fa6806405ea5e2b72ae9d080098369e7051391f068947b90a85031e",
      "reaction_quality": {
        "denominator": 5.0,
        "excluded_row_count": 12,
        "metric_version": "v1",
        "name": "reaction_quality",
        "numerator": 0.0,
        "sample_count": 17,
        "undefined_reason": null,
        "valid_row_count": 5,
        "value": 0.0
      }
    },
    {
      "excluded_reasons": {
        "outcome_horizon_unavailable": 7
      },
      "fold_id": "trendline-family-walk-forward-fold_fc9ac8fbca0898553383cb793f4bca08acfdc442b84d39fd203905b1447a2ace",
      "reaction_quality": {
        "denominator": 11.0,
        "excluded_row_count": 7,
        "metric_version": "v1",
        "name": "reaction_quality",
        "numerator": 6.0,
        "sample_count": 18,
        "undefined_reason": null,
        "valid_row_count": 11,
        "value": 0.5454545454545454
      }
    }
  ],
  "required_fold_count": 3,
  "required_minimum_sample_count": 100,
  "result_id": "trendline-family-trial-result_64c2b7ef5ecd1ea872a1fd057856543163109317dda1a6b5b437d07cd66fcc64",
  "sample_count": 47,
  "sample_deficit": 53,
  "trial_id": "trendline-family-trial_fd89bebdcbe1d91922f8178d6bac52c048ddd71d2a7359884812003141db70cb"
}
```

## Evidence Based Observations

```json
[
  "All status and quality summaries are validation-only provider replay evidence.",
  "Candidate scarcity is separated by canonical provider status before the diagnostic shadow path.",
  "The sole defined reaction-quality result is reported from verified persisted evidence, not recomputed."
]
```

## Research Hypotheses

```json
[
  "Does anchor_span_coverage_v1 remain restrictive for this fixed 4h validation window?",
  "Is the observed pre-threshold quality distribution misaligned with the approved quality grid?",
  "Would a separately approved longer validation dataset change the minimum-sample-gate evidence?",
  "Would a separately approved structural-density study isolate lookback and pivot availability?"
]
```
