"""CLI monitor for Momentum optimization studies.

Usage:
    PYTHONPATH=src python -m libs.models.momentum.optimization.monitor
"""

from __future__ import annotations

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import optuna


def print_study_summary(study: optuna.Study) -> None:
    """Print a summary of an Optuna study."""
    trials = study.trials
    completed = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in trials if t.state == optuna.trial.TrialState.PRUNED]
    failed = [t for t in trials if t.state == optuna.trial.TrialState.FAIL]

    print(f"\nStudy: {study.study_name}")
    print(f"{'='*50}")
    print(f"Total trials:     {len(trials)}")
    print(f"  Completed:      {len(completed)}")
    print(f"  Pruned:         {len(pruned)}")
    print(f"  Failed:         {len(failed)}")

    if completed:
        try:
            best = study.best_trial
            print(f"\nBest trial #{best.number}:")
            print(f"  Value:  {best.value}")
            print(f"  Params: {best.params}")
        except ValueError:
            pareto = study.best_trials
            print(f"\nPareto front ({len(pareto)} trials):")
            for t in pareto[:5]:
                print(f"  Trial #{t.number}: values={t.values} params={t.params}")
    print(f"{'='*50}\n")


def main() -> None:
    print("Momentum optimization monitor")
    print("Pass an Optuna study object to print_study_summary() programmatically.")


if __name__ == "__main__":
    main()
