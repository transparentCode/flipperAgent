"""Trendlines-owned temporal split contracts for data and workflow replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Tuple

import pandas as pd

from libs.models.trendlines.config import EvaluationConfig
_eval_cfg = EvaluationConfig()

TRENDLINE_AUTO_SPLIT_POLICY = "trendlines_pipeline_auto"
TRENDLINE_AUTO_SPLIT_POLICY_VERSION = "v1"

_BARS_PER_DAY_CRYPTO = {
    "1m": 1440,
    "3m": 480,
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "2h": 12,
    "4h": 6,
    "1d": 1,
}

_ASSET_CLASS_DAILY_SCALE = {
    "crypto": 1.0,
    "equity": 6.5 / 24,
    "fx": 1.0,
    "commodity": 0.96,
}


def _stable_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WalkForwardSplit:
    """Describes one train or test fold in a walk-forward run."""

    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_size(self) -> int:
        return self.test_end - self.test_start


class WalkForwardValidator:
    """Rolling walk-forward cross-validator for deterministic temporal plans."""

    def __init__(
        self,
        train_bars: int = 2160,
        test_bars: int = 720,
        step_bars: int = 720,
        purge_bars: int = 24,
        min_train_bars: int = 1440,
    ):
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.purge_bars = purge_bars
        self.min_train_bars = min_train_bars

    def n_folds(self, n_bars: int) -> int:
        usable = n_bars - self.train_bars - self.purge_bars
        if usable < self.test_bars:
            return 0
        return max(1, (usable - self.test_bars) // self.step_bars + 1)

    def get_splits(self, n_bars: int) -> List[WalkForwardSplit]:
        splits: List[WalkForwardSplit] = []
        fold_id = 0
        train_start = 0

        while True:
            train_end = train_start + self.train_bars
            test_start = train_end + self.purge_bars
            test_end = test_start + self.test_bars

            if test_end > n_bars:
                break
            if (train_end - train_start) < self.min_train_bars:
                break

            splits.append(
                WalkForwardSplit(
                    fold_id=fold_id,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            train_start += self.step_bars
            fold_id += 1

        return splits

    def iterate_splits(
        self,
        df: pd.DataFrame,
    ) -> Iterator[Tuple[WalkForwardSplit, pd.DataFrame, pd.DataFrame]]:
        n_bars = len(df)
        for split in self.get_splits(n_bars):
            train_df = df.iloc[split.train_start : split.train_end].copy()
            test_df = df.iloc[split.test_start : split.test_end].copy()
            yield split, train_df, test_df


@dataclass(frozen=True)
class TemporalSplitSpec:
    """Typed walk-forward split policy resolved before a trendlines run executes."""

    split_kind: str
    train_bars: int
    test_bars: int
    step_bars: int
    purge_bars: int = 0
    min_train_bars: int | None = None
    timeframe: str | None = None
    asset_class: str = "crypto"
    policy_name: str = "manual"
    policy_version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.train_bars <= 0 or self.test_bars <= 0 or self.step_bars <= 0:
            raise ValueError("train_bars, test_bars, and step_bars must be positive")
        if self.purge_bars < 0:
            raise ValueError("purge_bars must be >= 0")
        if self.min_train_bars is not None and self.min_train_bars <= 0:
            raise ValueError("min_train_bars must be positive when provided")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "split_kind": self.split_kind,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step_bars,
            "purge_bars": self.purge_bars,
            "min_train_bars": self.min_train_bars,
            "timeframe": self.timeframe,
            "asset_class": self.asset_class,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "metadata": dict(self.metadata),
        }

    @property
    def spec_hash(self) -> str:
        return _stable_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TemporalSplitSpec":
        raw = dict(payload or {})
        return cls(
            split_kind=str(raw.get("split_kind", "walk_forward")),
            train_bars=int(raw.get("train_bars", 1)),
            test_bars=int(raw.get("test_bars", 1)),
            step_bars=int(raw.get("step_bars", raw.get("test_bars", 1))),
            purge_bars=int(raw.get("purge_bars", 0)),
            min_train_bars=raw.get("min_train_bars"),
            timeframe=raw.get("timeframe"),
            asset_class=str(raw.get("asset_class", "crypto")),
            policy_name=str(raw.get("policy_name", "manual")),
            policy_version=str(raw.get("policy_version", "v1")),
            metadata=dict(raw.get("metadata", {})),
        )


@dataclass(frozen=True)
class TemporalSplitManifest:
    """Resolved fold manifest that can be persisted for deterministic replay."""

    spec: TemporalSplitSpec
    n_bars: int
    folds: Tuple[WalkForwardSplit, ...]
    manifest_version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "n_bars": self.n_bars,
            "manifest_version": self.manifest_version,
            "spec_hash": self.spec.spec_hash,
            "folds": [
                {
                    "fold_id": fold.fold_id,
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "test_start": fold.test_start,
                    "test_end": fold.test_end,
                }
                for fold in self.folds
            ],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TemporalSplitManifest":
        raw = dict(payload)
        return cls(
            spec=TemporalSplitSpec.from_dict(raw.get("spec")),
            n_bars=int(raw.get("n_bars", 0)),
            manifest_version=str(raw.get("manifest_version", "v1")),
            folds=tuple(
                WalkForwardSplit(
                    fold_id=int(item["fold_id"]),
                    train_start=int(item["train_start"]),
                    train_end=int(item["train_end"]),
                    test_start=int(item["test_start"]),
                    test_end=int(item["test_end"]),
                )
                for item in raw.get("folds", [])
            ),
        )


def resolve_trendline_auto_split_spec(
    timeframe: str,
    *,
    asset_class: str = "crypto",
    purge_bars: int = 0,
    step_bars: int | None = None,
    min_train_bars: int | None = None,
    policy_version: str = TRENDLINE_AUTO_SPLIT_POLICY_VERSION,
) -> TemporalSplitSpec:
    """Resolve the current trendlines auto-window heuristic into a typed spec."""

    crypto_daily = _BARS_PER_DAY_CRYPTO.get(timeframe, 24)
    scale = _ASSET_CLASS_DAILY_SCALE.get(asset_class, 1.0)
    daily = max(1, int(crypto_daily * scale))

    wf_cfg = _eval_cfg.walk_forward
    train_bars, test_bars = None, None
    
    for threshold, tr_mult, ts_mult in wf_cfg.auto_split_tiers:
        if daily >= threshold:
            train_bars, test_bars = daily * tr_mult, daily * ts_mult
            break
            
    if train_bars is None or test_bars is None:
        train_bars, test_bars = wf_cfg.auto_split_fallback

    return TemporalSplitSpec(
        split_kind="walk_forward",
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars or test_bars,
        purge_bars=purge_bars,
        min_train_bars=min_train_bars or train_bars,
        timeframe=timeframe,
        asset_class=asset_class,
        policy_name=TRENDLINE_AUTO_SPLIT_POLICY,
        policy_version=policy_version,
        metadata={"daily_bars": daily, "crypto_daily_bars": crypto_daily},
    )


def build_temporal_split_manifest(
    n_bars: int,
    spec: TemporalSplitSpec,
) -> TemporalSplitManifest:
    validator = WalkForwardValidator(
        train_bars=spec.train_bars,
        test_bars=spec.test_bars,
        step_bars=spec.step_bars,
        purge_bars=spec.purge_bars,
        min_train_bars=spec.min_train_bars or spec.train_bars,
    )
    return TemporalSplitManifest(
        spec=spec,
        n_bars=n_bars,
        folds=tuple(validator.get_splits(n_bars)),
    )


__all__ = [
    "TRENDLINE_AUTO_SPLIT_POLICY",
    "TRENDLINE_AUTO_SPLIT_POLICY_VERSION",
    "TemporalSplitManifest",
    "TemporalSplitSpec",
    "WalkForwardSplit",
    "WalkForwardValidator",
    "build_temporal_split_manifest",
    "resolve_trendline_auto_split_spec",
]