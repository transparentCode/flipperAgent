# Mature Trendlines L1-A1 — Fractal Equal-Plateau Finality

## 1. Disposition

READY_FOR_L1A2_RDP_RUNTIME_RESTRICTION

L1-A1 is complete as a bounded fractal-only remediation. Equal-price plateau
pivots are withheld while their run remains open, then emitted once the run
closes and its final member has the configured right-window confirmation.

No commit was created in L1-A1.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Starting commit: `79bc269b482351c3c35c718ef1c0a409faeb6f30`
- Starting commit subject: `docs: audit trendline causality and repaint risk`
- Starting worktree: clean
- Canonical package tree before change:
  `a186219ce5ca1eb479ef2e8e64fc86b9d2f10e0f`
- Canonical package tracked-file count: 147

## 3. Worktree and environment proof

Work remained inside `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
Validation used:

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`
- Ruff: `/Users/aloobhujia/.local/bin/ruff`
- `PYTHONPATH=$PWD/src:$PWD`

Codebase-memory indexing was attempted for this isolated worktree but its
worker crashed on a file; live source inspection and focused validation were
used as fallback. No dependency or network operation was performed.

## 4. Original defect reproduction

An ephemeral frame with an eight-bar equal-high plateau at indices 20 through
27, `window_left=3`, and `window_right=3` reproduced the prior moving midpoint:

```text
moving_plateau_sequence [[20], [21], [21], [22], [22], [23], [23], [24]]
```

The selected pivot moved as equal bars arrived: `20 → 21 → 22 → 23 → 24`.
No fixture or audit script was persisted.

## 5. Finality invariant

For every successive prefix, every previously emitted fractal pivot tuple
`(side, index, value)` remains present in the next prefix output. A prior
tuple may not move, disappear, change side, or change value. This invariant is
limited to `FractalPivotExtractor`; RDP ZigZag remains outside its scope.

## 6. Implementation details

`_deduplicate_equal_pivots` was replaced by private helper
`_select_closed_plateau_midpoints` in:

```text
src/libs/models/trendlines/pivots/fractal.py
```

The helper groups contiguous equal candidate indices, checks the raw value
immediately after each group, suppresses terminal or still-equal groups, and
selects the existing midpoint for closed groups. Even-sized groups retain the
existing upper-middle rule. No persistent extractor state was introduced.

## 7. Open-plateau behaviour

High and low groups are treated identically. A group is open when its final
candidate is the final supplied row or the following raw high/low equals the
plateau value. Open groups are omitted from `PivotSet`, preventing a midpoint
from being published before the equal run is final.

## 8. Completed-plateau behaviour

For the eight-member group `20..27`, the run closes at index 28. With
`window_right=3`, the first complete output appears at frame length 31
(prefix ending at index 30), after three bars confirm the final plateau member.
The selected midpoint is 24 and remains 24 for all later prefixes.

## 9. `window_right=0` behaviour

A terminal candidate remains suppressed while it can still be extended by an
equal future bar. In the dedicated case, plateau candidate 20/21 is absent at
prefix lengths 21 and 22; after the non-equal closing bar arrives at prefix
length 23, the completed plateau emits midpoint 21. This is the documented
effective one-bar plateau-closure delay.

## 10. Dedicated finality tests

Added exactly eight non-parametrised tests in:

```text
src/libs/models/trendlines/tests/test_fractal_finality.py
```

Coverage includes open and completed high/low plateaus, isolated-pivot delay,
higher/lower follow-ons, `window_right=0`, and the public prefix append-only
invariant. Dedicated result:

```text
8 collected
8 passed
```

## 11. Prefix append-only evidence

The deterministic in-memory mixed high/low fixture was replayed from the
minimum valid prefix through the full 80-row frame:

```text
prefix transitions checked: 73
previously emitted fractal pivots removed: 0
previously emitted fractal pivots moved:   0
```

The eight-bar high plateau selected midpoint 24. The eight-bar low plateau
used the same closed-run and midpoint semantics. The dedicated test also
checks `previous <= current` for every prefix.

## 12. Completed-frame semantic parity

Completed equal plateaus preserve the old midpoint representation. For the
even group `20, 21, 22, 23, 24, 25, 26, 27`, the emitted midpoint remains 24,
the upper middle member. No leftmost or rightmost replacement was introduced.

## 13. Canonical regression

Baseline before remediation:

```text
266 collected
266 passed
```

Post-remediation canonical suite:

```text
274 collected
274 passed
```

The eight-test increase is the dedicated finality coverage.

## 14. Consumer regression

RegimeV2 trendline feature producer:

```text
6 passed
```

No production consumer or model behaviour outside fractal plateau selection
was changed.

## 15. Static validation

All required checks passed:

```text
compileall: passed
Ruff: passed
git diff --check: passed
```

Repository-local Python caches generated during validation were absent from the
worktree before handoff.

## 16. Files changed

```text
M  src/libs/models/trendlines/pivots/fractal.py
M  src/libs/models/trendlines/docs/pivots.md
A  src/libs/models/trendlines/tests/test_fractal_finality.py
?? plans/coder-to-orchestrator-trendlines-l1a1-fractal-plateau-finality-v1.md
```

## 17. Git diff summary

The implementation changes only closed-plateau selection and its documentation.
The new test file contains eight public-extractor tests. No RDP, API, fitter,
boundary, history, signal, configuration, Trendline V2, artifact, or research
path changed.

## 18. Git status

Expected final status after handoff creation:

```text
 M src/libs/models/trendlines/docs/pivots.md
 M src/libs/models/trendlines/pivots/fractal.py
?? src/libs/models/trendlines/tests/test_fractal_finality.py
?? plans/coder-to-orchestrator-trendlines-l1a1-fractal-plateau-finality-v1.md
```

No commit was created. No unrelated path is present.

## 19. Commands executed

```text
git status --short --untracked-files=all
git diff --name-status
git diff --stat
python -m pytest --collect-only -q src/libs/models/trendlines/tests
python -m pytest -q src/libs/models/trendlines/tests
python -m pytest -q src/libs/models/trendlines/tests/test_extractors.py src/libs/models/trendlines/tests/test_fractal_finality.py
python -m pytest --collect-only -q src/libs/models/trendlines/tests/test_fractal_finality.py
python -m pytest -q src/libs/models/trendlines/tests/test_fractal_finality.py
python -m pytest -q tests/test_regime_v2_trendline_feature_producer.py
python -m compileall -q src/libs/models/trendlines/pivots/fractal.py src/libs/models/trendlines/tests/test_fractal_finality.py
ruff check src/libs/models/trendlines/pivots/fractal.py src/libs/models/trendlines/tests/test_fractal_finality.py
git diff --check
```

## 20. Residual risks

- RDP ZigZag remains retrospective and suffix-sensitive; L1-A2 must restrict
  its runtime use.
- Public trendline APIs still lack explicit `as_of`, finality, provisional
  status, and revision identity; L1-B remains required.
- Append-only behaviour is established for this stateless fractal extraction
  contract, not for RDP or downstream line/signal snapshots.
- Plateau closure uses raw equal-value comparison, consistent with existing
  exact-equality semantics.

## 21. Recommended next phase

L1-A2 — Restrict RDP ZigZag to retrospective/research use.
