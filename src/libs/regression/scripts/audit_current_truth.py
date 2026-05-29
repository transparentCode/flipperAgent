from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.regime.orchestrator import RegimeOrchestrator
from app.regression.api import compute_single_tf_series, compute_universe
from app.regression.config.resolver import ConfigResolver
from app.utils.ConfigLoader import ConfigLoader


ROOT = Path(__file__).resolve().parents[3]
CSV_DIR = ROOT / "app" / "trendlines" / "optimization" / "results"
ASSETS = {
    "BTCUSDT": CSV_DIR / "BTCUSDT_1h_2023-01-01_2026-03-01.csv",
    "ETHUSDT": CSV_DIR / "ETHUSDT_1h_2023-01-01_2026-03-01.csv",
    "SOLUSDT": CSV_DIR / "SOLUSDT_1h_2023-01-01_2026-03-01.csv",
}
WINDOW_BARS = 2500
HORIZON_BARS = 12


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def _load_1h(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"]).set_index("open_time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return _ensure_utc(df).iloc[-WINDOW_BARS:]


def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    return df_1h.resample("4h").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna(subset=["close"])


def _align_results(
    df: pd.DataFrame,
    results: list,
    window_size: int,
    horizon: int,
) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()

    index = df.index[window_size - 1 : window_size - 1 + len(results)]
    frame = pd.DataFrame(
        {
            "close": df["close"].reindex(index).values,
            "confidence": [float(r.confidence) if np.isfinite(r.confidence) else np.nan for r in results],
            "slope": [float(r.slope) if np.isfinite(r.slope) else np.nan for r in results],
            "z_score": [float(r.z_score) if np.isfinite(r.z_score) else np.nan for r in results],
            "direction": [r.direction for r in results],
            "is_valid": [bool(r.is_valid) for r in results],
        },
        index=index,
    )
    frame["direction_sign"] = frame["direction"].map(
        {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}
    ).fillna(0.0)
    frame["fwd_lr"] = np.log(df["close"].shift(-horizon) / df["close"]).reindex(index)
    frame["abs_fwd_lr"] = frame["fwd_lr"].abs()
    frame["confidence_score"] = frame["confidence"] * 100.0
    return frame.replace([np.inf, -np.inf], np.nan)


def _monotonic_summary(frame: pd.DataFrame) -> dict:
    valid = frame.dropna(subset=["confidence_score", "abs_fwd_lr"])
    valid = valid[valid["is_valid"]]
    if len(valid) < 50:
        return {
            "n": int(len(valid)),
            "rho_abs_move": None,
            "top_bottom_abs_move_ratio": None,
            "overall_hit_rate": None,
            "top_hit_rate": None,
        }

    rho = valid["confidence_score"].corr(valid["abs_fwd_lr"], method="spearman")

    directional = valid.dropna(subset=["fwd_lr"])
    directional = directional[directional["direction_sign"] != 0]
    overall_hit_rate = (
        float((np.sign(directional["fwd_lr"]) == directional["direction_sign"]).mean())
        if len(directional)
        else None
    )

    try:
        bins = pd.qcut(valid["confidence_score"], q=5, labels=False, duplicates="drop")
    except ValueError:
        bins = pd.Series(np.zeros(len(valid), dtype=int), index=valid.index)

    valid = valid.assign(bin=bins)
    grouped = valid.groupby("bin").agg(
        mean_abs_move=("abs_fwd_lr", "mean"),
        mean_conf=("confidence_score", "mean"),
    )
    top_bin = grouped.index.max()
    bottom_bin = grouped.index.min()
    top_bottom_ratio = None
    denom = grouped.loc[bottom_bin, "mean_abs_move"]
    if pd.notna(denom) and denom > 0:
        top_bottom_ratio = float(grouped.loc[top_bin, "mean_abs_move"] / denom)

    top_directional = valid.loc[valid["bin"] == top_bin].dropna(subset=["fwd_lr"])
    top_directional = top_directional[top_directional["direction_sign"] != 0]
    top_hit_rate = (
        float((np.sign(top_directional["fwd_lr"]) == top_directional["direction_sign"]).mean())
        if len(top_directional)
        else None
    )

    return {
        "n": int(len(valid)),
        "rho_abs_move": round(float(rho), 4) if pd.notna(rho) else None,
        "top_bottom_abs_move_ratio": round(float(top_bottom_ratio), 4) if top_bottom_ratio is not None else None,
        "overall_hit_rate": round(float(overall_hit_rate), 4) if overall_hit_rate is not None else None,
        "top_hit_rate": round(float(top_hit_rate), 4) if top_hit_rate is not None else None,
        "top_confidence_mean": round(float(grouped.loc[top_bin, "mean_conf"]), 2),
        "bottom_confidence_mean": round(float(grouped.loc[bottom_bin, "mean_conf"]), 2),
        "top_abs_move_mean": round(float(grouped.loc[top_bin, "mean_abs_move"]), 5),
        "bottom_abs_move_mean": round(float(grouped.loc[bottom_bin, "mean_abs_move"]), 5),
    }


def _regime_family(label: str) -> str:
    text = str(label or "")
    if "QUIET_MR" in text:
        return "MR"
    if "TREND" in text:
        return "TREND"
    if "CHOPPY" in text:
        return "CHOPPY"
    return "OTHER"


def _trend_fit_summary(frame: pd.DataFrame) -> dict:
    valid = frame.dropna(subset=["fwd_lr", "confidence_score"])
    valid = valid[(valid["family"] == "TREND") & (valid["direction_sign"] != 0)]
    if len(valid) < 30:
        return {"n": int(len(valid)), "top_conf_hit_rate": None, "top_conf_mean_signed_lr": None}

    threshold = valid["confidence_score"].quantile(0.8)
    top = valid[valid["confidence_score"] >= threshold]
    signed_lr = top["direction_sign"] * top["fwd_lr"]
    return {
        "n": int(len(valid)),
        "top_conf_threshold": round(float(threshold), 2),
        "top_conf_hit_rate": round(float((signed_lr > 0).mean()), 4),
        "top_conf_mean_signed_lr": round(float(signed_lr.mean()), 5),
    }


def _mr_fit_summary(frame: pd.DataFrame) -> dict:
    valid = frame.dropna(subset=["fwd_lr", "z_score", "confidence_score"])
    valid = valid[(valid["family"] == "MR") & (valid["z_score"].abs() >= 1.0)]
    if len(valid) < 30:
        return {"n": int(len(valid)), "reversion_hit_rate": None, "mean_reversion_lr": None}

    threshold = valid["confidence_score"].quantile(0.6)
    top = valid[valid["confidence_score"] >= threshold]
    reverted_lr = -np.sign(top["z_score"]) * top["fwd_lr"]
    return {
        "n": int(len(valid)),
        "confidence_threshold": round(float(threshold), 2),
        "reversion_hit_rate": round(float((reverted_lr > 0).mean()), 4),
        "mean_reversion_lr": round(float(reverted_lr.mean()), 5),
    }


def main() -> None:
    raw = ConfigLoader.load(str(ROOT / "app" / "regression" / "config" / "regression.yaml"))
    resolver = ConfigResolver.from_dict(raw)

    audit_assets: dict[str, dict[str, pd.DataFrame]] = {}
    per_asset_timeframe: dict[str, dict] = {}
    all_1h_frames: list[pd.DataFrame] = []

    for asset, path in ASSETS.items():
        df_1h = _load_1h(path)
        df_4h = _resample_4h(df_1h)
        audit_assets[asset] = {"1h": df_1h, "4h": df_4h}

        for timeframe, frame in (("1h", df_1h), ("4h", df_4h)):
            config = resolver.resolve(asset, timeframe)
            results = compute_single_tf_series(df=frame, asset=asset, timeframe=timeframe, config=config)
            aligned = _align_results(frame, results, config.window_size, HORIZON_BARS)

            summary = _monotonic_summary(aligned)
            summary["rows"] = int(len(aligned))
            summary["window_size"] = int(config.window_size)
            per_asset_timeframe[f"{asset}:{timeframe}"] = summary

            if timeframe == "1h" and not aligned.empty:
                regime_orchestrator = RegimeOrchestrator.create(asset, "1h", cache_enabled=False)
                regime_frame = regime_orchestrator.analyze_series(df_1h)
                aligned = aligned.join(regime_frame[["regime"]], how="left")
                aligned["family"] = aligned["regime"].map(_regime_family)
                aligned["asset"] = asset
                all_1h_frames.append(aligned)

    aggregate_by_timeframe: dict[str, dict] = {}
    for timeframe in ("1h", "4h"):
        frames = []
        for asset in ASSETS:
            frame = audit_assets[asset][timeframe]
            config = resolver.resolve(asset, timeframe)
            results = compute_single_tf_series(df=frame, asset=asset, timeframe=timeframe, config=config)
            aligned = _align_results(frame, results, config.window_size, HORIZON_BARS)
            if not aligned.empty:
                aligned["asset"] = asset
                frames.append(aligned)

        combined = pd.concat(frames) if frames else pd.DataFrame()
        aggregate_by_timeframe[timeframe] = _monotonic_summary(combined) if not combined.empty else {}

    combined_1h = pd.concat(all_1h_frames) if all_1h_frames else pd.DataFrame()
    regime_family_summary: dict[str, dict] = {}
    if not combined_1h.empty:
        for family, frame in combined_1h.groupby("family"):
            regime_family_summary[family] = _monotonic_summary(frame)

    trend_fit = _trend_fit_summary(combined_1h) if not combined_1h.empty else {}
    mean_reversion_fit = _mr_fit_summary(combined_1h) if not combined_1h.empty else {}

    universe_data = {
        "BTCUSDT": {
            "4h": audit_assets["BTCUSDT"]["4h"].iloc[-400:],
            "1h": audit_assets["BTCUSDT"]["1h"].iloc[-1200:],
        },
        "ETHUSDT": {
            "4h": audit_assets["ETHUSDT"]["4h"].iloc[-400:],
            "1h": audit_assets["ETHUSDT"]["1h"].iloc[-1200:],
        },
        "SOLUSDT": {
            "1h": audit_assets["SOLUSDT"]["1h"].iloc[-1200:],
        },
    }
    universe_result = compute_universe(universe_data, resolver)
    universe_snapshot = {
        "results": {
            asset: {
                "direction": result.direction,
                "confidence": round(float(result.confidence), 4),
                "z_score": round(float(result.z_score), 4),
                "slope": round(float(result.slope), 6),
            }
            for asset, result in universe_result.results.items()
        },
        "mtf_results": {
            asset: {
                "direction_consensus": mtf.direction_consensus,
                "alignment_score": round(float(mtf.alignment_score), 4),
                "weighted_confidence": round(float(mtf.weighted_confidence), 4),
                "dominant_tf": mtf.dominant_tf,
                "is_conflicted": bool(mtf.is_conflicted),
            }
            for asset, mtf in universe_result.mtf_results.items()
        },
        "stats": {
            "n_assets_processed": int(universe_result.n_assets_processed),
            "n_degraded": int(universe_result.n_degraded),
            "n_failed": int(universe_result.n_failed),
        },
    }

    output = {
        "sample": {
            "assets": list(ASSETS),
            "window_bars_1h": WINDOW_BARS,
            "horizon_bars": HORIZON_BARS,
        },
        "per_asset_timeframe": per_asset_timeframe,
        "aggregate_by_timeframe": aggregate_by_timeframe,
        "regime_family_summary_1h": regime_family_summary,
        "trend_fit_1h": trend_fit,
        "mean_reversion_fit_1h": mean_reversion_fit,
        "universe_snapshot": universe_snapshot,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()