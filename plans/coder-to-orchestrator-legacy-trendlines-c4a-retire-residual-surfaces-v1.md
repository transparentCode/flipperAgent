# Legacy Trendlines Consolidation C4-A
## Retire Residual Non-Standard Legacy Trendline Surfaces

## 1. Disposition

C4-A completed. The residual benchmark and research notebook referencing deleted singular trendline packages were deleted. Durable ownership scanning now includes `benchmarks/` and `research/`. C4-A remains uncommitted for review.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Starting commit: `6e525bb refactor: delete app trendlines compatibility namespace`.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Starting status: clean.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, 0.15.20.
- `PYTHONPATH`: `$PWD/src:$PWD`.
- Canonical plural package: 147 tracked files.
- Independent Trendline V2 package: 33 tracked files.
- Retired package paths, compatibility namespaces, and C3-R1b surfaces remained absent.

Codebase-memory re-index was attempted before discovery and crashed on one file. Live source/text inventory and the durable AST/text boundary were used as fallback.

## 4. Immutable residual inventory

Before deletion:

```text
benchmarks/trendline_numba_atr.py
  95 lines
  SHA-256: 40d042bbff20c0daabcd05fd24fee6dc54f8ffd2a24cb315539a9fad82c67e00

research/trendline_family_research_lab.ipynb
  527 lines
  SHA-256: 5b8212edaab6747c172c717a322ca40705b4b79cc29b40989c272c7d39b8c4fa

Combined: 2 files, 622 lines
```

Tracked blob identities were recorded before deletion:

```text
benchmarks/trendline_numba_atr.py: 2c7a11903f0c8ec37bb6b5de49837442df2da3c7
research/trendline_family_research_lab.ipynb: 764173d06e208ee3042f8d6f01098b99615bb53a
```

## 5. Consumer proof

- Inbound references to `trendline_numba_atr`: 0.
- Inbound references to `trendline_family_research_lab`: 0.
- Pre-deletion non-standard namespace match count: 2.
- Exact pre-deletion matches:

```text
./benchmarks/trendline_numba_atr.py
./research/trendline_family_research_lab.ipynb
```

The benchmark used deleted singular interaction/tracking APIs. The notebook used deleted `libs.models.trendline_family` and research-lab APIs. Neither was migrated to the plural model or Trendline V2.

## 6. Pre-deletion baseline

- Retirement boundary: 6 passed.
- Canonical suite: 266 passed.
- RegimeV2 adapter: 6 passed.
- Trendline V2/viewer: 281 passed.
- Scripts: 283 passed, 21 skipped.

## 7. Benchmark deleted

Deleted:

```text
benchmarks/trendline_numba_atr.py
```

Deletion count: 1 file, 95 lines.

## 8. Research notebook deleted

Deleted:

```text
research/trendline_family_research_lab.ipynb
```

Deletion count: 1 file, 527 lines.

Notebook was not executed, migrated, regenerated, or copied into another active directory.

## 9. Durable ownership scanner expanded

`tests/models/test_legacy_trendline_retirement.py` now:

- scans Python AST imports under `src`, `tests`, `scripts`, `conductor`, `benchmarks`, and `research`;
- scans active text files under `benchmarks/` and `research/` with suffixes `.py`, `.ipynb`, and `.md`;
- excludes cache directories and notebook checkpoints;
- uses boundary-aware retired namespace matching so `libs.models.trendlines` and `libs.models.trendline_v2` are not classified as retired;
- adds absence and non-standard-root reference tests.

Expanded AST roots:

```text
src, tests, scripts, conductor, benchmarks, research
```

Text-scanner suffixes:

```text
.py, .ipynb, .md
```

## 10. Structural absence proof

- `benchmarks/trendline_numba_atr.py`: absent.
- `research/trendline_family_research_lab.ipynb`: absent.
- Git-tracked files at both paths: zero.
- Post-deletion non-standard namespace match count: 0.
- Retirement boundary: 8 passed.
- Canonical package count remains 147.
- Trendline V2 package count remains 33.

## 11. Post-deletion test results

- Retirement boundary: 8 passed.
- Canonical suite: 266 passed.
- RegimeV2 adapter: 6 passed.
- Trendline V2/viewer: 281 passed.
- Scripts: 283 passed, 21 skipped.
- Canonical CLI: passed.
- Canonical identity smoke: passed.

## 12. Static validation

- Compileall over canonical package, Trendline V2 package, and retirement test: passed.
- Targeted Ruff on retirement test: passed.
- `git diff --check`: passed.
- Repository-local `__pycache__` directories removed after validation.

## 13. Files changed

- Deleted: `benchmarks/trendline_numba_atr.py`.
- Deleted: `research/trendline_family_research_lab.ipynb`.
- Modified: `tests/models/test_legacy_trendline_retirement.py`.
- Added: this handoff.

## 14. Git diff summary

Tracked C4-A diff:

```text
2 deleted files
622 deleted residual-surface lines
1 modified retirement-boundary test
```

No other source, configuration, artifact, benchmark, research, or historical-plan path changed.

## 15. Git status

Worktree intentionally remains dirty and uncommitted for review:

```text
D  benchmarks/trendline_numba_atr.py
D  research/trendline_family_research_lab.ipynb
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4a-retire-residual-surfaces-v1.md
```

## 16. Commands executed

Preflight: branch, HEAD, status, worktree, log, canonical package counts, retired-path checks, Python/Ruff versions, source inventory, line counts, blob IDs, hashes, and required source reads.

Consumer proof: inbound basename searches and non-standard active-root namespace scan.

Mutation: `git rm benchmarks/trendline_numba_atr.py research/trendline_family_research_lab.ipynb`; `apply_patch` expansion of the retirement scanner; handoff creation.

Validation: baseline/post-change pytest suites, retirement boundary, canonical CLI help, identity smoke, compileall, Ruff, `git diff --check`, and cache cleanup.

No network, optimizer, replay, notebook execution, artifact generation, causality, or L0-B workflow was run.

## 17. Residual risks

- C4-B broad final ownership audit and repository regression remain outstanding.
- Historical plans and artifacts retain references by design and were not rewritten.
- Codebase-memory indexing remains unavailable because worker crashes on one file; live AST/text checks are authoritative for this phase.

## 18. Recommended next phase

`C4-B — Final single-package ownership audit and broad repository regression`

READY_FOR_C4B_FINAL_OWNERSHIP_REGRESSION
