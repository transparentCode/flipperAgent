# Trendline V2 Phase 10C.2 Rolling-Lookback Eviction Replay

Status: `LOOKBACK_EVICTION_TRANSITIONS_VERIFIED`

## Boundary

- Branch: `research/trendline-v2-phase-10c2-lookback-eviction-replay-v1`
- Base commit: `c4fda38766ab46ad6118616e5757f78a98b9f836`
- No commit, merge or push performed.
- Prior `fe93…` replay invocation stopped during tracking validation before
  artifact publication; it remains superseded blocked-attempt provenance.
- Replacement replay completed five provider iterations, then stopped before
  artifact publication because output-parent bootstrap was missing.
- Final publication-ready replay completed exactly five provider calls and
  published the verified bundle atomically.
- Network requests, retries, fallbacks, configuration variants and parallel
  execution remained zero.
- No `src/` files or existing source artifacts changed.

## Changed Files

- `scripts/replay_trendline_v2_lookback_eviction.py`
- `tests/scripts/test_trendline_v2_lookback_eviction.py`
- this handoff

## Implemented Offline Boundary

The script includes:

- exact Phase 10C.1 source verification and identity binding;
- the five fixed checkpoint definitions and 732-row effective-window checks;
- causal prefix construction with strict `< checkpoint` semantics;
- fixed configuration and selection/tracking policy identity checks;
- public discovery, selection and exact tracking replay wiring;
- source-removal attribution and removed-family reappearance guards;
- required-history-start attribution for first-anchor eviction and left-context
  eviction;
- canonical blocked-run JSON diagnostics with completed execution count;
- canonical typed provider-result reconstruction;
- atomic 12-file publication and manifest validation;
- zero-provider offline verification mode;
- dual generation guard and existing-output refusal.

## Contract Identity Resolution

The original planning digest is withdrawn and retained only as a supersession
record:

```text
5ae71a628947044ec6a0a904e87876955c243bfe287125437880095751327e2e
```

`5ae71a...` is `SUPERSEDED_UNREPRODUCIBLE_PLANNING_DIGEST`. It is not an
evidence identity and is not used by the runner.

Prior contract `fe93c86f...` is
`SUPERSEDED_PRE_LEFT_CONTEXT_ATTRIBUTION_CONTRACT`. It identifies blocked
attempt only and is not successful Phase 10C.2 evidence.

The approved canonical payload is derived by the runner from the exact fixed
Phase 10C.2 inputs. It binds:

```text
source contract/input, BTCUSDT/4h, causal prefix rule,
inclusive provider-history rule, 10,540,800-second lookback,
732 effective rows, five checkpoint dates/prefix counts/window starts,
execution order, configuration/policy identities, one-bar left-context
eligibility, required-history-start attribution, two removal causes,
unattributed-removal rejection, removed-family reappearance rule
```

The derived identity is:

```text
166b156a471f06dcc2d4fbf09196df95c4648e4b60cac52d1d315f7e7794af96
```

The implementation uses `REPLAY_CONTRACT_EXPECTED_ID` only as a check on this
derived value; `REPLAY_CONTRACT_ID` is computed from the canonical payload at
module initialization.

## Execution Authorization

One final five-call replay was gated on the approved environment variable and
explicit CLI flag. Preflight passed before execution. No retry, fallback,
fourth replay, commit, merge or push was performed.

## Preflight Evidence

- Focused replay tests: `31 passed, 1 skipped`.
- Ruff: passed.
- Compileall: passed.
- `git diff --check`: passed.
- Phase 10C.1 source verification: passed; source inventory remained
  `872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f`.
- Canonical Phase 10C.2 output root was absent before replay.
- Staging bootstrap tests passed, including missing-parent creation before
  `_replay_records`, zero calls on staging failure, staging cleanup on replay
  failure, and atomic publication from a missing parent.

## Immutable External Evidence Pinning

The opt-in external replay suite passed `32` tests. Its verifier assertion is
pinned to:

```text
decision_id: ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6
manifest_id: 4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5
output_inventory_sha256: 64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c
provider_execution_count: 0
network_request_count: 0
checkpoint_count: 5
```

The same test pins all five checkpoint input/provider/discovery/selection/
tracking identities and all checkpoint counts. Supporting evidence hashes are:

```text
removal_attribution.json: 14cadcbbf061ed37f8cf0926b458f9729c856f74c3e1d525cbc43feeab430691
provider_execution_audit.json: b5643c4e00125ce5e661b91675e5606806c1817c3446f5e148c50df6dff4f962
checkpoint_summary.csv: d6ec714ca01c83e97340dfaf3ffd0a8eb91b4234057e3935cb225feccaad48ed
```

Decision aggregates and both removal-cause counts are pinned. No provider
rerun or artifact regeneration was used for this remediation.

## Prior Blocked Attempt

The prior command used both required guards:

```text
TRENDLINE_V2_ALLOW_PHASE10C2_PROVIDER_REPLAY=1
--execute-eviction-replay
```

It stopped with:

```text
ReplayScopeBlocked: UNATTRIBUTED_SOURCE_REMOVAL
```

The failure occurred in `_validate_tracking_step` while validating source
removal attribution. The staged output was not published. No execution audit,
checkpoint artifacts, decision, manifest or inventory exists for that attempt;
completed provider-call count was not verified and must not be inferred as
zero.

## Final Publication-Ready Replay

Publication remediation adds:

- output-parent creation before provider call 1;
- pre-created staging directory under the output parent;
- atomic final `os.replace` publication;
- staging cleanup on preparation, replay and publication failures;
- staging-directory creation as the publication-readiness gate;
- no transient staging marker in the canonical bundle.

The authorized command used both guards and completed exactly five provider
calls through `_replay_records`:

```text
provider calls: 5
network requests: 0
retries: 0
fallbacks: 0
configuration variants: 0
parallel execution: 0
```

Published root:

```text
/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401
```

Offline `--verify` independently passed with:

```text
study_status: LOOKBACK_EVICTION_TRANSITIONS_VERIFIED
decision_id: ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6
manifest_id: 4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5
output_inventory_sha256: 64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c
manifest_members: 11
offline_provider_calls: 0
offline_network_requests: 0
```

Replay evidence:

```text
births: 645
continuations: 989
attributed removals: 322
unattributed removals: 0
removed-family reappearances: 0
final active families: 323
candidate-ID turnovers: 989
removal causes:
  first_anchor_evicted: 321
  first_anchor_left_context_evicted: 1
```

Checkpoint active-family counts: `321, 330, 335, 325, 323`.

Source verification remained unchanged before and after replay:

```text
source_inventory_sha256: 872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f
source_input_identity: 6397fc215f0c9d2fc7c6cdf1fe44e60e5530d7fef2c040cce2731661a5657a4c
source_immutability_verified: true
```

Staging-directory creation was the publication-readiness gate. No transient
staging marker was included in the canonical bundle.

No additional provider-executing replay is authorized under this handoff.
