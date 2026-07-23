# Coder Handoff: Trendline V2 Phase 9C.1 Fresh Scope Sources

## 1. Status

```text
READY_FOR_ORCHESTRATOR_REVIEW
PHASE_9C1: COMPLETE
PHASE_9C1_REMEDIATION: COMPLETE
PHASE_9C1_ROW_COUNT_REMEDIATION: COMPLETE
HISTORICAL_ACQUISITION_REQUESTS: 6
REMEDIATION_NETWORK_REQUESTS: 0
PHASE_9C2: NOT_YET_AUTHORIZED
PROVIDER_EXECUTION: NOT_AUTHORIZED
CANDIDATE_EVALUATION: NOT_AUTHORIZED
ELIGIBILITY_FAMILY_SELECTION: NOT_AUTHORIZED
PARAMETER_PROMOTION: NOT_AUTHORIZED
CANONICAL_CONFIG_CHANGE: NOT_AUTHORIZED
TRACKER_START: NOT_AUTHORIZED
MTF: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PUSH: NOT_AUTHORIZED
COMMIT: NOT_YET_AUTHORIZED
```

Branch:

```text
research/trendline-v2-phase-9c1-fresh-scope-sources-v1
```

Base commit:

```text
823bfb1b2fe765f5a832fc76c145e94f3c79cf84
```

## 2. Changed Files

```text
scripts/freeze_trendline_v2_fresh_scope_sources.py
tests/scripts/test_trendline_v2_fresh_scope_sources.py
plans/coder-to-orchestrator-trendline-v2-phase-9c1-fresh-scope-sources-v1.md
```

No `src/libs/models/trendline_v2/`, viewer, Binance adapter, configuration,
YAML, Trendline Family, Regime, tracker or MTF file changed.

## 3. Fixed Network Contract

Market:

```text
binance_usd_m_futures
```

Window:

```text
start: 2026-05-22T00:00:00Z
end/confirmed-through: 2026-07-01T00:00:00Z
```

Request parameters for every dataset:

```text
since_ms: 1779408000000
until_ms: 1782864000000
limit: 1000
retries: 0
fallbacks: 0
pagination: 0
```

The six calls executed sequentially in contract order:

```text
1  BTCUSDT  1h  raw 961  confirmed 960
2  BTCUSDT  4h  raw 241  confirmed 240
3  ETHUSDT  1h  raw 961  confirmed 960
4  ETHUSDT  4h  raw 241  confirmed 240
5  SUIUSDT  1h  raw 961  confirmed 960
6  SUIUSDT  4h  raw 241  confirmed 240
```

Each source retained exact 40-day spacing and boundaries. The end-open candle
was excluded by close-time filtering:

```text
1h last confirmed open: 2026-06-30T23:00:00Z
4h last confirmed open: 2026-06-30T20:00:00Z
```

Actual consumed request count: `6`. No retry, fallback, replacement source,
pagination or additional request occurred.

## 4. Dataset Identities

```text
dataset        adapter_rows_identity                                      input_identity                                            dataset_source_identity
btcusdt_1h     c0efc5181db31e18c171ab6d7c7431e85adb7d8aacf428ee57199ca9b7a285d5  dde3d8a82109e4eda6dfec8b1a128e7896dc6845bcd47bab5754eefcc79623e9  674e1a6e003422cb8f19dd0b9370920cf3c8632fd13b043bd96c2d7170ba0353
btcusdt_4h     9e4793a6795a7a885d5b6e627c1d0d7028f5ca92935fe36243aca53e1b097ee5  2de51ce8f76920b92269fe94c78efb636944d4c804d5dd723875903df5bc8aa8  3ab2c44543f7c5d7256086b10de8d1608cd93ca0eb0a82a544bfc6d71443be3a
ethusdt_1h     ff830ab813dfbf139ba6b0e4c5e90e718ab62b03f33dacada680012746f3bb69  483d29e4aa2b32d85d00f8a58f956f84dfbf3ba14f6e80b80210968e85424469  e82e884f02ce94e4fc428082073f8bbfa96165fa1eb5655876adcf7e5115ea13
ethusdt_4h     5b53114c812f8e5858ab37726fd7f343a1327b76d98a8af9d34a5d2d4f6b9f68  35965d4fe6b90298340a130063596011b3e0bcbff26463d68525f6097a762239  1a47f75b857f496332ff3f063af02a4b4d96c9c9b57d4fc5a2574e76091058c3
suiusdt_1h     082f198058d992bae1a8aac65240c32c1529626ce6890b2900bfbc20a236583f  713f24aa59bb0d8f9dbb4040cdbd56fa89c1890c263d9b9c6bc72c3c669679ae  475f0b62e437a8402c54631b79c1fa578765d70b07741f9eb3e91ffffcf09b2c
suiusdt_4h     12c81737ffe7f96ba0357f5479ba0e93637e2af5e697035f6edcfa0b3ffe9cc5  7a43ce7b5b8489e46edebe61a32144046c2309387a1998077f4ba2d08214cfae  85d868a6982e4b17cc96acf0b853b03d7099096806179f66d2f3ef042f71efd3
```

Top-level identities:

```text
cohort_contract_id:  55fabdf05929e923776d810c9958b26c44a8e85a5b92f73ec3027ab92dfcf00a
cohort_source_identity: c8cb7ecb7337020d09b3fe7a3026a14b84d07734252aa9bfa3f563d30f36ae72
```

Each `provider_input.json` reconstructs to existing immutable
`ProviderInput`, with equal serialization, exact identity and expected row
count. No provider configuration is attached.

## 5. Artifact Bundle

Canonical root:

```text
/tmp/trendline_v2_phase9c1_fresh_scope_sources/20260522_20260701/
```

The unchanged pre-remediation source is preserved separately at:

```text
/tmp/trendline_v2_phase9c1_fresh_scope_sources_superseded/
20260522_20260701_pre_integrity_remediation/
```

The prior corrected bundle, superseded only to add explicit `row_count`, is
preserved separately at:

```text
/tmp/trendline_v2_phase9c1_fresh_scope_sources_superseded/
20260522_20260701_pre_row_count_remediation/
```

Manifest binds 22 data members. Member sizes and hashes:

```text
cohort_contract.json                                  2257  1eb1757ff4fcd15748e7d18f47304237721169a5dfdaf84ba2ff6b1e049db362
datasets/btcusdt_1h/adapter_rows.json                102246  9fcc511b8da928e84a517d7463f763982a40a495fd2e57119715be28d4bcdf91
datasets/btcusdt_1h/provider_input.json               58992  1c45e07cca3ea74d6735c69f41fcd29f4ef842e89fc96a17dbefacc1f4346505
datasets/btcusdt_1h/run_report.json                     980  f04fb3b97ad8d603afae6dd08adba0215883ed43636ad11d3ee65d8c3dd140e0
datasets/btcusdt_4h/adapter_rows.json                 26041  ae7fb578832e058f00bc650e8bd303e98ed534d53c85651f55d3c758443606de
datasets/btcusdt_4h/provider_input.json                15186  d64ec9e63b9a36571a5e658550a1973d3deffec2f3c4e6d94d36ad465fc3781a
datasets/btcusdt_4h/run_report.json                     981  2433a1a97b9ce05016a471a957847869d1286afac91da3093a1d8d5b99026a40
datasets/ethusdt_1h/adapter_rows.json                103042  88a9914a3ba921c422dde249814519d3095e61ea00ddd673956cf279ef8a327a
datasets/ethusdt_1h/provider_input.json               59788  4126154b1e2536b90dd7ea27d1c91e8f33ef9242a0d7fe25ac76f608735c8923
datasets/ethusdt_1h/run_report.json                     980  a17307e04d63291b4dea49ebb78e1faaa41176c2474c8fbcfb2e2dc8df7981dc
datasets/ethusdt_4h/adapter_rows.json                 26175  2973f23d724f32c7e77f7280c5efd9020b41fb325ffe785d67d550e0efacbcae
datasets/ethusdt_4h/provider_input.json                15319  ff69d1a149b6c6d7dc2cdd76cf682cab687ae8d887c6bf9d0e844d5c72bba2fd
datasets/ethusdt_4h/run_report.json                     981  bd73f5245dd448a03ddc717c7aec06683e0fa66f3b2ff6029792d109953dad44
datasets/suiusdt_1h/adapter_rows.json                 99216  51df3c10b9213c3cbe16cb981bb20015bbd834a2d3069ce6935ac2bfcd307e10
datasets/suiusdt_1h/provider_input.json                55965  d96290b323e3dac7793bb4121ade405ce8ec32a0ee2d04cf1ce241927f587471
datasets/suiusdt_1h/run_report.json                     980  8c3dfa52a805e37dd5903a96cd214b7a77e449a11ea28213ada826f94c0a0642
datasets/suiusdt_4h/adapter_rows.json                 25259  81db17eddf30a6c8e217fc42a8f2f261857fd48a27bf9ffc509a7a25ce41ad43
datasets/suiusdt_4h/provider_input.json                14407  955435e0014b9748ba9a2f726efd116e812210b8e636ac616336f187285fbb1c
datasets/suiusdt_4h/run_report.json                     981  7e074096b2f0e7218424e148927dbfc46980c5d75158e3a2969e86b591794082
decision.json                                            2783  df1b0d2881e744c625f7d3519257c3394e5316600f6dae1ba9ee8b4e50cb2eaa
network_audit.json                                      1334  46cafd8ccc7d66872f5ced922ccda0a669123b3cb095a2e8a08f12d54c0317bf
source_summary.csv                                      1805  7ae9246c6bb542ae3cd52889c37e573d013ee5210d40cefe7d412655374c755e
```

Content identities:

```text
decision_id:       215600f4b80c356e95e969948dfd12ba57b17a55b140c25a8ea78ad3c9c15424
decision.json SHA: df1b0d2881e744c625f7d3519257c3394e5316600f6dae1ba9ee8b4e50cb2eaa
manifest_id:       e2afa4234054396ce5a7343eeb30f0e409fb56f0766c9c11a067180162374d56
manifest.json SHA: e647eb64303f913ea117239a09de9437d35310bb34d5beacf004e08b312bda8c
corrected 23-file inventory SHA: 631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be
pre-row-count 23-file inventory SHA: 333a3beef4980952390d066cff8da44f14404e1f49e7dd842a34a84cce1bb3f1
superseded 23-file inventory SHA: e4c153f5f88a6a1f8e8d001d0270bfee4b3d4ac1672fe1a651e975b25f7d2562
```

Independent reload through `verify_bundle(...)` passed. Manifest member sizes,
hashes, semantic IDs, canonical JSON and recursive inventory all reconcile. All
six typed-input artifacts explicitly bind `row_count` (`960` for 1h and `240`
for 4h). The corrected decision and manifest bind original source inventory
and record `remediation_network_request_count: 0`; historical acquisition
remains six requests.

## 6. Scope Proof

```text
network_request_count:       6
historical_acquisition_requests: 6
remediation_network_requests:     0
retry_count:                 0
fallback_count:              0
provider_execution_count:    0
candidate_generation_status: NOT_EXECUTED for all datasets
```

Runner requires both `--execute-network` and
`TRENDLINE_V2_ALLOW_PHASE9C1_NETWORK=1` before adapter construction. Failure
stops fixed-order execution, removes staging output and never publishes the
canonical root. Successful publication uses staging plus atomic directory
rename. Existing output root is refused.

The six historical adapter calls are retained as acquisition evidence. The
remediation constructed no adapter, made no network request, executed no
provider, evaluator, family, viewer, tracker, MTF, configuration or runtime
path. No generated artifact entered Git.

## 7. Validation

```text
Hermetic Phase 9C.1 tests:             41 passed, 2 skipped
Read-only external verification:       43 passed
Viewer + Trendline V2 suites:         135 passed
Protected Trendline Family suite:     400 passed
Provider benchmark harness:             4 passed
Frontend npm test/build:               13 passed
npm audit:                               0 vulnerabilities
Ruff:                                  passed
compileall:                            passed
git diff --check:                      passed
Independent artifact verification:     passed
```

Normal suite retains two gated external-evidence skips. With
`TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1`, it passed read-only against the
row-count-corrected canonical bundle, rejected missing/invalid persisted
counts in copied bundles, and did not issue network calls or regenerate files.

The superseded pre-remediation bundle was inventoried before and after the
offline correction and remained byte-identical at
`e4c153f5f88a6a1f8e8d001d0270bfee4b3d4ac1672fe1a651e975b25f7d2562`.
The prior corrected bundle was also preserved byte-identically at
`333a3beef4980952390d066cff8da44f14404e1f49e7dd842a34a84cce1bb3f1`.

## 8. Limitations and Decision Boundary

This bundle freezes six fresh normalized OHLCV inputs only. It contains no
candidate, continuation, eligibility-family, predictive, trading, tracking or
MTF evidence. No family, parameter or runtime filter was selected.

Phase 9C.2 may be reviewed separately for six local provider executions and
cross-asset/timeframe family evaluation. It remains unauthorized by this
handoff.

```text
READY_FOR_ORCHESTRATOR_REVIEW
```
