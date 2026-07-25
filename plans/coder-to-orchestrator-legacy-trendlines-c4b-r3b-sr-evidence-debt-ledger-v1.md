# C4-B-R3b SR Evidence-Debt Ledger Handoff

## 1. Disposition

R3b complete. SR evidence debt is classified and frozen without changing SR
code, tests, configuration, research evidence, or artifacts.

Final disposition: `READY_FOR_C4BR4_FINAL_REGRESSION`

## 2. Starting branch and commit

Branch: `research/legacy-trendlines-quality-stability-v1`

HEAD: `122e1d32645fe122190d0d8108b6194865134066`

Commit subject: `test: make shadow removal contract missing-parent safe`

## 3. Expected dirty-worktree proof

Pre-existing dirty paths matched R3b scope:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
```

Only this R3b handoff was added. No commit was created for R3b.

## 4. Proof SR was unchanged

Both `git diff HEAD` and the full C4-B diff against `41fea18` were empty for:

```text
src/libs/models/sr
tests/models/sr
configs/sr_trials
research/tmp_sr*
```

R3a changed only its RegimeV2 removal test and committed handoff. No SR source,
test, configuration, or evidence file changed.

## 5. Ordinary SR model result

The ordinary SR model contract group passed:

```text
440 passed
```

Only research and script nodes are ledger exceptions.

## 6. Research result

```text
228 passed
29 failed
11 errors
```

No skip occurred.

## 7. Script result

```text
232 passed
6 failed
108 errors
```

No skip occurred.

## 8. Combined SR accounting

```text
Ordinary SR:  440 passed
Research:     228 passed, 29 failed, 11 errors
Scripts:      232 passed,  6 failed, 108 errors
------------------------------------------------
Total:        900 passed, 35 failed, 119 errors
```

Only 154 SR research/script nodes are exceptions.

## 9. Exact 154-node ledger

The normalized `FAILED`/`ERROR` node set contained exactly:

```text
154 nodes
```

The exact node-set hash is:

```text
bb2c285245847bd466797ddce9221c2d0ce966e1fe1763f8a70f2bbf0a8d2eb3
```

## 10. Node-set SHA-256

Computed from sorted normalized node names emitted by the combined research and
script pytest run. Count and SHA-256 matched the required ledger exactly.

## 11. Raw seven-signature ledger

Normalized raw signature counts:

```text
34  ContractValidationError: approved V1.5 bundle is missing or is a symlink
23  ContractValidationError: approved TAOUSDT development capsule is missing
73  ContractValidationError: artifact member set mismatch
20  ContractValidationError: V1.9 artifact member set mismatch
1   ContractValidationError: V2.3 history bundle must be a real directory
2   FileNotFoundError: research/tmp_sr_v1_5/
    d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925
1   FileNotFoundError: research/tmp_sr_v2_3/source/
    041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e
```

Counts total 154.

## 12. Five root-cause families

```text
Family A  MISSING_APPROVED_V1_5_SOURCE_BUNDLE          36
Family B  MISSING_APPROVED_TAOUSDT_DEVELOPMENT_CAPSULE 23
Family C  FROZEN_ARTIFACT_MEMBER_SET_MISMATCH          73
Family D  V1_9_ARTIFACT_MEMBER_SET_MISMATCH             20
Family E  MISSING_V2_3_HISTORY_BUNDLE                   2
                                                        ---
                                                        154
```

Family A binds to missing `research/tmp_sr_v1_5/` bundle
`d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`.
Family E binds to missing `research/tmp_sr_v2_3/source/` bundle
`041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e`.

## 13. Evidence filesystem state

Confirmed absent:

```text
research/tmp_sr_v1_5
research/tmp_sr_v2_3
```

No tracked files exist under `research/tmp_sr*`. Missing evidence was not
regenerated, copied, fetched, or published. Fail-closed provenance behavior was
preserved.

## 14. Configuration bindings

Relevant bindings remain in:

```text
configs/sr_trials/taousdt_1d_atr_calibration.yaml
configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml
configs/sr_trials/sr_v2_3_adaptive_context_calibration.yaml
configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml
```

They continue to reference the absent frozen source roots and immutable bundle
identities. No configuration was modified.

## 15. Non-SR and trendline preservation

```text
Non-SR model suite: 474 passed
Ownership boundary: 9 passed
Canonical trendlines: 266 passed
```

These suites are outside the SR exception ledger.

## 16. Files changed

R3b added only:

```text
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r3b-sr-evidence-debt-ledger-v1.md
```

No SR path changed.

## 17. Git status

Expected final status:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r3b-sr-evidence-debt-ledger-v1.md
```

R3a remains committed at `122e1d3`.

## 18. Commands executed

Executed R3b preflight, SR scope and filesystem checks, ordinary SR model suite,
research suite, script suite, combined node-set count/hash, raw signature
ledger, non-SR preservation suite, ownership boundary, canonical trendline
suite, diff check, and cache cleanup.

## 19. Residual risks

SR research evidence remains unavailable or structurally invalid. Later R4 must
exclude exactly these 154 fixed nodes and require all other tests to pass. No
evidence regeneration or contract weakening is authorized by this ledger.

## 20. Recommended next phase

```text
C4-B-R4 — Complete final regression using the fixed
25 alert/E2E exceptions plus 154 SR evidence exceptions
```

Expected fixed exceptions: `179`.

Expected runnable matrix: `4,000 - 179 = 3,821 tests`.

Final disposition:

```text
READY_FOR_C4BR4_FINAL_REGRESSION
```
