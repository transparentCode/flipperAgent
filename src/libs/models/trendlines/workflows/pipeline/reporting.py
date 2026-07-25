"""Reporting and output formatting for trendlines pipeline workflows."""

from __future__ import annotations

from typing import Any, Dict


def print_results(results: Dict[str, Dict[str, Any]], asset: str, quiet: bool = False) -> None:
    if quiet:
        return

    print("\n" + "=" * 70)
    print("  TRENDLINES PIPELINE OPTIMIZATION RESULTS")
    print("=" * 70)
    print(f"\n  Asset: {asset}")

    for timeframe, result in results.items():
        print(f"\n  Timeframe: {timeframe}")
        print(f"  Fitness:   {result['best_fitness']:.4f} ± {result['best_fitness_std']:.4f}")
        print(f"  Windows:   {result['n_windows']}")
        if "study_status" in result:
            print(f"  Study:     {result['study_status']}")
        if "promotion_result" in result:
            print(f"  Promotion: {result['promotion_result'].get('status')}")


def print_pipeline_yaml_snippet(yaml_snippet: Dict[str, Any], *, quiet: bool) -> None:
    if quiet:
        return

    import yaml

    print("\n  Recommended trendlines_pipeline.yaml universe block:")
    print(f"  {'─' * 50}")
    snippet_str = yaml.dump({"universe": yaml_snippet}, default_flow_style=False, indent=2)
    for line in snippet_str.split("\n"):
        print(f"    {line}")


__all__ = [
    "print_pipeline_yaml_snippet",
    "print_results",
]
