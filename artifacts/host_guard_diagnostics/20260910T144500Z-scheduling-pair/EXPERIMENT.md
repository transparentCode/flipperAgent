# Fixed paired host-guard scheduling diagnostic

Status: PREPARED; neither arm launched by coder. Authority:
`plans/architect-to-coder-hostguard-scheduling-diagnostic-v1.md`.
Template: `artifacts/host_guard_diagnostics/20260910T143607Z/ac-smoke.plist`.

Hypothesis: launchd scheduling settings may contribute to intermittent host-probe
timeouts. The earlier ASSERTIONS timeout and subsequent passing foreground probes
do not establish scheduling causation.

| Arm | Plist | Label | Scheduling | Output files in this directory |
| --- | --- | --- | --- | --- |
| Background | background.plist | com.flipperagent.hostguard-pair-06101445-background | ProcessType Background; LowPriorityIO true | background.stdout.log; background.stderr.log |
| Standard | standard.plist | com.flipperagent.hostguard-pair-06101445-standard | ProcessType Standard; LowPriorityIO absent | standard.stdout.log; standard.stderr.log |

Both preserve the template interpreter, working directory, Aqua session and
environment. Both execute the immutable
`artifacts/ingestion_decision_24h_soak/20260910T082550Z/run-local/source/scripts/host_sleep_guard.py`
with `--max-check-gap 60 -- /bin/sleep 180`. Default probe interval/timeout,
startup timeout and termination grace remain 5/2/8/2 seconds respectively.
RunAtLoad is true; KeepAlive and other restart/scheduling triggers are absent.
AC/lid checks, owned assertion verification and terminal failure behavior are unchanged.

Parent execution protocol: load each exact plist once in the current user's GUI
launchd domain for one paired experiment. Record each load time and label, AC/lid
observations, terminal guard record, exit status and output files, retaining failures
and incomplete outcomes. Do not reload an arm to seek a passing outcome. After each
result, unload only its listed label; validate that the reported owned child and
assertion were cleaned up. Missing terminal evidence or cleanup uncertainty must be
reported as incomplete, not inferred successful. Parent owns execution and collection.

Both passing remains inconclusive for historical root cause. Either arm failing
does not establish causation; concurrent host load, shared resources and timing
remain possible confounders. Diagnostic completion grants no preflight or measurement
approval and does not resolve the separate websocket-quarantine finding.

Offline validation: both `plutil -lint` results OK. Mechanical plist comparison
passed: the exact differing keys are Label, StandardOutPath, StandardErrorPath,
ProcessType and LowPriorityIO. Each arm also matches its authorized transformation
of the template. Interpreter, guard, sleep and working-directory paths exist;
output files do not yet exist. AST inspection confirmed the unchanged guard defaults.
The frozen SOURCE_EXPORT_PROOF hash matches FROZEN_TOOLING_HASHES, and its approved
host-overlay hash matches both exported and canonical guard bytes.

SHA256:

- background.plist: `0d27e07e57ab8bff4437fe732d2d5cd21bb6437547ba01bda79d0c1b4b30f9b3`
- standard.plist: `a43c5518d233d44be18de7f3e8a913326ce5cbad6b5df1c743dd6f661c639287`
- Exported and canonical guard: `61d8f9265c84f1c94a5a11b86a22416ca0fede8f1739ec53b6be0d417458fc6d`
- Frozen source proof: `c28367d2cb10fd300d1d3a05a2ef3336559e329760cb95aef5ff6f198279d9f4`

Self-review Pass 1: exact authorized artifact scope, paths, labels, durations,
template equivalence and hashes verified. Pass 2: checked output isolation,
absence of restart policy, unchanged budgets, preserved failure checks and limited
causal interpretation. No material issue found; runtime evidence remains pending.
