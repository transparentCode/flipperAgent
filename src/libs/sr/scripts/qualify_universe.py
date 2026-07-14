#!/usr/bin/env python3
"""
S/R Universe Qualification.

Computes structural metrics for all assets in the universe,
ranks them cross-sectionally, and assigns confidence tiers.
All ranking is relative (quartile-based) — no absolute thresholds.

Usage:
    # Qualify specific assets
    python app/sr/scripts/qualify_universe.py \\
        -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h --lookback 90

    # Qualify with date range
    python app/sr/scripts/qualify_universe.py \\
        -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h,4h \\
        --start-date 2025-01-01 --end-date 2026-01-01

    # Save report to JSON
    python app/sr/scripts/qualify_universe.py \\
        -a BTCUSDT,ETHUSDT -t 1h --output results/qualification.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger("app.sr.scripts.qualify_universe")

_DEFAULT_YAML = Path(__file__).parent.parent / "config" / "sr.yaml"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Structural qualification of SR universe assets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python app/sr/scripts/qualify_universe.py \\
        -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h --lookback 90

    python app/sr/scripts/qualify_universe.py \\
        -a BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \\
        -t 1h,4h --start-date 2025-01-01 --end-date 2026-01-01 \\
        --output results/qualification_report.json
        """,
    )
    parser.add_argument(
        "-a", "--assets",
        type=str,
        required=True,
        help="Comma-separated list of assets (e.g. BTCUSDT,ETHUSDT,SOLUSDT)",
    )
    parser.add_argument(
        "-t", "--timeframes",
        type=str,
        default="1h",
        help="Comma-separated timeframes (default: 1h)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to sr.yaml config (optional; uses default sr.yaml)",
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
        "--output", "-o",
        type=str,
        default=None,
        help="Save report to JSON file (optional)",
    )
    parser.add_argument(
        "--skip-survival",
        action="store_true",
        help="Skip quick_survival metric (faster, no pipeline run)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_raw_config(config_path: Optional[str] = None) -> dict:
    """Load raw sr.yaml config."""
    from app.utils.ConfigLoader import ConfigLoader

    path = config_path or str(_DEFAULT_YAML)
    return ConfigLoader.load(path)


def get_qualification_config(raw_config: dict) -> dict:
    """Extract the sr.qualification section."""
    sr = raw_config.get("sr", {})
    return sr.get("qualification", {})


def resolve_sr_config(raw_config: dict, asset: str, timeframe: str):
    """Resolve SR config for a specific asset/timeframe (for quick_survival)."""
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()
    return resolver.resolve(asset, timeframe, raw_config)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_qualification(
    assets: list[str],
    timeframes: list[str],
    raw_config: dict,
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip_survival: bool = False,
    quiet: bool = False,
):
    """Run the full qualification pipeline.

    Returns
    -------
    UniverseQualificationReport
    """
    from app.sr.qualification.screener import StructuralScreener, StructuralMetrics
    from app.sr.qualification.qualifier import AssetQualifier
    from app.sr.scripts._utils import fetch_data

    qual_config = get_qualification_config(raw_config)
    screener = StructuralScreener(qual_config)
    qualifier = AssetQualifier(qual_config)

    # Fetch data and screen each (asset, timeframe) pair
    all_metrics: list[StructuralMetrics] = []

    for asset in assets:
        for tf in timeframes:
            if not quiet:
                print(f"Screening {asset} {tf}...", flush=True)

            # Fetch OHLCV
            df = fetch_data(
                asset, tf,
                lookback_days=lookback_days,
                start_date=start_date,
                end_date=end_date,
                quiet=quiet,
            )

            if df.empty or len(df) < 50:
                logger.warning(
                    "Insufficient data for %s %s (%d bars), skipping",
                    asset, tf, len(df),
                )
                all_metrics.append(StructuralMetrics(
                    asset=asset,
                    timeframe=tf,
                    bar_count=len(df),
                    errors={"data": f"Insufficient bars: {len(df)}"},
                ))
                continue

            # Resolve SR config for pipeline-based metrics
            sr_config = None
            if not skip_survival:
                try:
                    sr_config = resolve_sr_config(raw_config, asset, tf)
                except Exception as e:
                    logger.warning(
                        "Could not resolve SR config for %s %s: %s", asset, tf, e
                    )

            metrics = screener.screen(df, asset, tf, sr_config=sr_config)
            all_metrics.append(metrics)

            if not quiet:
                poc_str = f"{metrics.poc_stability:.4f}" if metrics.poc_stability is not None else "N/A"
                wick_str = f"{metrics.wick_body_ratio:.2f}" if metrics.wick_body_ratio is not None else "N/A"
                surv_str = f"{metrics.quick_survival:.2f}" if metrics.quick_survival is not None else "N/A"
                if metrics.errors:
                    print(f"  bars={metrics.bar_count} (errors: {metrics.errors})", flush=True)
                else:
                    print(
                        f"  bars={metrics.bar_count} poc_cv={poc_str} wick={wick_str} surv={surv_str}",
                        flush=True,
                    )

    # Rank and tier
    report = qualifier.qualify(all_metrics)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = parse_args(argv)
    assets = [a.strip() for a in args.assets.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    if not assets:
        print("ERROR: No assets specified", file=sys.stderr)
        return 1

    # Load config
    raw_config = load_raw_config(args.config)

    # Run qualification
    report = run_qualification(
        assets=assets,
        timeframes=timeframes,
        raw_config=raw_config,
        lookback_days=args.lookback,
        start_date=args.start_date,
        end_date=args.end_date,
        skip_survival=args.skip_survival,
        quiet=args.quiet,
    )

    # Print report
    print()
    print(report.summary_table())
    print()

    # Save to JSON if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"Report saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
