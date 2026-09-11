#!/usr/bin/env python3
"""
S/R Zone Quality Audit.

Loads real OHLCV data, runs the S/R v2 pipeline bar-by-bar via
MultiBarRunner, evaluates zone quality metrics, and prints a
diagnostic report.

Usage:
    python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h --lookback 90
    python app/sr/scripts/zone_quality_audit.py -a ETHUSDT -t 4h \\
        --start-date 2025-01-01 --end-date 2026-01-01
    python app/sr/scripts/zone_quality_audit.py --help
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger("app.sr.scripts.zone_quality_audit")

_DEFAULT_YAML = Path(__file__).parent.parent / "config" / "sr.yaml"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="S/R zone quality audit on real market data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Recent 90 days
    python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h

    # Date range
    python app/sr/scripts/zone_quality_audit.py -a ETHUSDT -t 4h \\
        --start-date 2025-01-01 --end-date 2026-01-01

    # With custom config and bar range
    python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h \\
        --config app/sr/config/sr.yaml --bar-range 100:500
        """,
    )

    parser.add_argument(
        "-a", "--asset",
        type=str,
        default="BTCUSDT",
        help="Trading pair (default: BTCUSDT)",
    )
    parser.add_argument(
        "-t", "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to sr.yaml config (optional; uses defaults otherwise)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Overrides --lookback.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "-l", "--lookback",
        type=int,
        default=90,
        help="Lookback days from today (default: 90). Ignored if --start-date set.",
    )
    parser.add_argument(
        "--bar-range",
        type=str,
        default=None,
        help="Bar range as start:end (default: full data). E.g. 100:500",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=100,
        help="Minimum bars required to run audit (default: 100)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def resolve_config(asset: str, timeframe: str, config_path: Optional[str] = None):
    """Resolve SR config for the given asset/timeframe.

    Returns
    -------
    SRResolvedConfig
    """
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()

    if config_path is not None:
        from app.utils.ConfigLoader import ConfigLoader
        raw = ConfigLoader.load(config_path)
    elif _DEFAULT_YAML.exists():
        from app.utils.ConfigLoader import ConfigLoader
        raw = ConfigLoader.load(str(_DEFAULT_YAML))
    else:
        raw = {}

    return resolver.resolve(asset, timeframe, raw)


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------

def run_audit(
    df,
    asset: str,
    timeframe: str,
    config,
    start_bar: int = 0,
    end_bar: Optional[int] = None,
    quiet: bool = False,
) -> dict:
    """Run bar-by-bar pipeline and evaluate zone quality.

    Returns
    -------
    dict
        Audit results with metrics, composite score, zone count, and events.
    """
    from app.sr.optimization.multi_bar_runner import MultiBarRunner
    from app.sr.optimization.quality_metrics import ZoneQualityEvaluator
    from app.sr.pipeline import SRv2Pipeline

    pipeline = SRv2Pipeline(config, asset=asset, timeframe=timeframe)
    runner = MultiBarRunner(pipeline)

    if not quiet:
        bar_count = (end_bar or len(df)) - start_bar
        print(f"  Running {bar_count} bars through pipeline...")

    def _progress(current, total):
        if current % 1000 == 0 or current == total:
            pct = current / total * 100
            print(f"\r  Progress: {current:>6d}/{total} ({pct:5.1f}%)", end="", flush=True)
        if current == total:
            print()  # newline after final update

    run_result = runner.run(
        df, start_bar=start_bar, end_bar=end_bar,
        progress_callback=_progress if not quiet else None,
    )

    evaluator = ZoneQualityEvaluator()
    metrics = evaluator.evaluate(run_result)
    composite = evaluator.composite_score(metrics)

    return {
        "metrics": metrics,
        "composite_score": composite,
        "run_result": run_result,
    }


def print_report(
    asset: str,
    timeframe: str,
    audit: dict,
    bar_count: int,
) -> None:
    """Print formatted audit report."""
    metrics = audit["metrics"]
    composite = audit["composite_score"]
    rr = audit["run_result"]

    print()
    print("=" * 65)
    print("  S/R ZONE QUALITY AUDIT")
    print("=" * 65)
    print(f"  Asset:     {asset}")
    print(f"  Timeframe: {timeframe}")
    print(f"  Bars:      {bar_count}")
    print()

    # Quality metrics
    print("  QUALITY METRICS")
    print(f"    Survival Rate:       {metrics.survival_rate:.4f}")
    print(f"    Touch Accuracy:      {metrics.touch_accuracy:.4f}")
    print(f"    False Breakout Rate: {metrics.false_breakout_rate:.4f}")
    print(f"    Strength Stability:  {metrics.strength_stability:.4f}")
    print(f"    Coverage:            {metrics.coverage:.4f}")
    print()
    print(f"  COMPOSITE SCORE:       {composite:.4f}")
    print()

    # Zone counts
    print("  ZONE STATISTICS")
    print(f"    Total zones created:  {rr.total_zones_created}")
    print(f"    Zones reached active: {rr.zones_reached_active}")
    print(f"    Zones broken:         {rr.zones_broken}")
    print(f"    Zones expired:        {rr.zones_expired}")
    print()

    # Event histogram
    print("  EVENT HISTOGRAM")
    print(f"    Touches:          {rr.total_touches}")
    print(f"    Breakouts:        {rr.total_breakouts}")
    print(f"    False breakouts:  {rr.total_false_breakouts}")

    print("=" * 65)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    if not args.quiet:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    # 1. Fetch data
    from app.sr.scripts._utils import fetch_data

    try:
        if not args.quiet:
            print(f"\nFetching {args.asset} {args.timeframe}...")
        df = fetch_data(
            args.asset, args.timeframe,
            lookback_days=args.lookback,
            start_date=args.start_date,
            end_date=args.end_date,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: Failed to fetch data: {exc}", file=sys.stderr)
        return 1

    if len(df) < args.min_bars:
        print(
            f"ERROR: Insufficient data — got {len(df)} bars, need at least {args.min_bars}",
            file=sys.stderr,
        )
        return 1

    # 2. Resolve config (with wick-adaptive characteristics)
    try:
        from app.sr.scripts._utils import build_characteristics
        from app.sr.config_resolver import SRConfigResolver
        from app.utils.ConfigLoader import ConfigLoader

        config_path = args.config or str(_DEFAULT_YAML)
        raw_config = ConfigLoader.load(config_path) if Path(config_path).exists() else {}
        resolver = SRConfigResolver()

        # First resolve without characteristics to get metadata
        base_resolved = resolver.resolve(args.asset, args.timeframe, raw_config)
        # Build characteristics from data
        chars = build_characteristics(
            df, args.asset, args.timeframe,
            metadata=base_resolved.metadata,
        )
        # Re-resolve with characteristics for wick-adaptive params
        config = resolver.resolve(
            args.asset, args.timeframe, raw_config,
            characteristics=chars,
        )
        if not args.quiet:
            wick_ratio = chars.wick_body_ratio
            print(f"  Wick body ratio: {wick_ratio:.2f}")
            print(f"  Wick-adapted breakout_atr: {config.lifecycle.breakout_atr_threshold:.3f}")
            print(f"  Wick-adapted touch_prox:   {config.lifecycle.touch_proximity_atr:.3f}")
            print(f"  Wick-adapted recovery_bars: {config.lifecycle.false_breakout_recovery_bars}")
    except Exception as exc:
        print(f"ERROR: Config resolution failed: {exc}", file=sys.stderr)
        return 2

    # 3. Parse bar range
    start_bar = 0
    end_bar = None
    if args.bar_range:
        try:
            parts = args.bar_range.split(":")
            start_bar = int(parts[0])
            end_bar = int(parts[1]) if len(parts) > 1 and parts[1] else None
        except (ValueError, IndexError):
            print(f"ERROR: Invalid --bar-range format: {args.bar_range}", file=sys.stderr)
            return 2

    # 4. Run audit
    try:
        audit = run_audit(
            df, args.asset, args.timeframe, config,
            start_bar=start_bar, end_bar=end_bar,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: Audit failed: {exc}", file=sys.stderr)
        return 1

    # 5. Print report
    bar_count = (end_bar or len(df)) - start_bar
    print_report(args.asset, args.timeframe, audit, bar_count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
