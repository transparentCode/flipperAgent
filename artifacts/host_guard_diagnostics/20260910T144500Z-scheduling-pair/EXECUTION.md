# Single paired launchd execution

Parent loaded background then standard once at approximately 2026-09-10T14:49:15Z
(timestamp after the two successful bootstrap commands; not individual exact starts).
AC71% charging and lid open verified before launch. Both labels absent beforehand.
Parent independently checked plist semantics and identical exported/canonical guard
hash61d8f9265c84f1c94a5a11b86a22416ca0fede8f1739ec53b6be0d417458fc6d.

At about20s elapsed, both launchctl records show runs1 and state running:

- Background guard66199, assertion66238, child66242; spawn type background5,
  low priority IO property positively observed.
- Standard guard66201, assertion66231, child66235; spawn type daemon3,
  low priority IO absent.

Each child is /bin/sleep180. Each owned assertion is caffeinate -i -s -w GUARD_PID.
All groups distinct. No SUT or MCP changes. Final outcomes pending; these live
observations cannot establish historical timeout causation.

## Final outcome

Both ran exactly once and completed (launchctl last exit0). Terminal guard records
are in each arm's stderr.log; stdout remained empty by the guard CLI convention.

- Background: start14:49:16.049749Z, finish14:52:16.935838Z, CHILD_EXITED,
  child_returncode0; last full verification14:52:16.928188Z.
- Standard: start14:49:15.935538Z, finish14:52:16.260518Z, CHILD_EXITED,
  child_returncode0; last full verification14:52:16.247016Z.

All six guard/assertion/child PIDs absent after completion. Parent booted out only
the two diagnostic labels successfully. No retries, extensions, or Docker changes.
Conclusion: causally inconclusive; neither timeout reproduced. Standard is a
scheduling-policy mitigation, not a proven cure. Both final owned verification
checks passed, but these180s samples cannot establish900s or24h reliability.

Independent guard regression run:54passed1.24s, root cleanup hook excluded.
