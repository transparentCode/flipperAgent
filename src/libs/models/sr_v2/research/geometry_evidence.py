"""Bounded, candidate-wise geometry evidence composition.

Only counters, exact fractions, rolling stream digests, and calendar-block
summaries cross this boundary.  Outcome rows are consumed once and are never
retained by the accumulator.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from ..config.schema import TIMEFRAME_DURATIONS
from ..contracts import ZoneSide
from ..domain.identity import canonical_hash, canonical_json
from ..research_lab.episode_evidence import TargetCompilerReceipt, TargetOutcomeRow
from ..research_lab.scientific_compiler import ScientificGroupKey
from .observations import canonical_issuance_calendar_block
from .optimizer import (
    CutoffReactionEvidence,
    GeometryCellEvidence,
    GeometryRankingInput,
    SealedCandidateFamily,
)
from .placebos import FEASIBLE_RANDOM_PRICE_ID

JOINT_BLOCK_DRAW_ALGORITHM = "shared_utc_calendar_blocks@1"
_GLOBAL_GEOMETRY_SCHEMA = "sr_v2.development_global_geometry@1"


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha(value: object, name: str) -> str:
    text = _nonempty(value, name)
    if len(text) != 64:
        raise ValueError(f"{name} must be a SHA-256")
    try:
        int(text, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256") from exc
    return text.lower()


def _source_binding(value: object, name: str) -> tuple[str, str, str, str]:
    if (
        not isinstance(value, tuple)
        or len(value) != 4
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(
            f"{name} must be (instrument_id, source_manifest_id, source_sha256, source_slice_fingerprint)"
        )
    return tuple(value)


@dataclass(slots=True)
class _ClusterCounts:
    lineages: int = 0
    actual_bounce: int = 0
    actual_break: int = 0
    null_bounce: int = 0
    null_break: int = 0


@dataclass(slots=True)
class _BlockSummary:
    first_cutoff: datetime
    cutoffs: int = 0
    clusters: int = 0
    actual_probability_sum: Fraction = Fraction(0, 1)
    null_probability_sum: Fraction = Fraction(0, 1)
    actual_bounce: int = 0
    actual_break: int = 0
    null_bounce: int = 0
    null_break: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class GeometryFamilyEvidence:
    """Complete-family cells with one shared paired-block draw receipt."""

    family_hash: str
    cells_by_candidate: Mapping[str, tuple[GeometryCellEvidence, ...]]
    block_draws: tuple[tuple[str, ...], ...]
    family_size: int
    draw_algorithm: str = JOINT_BLOCK_DRAW_ALGORITHM
    config_fingerprint: str = ""
    draw_seed: str = ""
    confidence: float = 0.0
    repetitions: int = 0
    common_block_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.family_hash, str)
            or len(self.family_hash) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.family_hash
            )
        ):
            raise ValueError("geometry family evidence family_hash must be SHA-256")
        if (
            not isinstance(self.cells_by_candidate, Mapping)
            or not self.cells_by_candidate
        ):
            raise ValueError("geometry family evidence cells are required")
        if (
            isinstance(self.family_size, bool)
            or not isinstance(self.family_size, int)
            or self.family_size <= 0
        ):
            raise ValueError("geometry family evidence family_size must be positive")
        if self.draw_algorithm != JOINT_BLOCK_DRAW_ALGORITHM:
            raise ValueError("unsupported geometry family block draw algorithm")
        if (
            not isinstance(self.config_fingerprint, str)
            or len(self.config_fingerprint) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.config_fingerprint
            )
        ):
            raise ValueError(
                "geometry family evidence config_fingerprint must be SHA-256"
            )
        if not isinstance(self.draw_seed, str) or not self.draw_seed.strip():
            raise ValueError("geometry family evidence draw_seed must be non-empty")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0 < float(self.confidence) < 1
        ):
            raise ValueError("geometry family evidence confidence must be in (0, 1)")
        if (
            isinstance(self.repetitions, bool)
            or not isinstance(self.repetitions, int)
            or self.repetitions <= 0
        ):
            raise ValueError("geometry family evidence repetitions must be positive")
        labels = tuple(self.common_block_labels)
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("geometry family evidence block labels must be non-empty")
        if labels != tuple(sorted(set(labels))):
            raise ValueError("geometry family evidence block labels must be sorted")
        draws = tuple(tuple(item for item in draw) for draw in self.block_draws)
        if any(
            not draw
            or any(not isinstance(block, str) or not block.strip() for block in draw)
            for draw in draws
        ):
            raise ValueError(
                "geometry family evidence draws must contain non-empty blocks"
            )
        if draws and len(draws) != self.repetitions:
            raise ValueError(
                "geometry family evidence draw count differs from repetitions"
            )
        if any(
            len(draw) != len(labels) or any(block not in labels for block in draw)
            for draw in draws
        ):
            raise ValueError("geometry family evidence draw slots differ from labels")
        values: dict[str, tuple[GeometryCellEvidence, ...]] = {}
        for candidate_id, cells in self.cells_by_candidate.items():
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                raise ValueError(
                    "geometry family evidence candidate IDs must be non-empty"
                )
            cells_tuple = tuple(cells)
            if any(not isinstance(cell, GeometryCellEvidence) for cell in cells_tuple):
                raise TypeError("geometry family evidence cells must be typed")
            if any(cell.candidate_id != candidate_id for cell in cells_tuple):
                raise ValueError("geometry family evidence cell candidate mismatch")
            values[candidate_id] = cells_tuple
        object.__setattr__(
            self, "cells_by_candidate", MappingProxyType(dict(sorted(values.items())))
        )
        object.__setattr__(self, "block_draws", draws)
        object.__setattr__(self, "common_block_labels", labels)

    @property
    def receipt_fingerprint(self) -> str:
        """Stable identity of the complete shared-draw adjustment evidence."""

        return canonical_hash(
            {
                "schema": "sr_v2.geometry_family_evidence@1",
                "family_hash": self.family_hash,
                "config_fingerprint": self.config_fingerprint,
                "draw_algorithm": self.draw_algorithm,
                "draw_seed": self.draw_seed,
                "confidence": self.confidence,
                "repetitions": self.repetitions,
                "common_block_labels": self.common_block_labels,
                "block_draws": self.block_draws,
                "family_size": self.family_size,
            }
        )


def _reaction(value: Any) -> str | None:
    reaction = getattr(value, "reaction", None)
    return None if reaction is None else getattr(reaction, "value", reaction)


def _eligible(value: Any) -> bool:
    return bool(
        value is not None
        and getattr(value, "touch", None) is True
        and getattr(value, "reaction_eligible", False)
        and not getattr(value, "censored", False)
        and not getattr(value, "ambiguous", False)
        and _reaction(value) in {"BOUNCE", "BREAK"}
    )


def _validate_strict_geometry_window(config: Any, row: TargetOutcomeRow) -> None:
    """Keep strict geometry observations wholly inside geometry-train."""

    if getattr(config, "schema", None) != _GLOBAL_GEOMETRY_SCHEMA:
        return
    splits = getattr(config, "splits", None)
    window = getattr(splits, "geometry_train", None)
    freeze = getattr(config, "target_freeze", None)
    target_tuple = getattr(freeze, "selected_tuple", None)
    if window is None or target_tuple is None:
        raise TypeError("strict global geometry config lacks train window or target")
    horizon = (
        TIMEFRAME_DURATIONS[row.group.timeframe] * target_tuple.source_horizon_bars
    )
    if row.issuance_cutoff < window.start or row.issuance_cutoff + horizon > window.end:
        raise ValueError("geometry outcome issuance is outside geometry-train window")


class GeometryDiagnosticAccumulator:
    """Consume one candidate's asset-keyed target streams in one pass."""

    def __init__(
        self,
        config: Any,
        family: SealedCandidateFamily,
        candidate_id: str,
        *,
        source_bindings: Mapping[str, tuple[str, str, str, str]],
        target_fingerprints: Mapping[str, str],
        compiler_fingerprints: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(family, SealedCandidateFamily):
            raise TypeError("geometry accumulator family must be SealedCandidateFamily")
        if not isinstance(candidate_id, str) or candidate_id not in {
            item.candidate_id for item in family.candidates
        }:
            raise ValueError("geometry accumulator candidate is not in family")
        if not isinstance(source_bindings, Mapping) or not source_bindings:
            raise ValueError("geometry accumulator source bindings are required")
        self.config = config
        self.family = family
        self.candidate_id = candidate_id
        self.source_bindings = {
            asset: _source_binding(value, f"source_bindings.{asset}")
            for asset, value in sorted(source_bindings.items())
        }
        self.target_fingerprints = dict(sorted(target_fingerprints.items()))
        if not self.target_fingerprints:
            raise ValueError("geometry accumulator target fingerprints are required")
        if compiler_fingerprints is None:
            self.compiler_fingerprints: dict[str, str] = {}
        else:
            self.compiler_fingerprints = {
                asset: _nonempty(value, f"compiler_fingerprints.{asset}")
                for asset, value in sorted(compiler_fingerprints.items())
            }
            if set(self.compiler_fingerprints) != set(self.source_bindings):
                raise ValueError("compiler fingerprints must cover exact assets")
        self._expected_groups = self._groups()
        self._lineage_support: Counter[ScientificGroupKey] = Counter()
        self._touch_count: Counter[ScientificGroupKey] = Counter()
        self._null_available: Counter[ScientificGroupKey] = Counter()
        self._censored: Counter[ScientificGroupKey] = Counter()
        self._ambiguous: Counter[ScientificGroupKey] = Counter()
        self._unresolved: Counter[ScientificGroupKey] = Counter()
        self._cluster_count: Counter[ScientificGroupKey] = Counter()
        self._unique_cutoffs: Counter[ScientificGroupKey] = Counter()
        self._block_summaries: dict[ScientificGroupKey, dict[str, _BlockSummary]] = {
            group: {} for group in self._expected_groups
        }
        self._current_cutoff: datetime | None = None
        self._current_clusters: dict[
            tuple[ScientificGroupKey, str], _ClusterCounts
        ] = {}
        self._row_count = 0
        self._row_digest = hashlib.sha256()
        self._consumed_assets: set[str] = set()
        self._finished = False

    def _groups(self) -> tuple[ScientificGroupKey, ...]:
        baseline = self.config.baseline_config
        return tuple(
            sorted(
                ScientificGroupKey(
                    asset=asset,
                    timeframe=timeframe,
                    kernel_id=kernel.kernel_id,
                    kernel_version=kernel.kernel_version,
                    side=side,
                )
                for asset in self.source_bindings
                for timeframe in baseline.ladder
                for kernel in baseline.kernels
                if kernel.enabled_for(timeframe)
                for side in ZoneSide
            )
        )

    @property
    def row_count(self) -> int:
        return self._row_count

    @property
    def row_sha256(self) -> str:
        return self._row_digest.hexdigest()

    def _block(self, cutoff: datetime) -> str:
        inference = self.config.inference
        return canonical_issuance_calendar_block(
            cutoff,
            block=inference.joint_utc_block,
            epoch=inference.epoch,
        )

    @staticmethod
    def _fraction(numerator: int, denominator: int) -> Fraction:
        if denominator <= 0:
            raise ValueError("reaction support must be positive")
        return Fraction(numerator, denominator)

    def _flush_cutoff(self) -> None:
        if self._current_cutoff is None:
            return
        cutoff = self._current_cutoff
        by_group: dict[ScientificGroupKey, list[_ClusterCounts]] = {}
        for (group, _cluster), counts in self._current_clusters.items():
            by_group.setdefault(group, []).append(counts)
        for group, clusters in by_group.items():
            eligible_clusters = [
                item
                for item in clusters
                if item.actual_bounce + item.actual_break > 0
                and item.null_bounce + item.null_break > 0
            ]
            if not eligible_clusters:
                continue
            actual_sum = sum(
                (
                    self._fraction(
                        item.actual_bounce, item.actual_bounce + item.actual_break
                    )
                    for item in eligible_clusters
                ),
                Fraction(0, 1),
            )
            null_sum = sum(
                (
                    self._fraction(item.null_bounce, item.null_bounce + item.null_break)
                    for item in eligible_clusters
                ),
                Fraction(0, 1),
            )
            block = self._block(cutoff)
            summary = self._block_summaries[group].get(block)
            if summary is None:
                summary = _BlockSummary(first_cutoff=cutoff)
                self._block_summaries[group][block] = summary
            self._unique_cutoffs[group] += 1
            self._cluster_count[group] += len(eligible_clusters)
            summary.cutoffs += 1
            summary.clusters += len(eligible_clusters)
            summary.actual_probability_sum += actual_sum / len(eligible_clusters)
            summary.null_probability_sum += null_sum / len(eligible_clusters)
            summary.actual_bounce += sum(
                item.actual_bounce for item in eligible_clusters
            )
            summary.actual_break += sum(item.actual_break for item in eligible_clusters)
            summary.null_bounce += sum(item.null_bounce for item in eligible_clusters)
            summary.null_break += sum(item.null_break for item in eligible_clusters)
        self._current_cutoff = None
        self._current_clusters.clear()

    def _validate_receipt(self, asset: str, receipt: TargetCompilerReceipt) -> None:
        if not isinstance(receipt, TargetCompilerReceipt):
            raise TypeError("geometry stream receipt must be TargetCompilerReceipt")
        binding = self.source_bindings.get(asset)
        if binding is None:
            raise ValueError(f"geometry stream has unexpected asset: {asset}")
        if receipt.asset != asset:
            raise ValueError("geometry compiler receipt asset differs from stream")
        if (
            receipt.source_manifest_id != binding[1]
            or receipt.source_sha256 != binding[2]
            or receipt.source_slice_fingerprint != binding[3]
        ):
            raise ValueError(f"geometry compiler source identity differs for {asset}")
        if receipt.null_algorithm != FEASIBLE_RANDOM_PRICE_ID:
            raise ValueError("geometry compiler null algorithm is unsupported")
        expected_compiler = self.compiler_fingerprints.get(asset)
        if (
            expected_compiler is not None
            and receipt.compiler_fingerprint != expected_compiler
        ):
            raise ValueError(f"geometry compiler fingerprint differs for {asset}")
        receipt_targets = dict(receipt.target_fingerprints)
        if receipt_targets != self.target_fingerprints:
            raise ValueError(f"geometry target fingerprints differ for {asset}")

    def consume(
        self,
        asset: str,
        receipt: TargetCompilerReceipt,
        rows: Iterable[TargetOutcomeRow],
    ) -> None:
        if self._finished:
            raise RuntimeError("geometry accumulator is already finalized")
        if asset in self._consumed_assets:
            raise ValueError(f"geometry asset was consumed twice: {asset}")
        self._validate_receipt(asset, receipt)
        self._consumed_assets.add(asset)
        expected_groups = {
            group for group in self._expected_groups if group.asset == asset
        }
        stream_count = 0
        stream_digest = hashlib.sha256()
        previous_row_key: tuple[datetime, str] | None = None
        for row in rows:
            if not isinstance(row, TargetOutcomeRow):
                raise TypeError("geometry rows must contain TargetOutcomeRow values")
            if row.group not in expected_groups:
                raise ValueError(
                    "geometry row group is outside the exact asset ontology"
                )
            _validate_strict_geometry_window(self.config, row)
            row_key = (row.issuance_cutoff, row.observation_id)
            if previous_row_key is not None and row_key < previous_row_key:
                raise ValueError(
                    "geometry rows must be ordered by issuance cutoff and observation identity"
                )
            previous_row_key = row_key
            if (
                self._current_cutoff is not None
                and row.issuance_cutoff != self._current_cutoff
            ):
                self._flush_cutoff()
            if self._current_cutoff is None:
                self._current_cutoff = row.issuance_cutoff
            if (
                self.target_fingerprints.get(row.group.timeframe)
                != row.target_fingerprint
            ):
                raise ValueError(
                    "geometry row target fingerprint differs from frozen target"
                )
            self._row_count += 1
            encoded = canonical_json(row.to_mapping()).encode("utf-8")
            stream_digest.update(len(encoded).to_bytes(8, "big"))
            stream_digest.update(encoded)
            stream_count += 1
            group = row.group
            self._lineage_support[group] += 1
            if row.actual.touch is True:
                self._touch_count[group] += 1
            if row.null_available:
                self._null_available[group] += 1
            if row.actual.censored or (row.null is not None and row.null.censored):
                self._censored[group] += 1
            if row.actual.ambiguous or (row.null is not None and row.null.ambiguous):
                self._ambiguous[group] += 1
            if (
                row.actual.touch is True
                and not row.actual.censored
                and not row.actual.ambiguous
                and not row.actual.reaction_eligible
            ) or (
                row.null is not None
                and row.null.touch is True
                and not row.null.censored
                and not row.null.ambiguous
                and not row.null.reaction_eligible
            ):
                self._unresolved[group] += 1
            key = (group, row.cluster_identity)
            cluster = self._current_clusters.setdefault(key, _ClusterCounts())
            cluster.lineages += 1
            if _eligible(row.actual) and _eligible(row.null):
                if _reaction(row.actual) == "BOUNCE":
                    cluster.actual_bounce += 1
                else:
                    cluster.actual_break += 1
                if _reaction(row.null) == "BOUNCE":
                    cluster.null_bounce += 1
                else:
                    cluster.null_break += 1
        self._flush_cutoff()
        self._row_digest.update(
            canonical_json((asset, stream_count, stream_digest.hexdigest())).encode(
                "utf-8"
            )
        )
        if (
            stream_count != receipt.expected_row_count
            or stream_digest.hexdigest() != receipt.expected_row_sha256
        ):
            raise ValueError(
                f"geometry row stream differs from compiler receipt for {asset}"
            )

    def finalize(self) -> tuple[GeometryCellEvidence, ...]:
        if self._finished:
            raise RuntimeError("geometry accumulator is already finalized")
        self._finished = True
        if self._consumed_assets != set(self.source_bindings):
            missing = sorted(set(self.source_bindings) - self._consumed_assets)
            raise ValueError(f"geometry streams are missing assets: {missing}")
        cells: list[GeometryCellEvidence] = []
        for group in self._expected_groups:
            summaries = self._block_summaries[group]
            evidence: list[CutoffReactionEvidence] = []
            for block, summary in sorted(summaries.items()):
                actual_mean = summary.actual_probability_sum / summary.cutoffs
                null_mean = summary.null_probability_sum / summary.cutoffs
                evidence.append(
                    CutoffReactionEvidence(
                        cutoff=summary.first_cutoff,
                        actual_bounce=summary.actual_bounce,
                        actual_break=summary.actual_break,
                        null_bounce=summary.null_bounce,
                        null_break=summary.null_break,
                        actual_probability_numerator=actual_mean.numerator,
                        actual_probability_denominator=actual_mean.denominator,
                        null_probability_numerator=null_mean.numerator,
                        null_probability_denominator=null_mean.denominator,
                        cutoff_weight=summary.cutoffs,
                    )
                )
            asset_binding = self.source_bindings[group.asset]
            cells.append(
                GeometryCellEvidence(
                    candidate_id=self.candidate_id,
                    group=group,
                    source_manifest_id=asset_binding[1],
                    source_sha256=asset_binding[2],
                    source_slice_fingerprint=asset_binding[3],
                    target_fingerprint=self.target_fingerprints[group.timeframe],
                    compiler_fingerprint=self.compiler_fingerprints.get(
                        group.asset,
                        "derived-from-receipt",
                    ),
                    null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
                    lineage_support=self._lineage_support[group],
                    cutoff_evidence=tuple(evidence),
                    touch_count=self._touch_count[group],
                    unique_cutoff_count=self._unique_cutoffs[group],
                    cluster_count=self._cluster_count[group],
                    null_available_count=self._null_available[group],
                    joint_utc_block_count=len(summaries),
                    censored_count=self._censored[group],
                    ambiguous_count=self._ambiguous[group],
                    unresolved_reaction_count=self._unresolved[group],
                )
            )
        return tuple(cells)


def compose_geometry_evidence(
    config: Any,
    family: SealedCandidateFamily,
    candidate_id: str,
    streams: Mapping[str, tuple[TargetCompilerReceipt, Iterable[TargetOutcomeRow]]],
    *,
    source_bindings: Mapping[str, tuple[str, str, str, str]],
    target_fingerprints: Mapping[str, str],
    compiler_fingerprints: Mapping[str, str] | None = None,
) -> tuple[GeometryCellEvidence, ...]:
    """Compose one candidate's asset-keyed target rows without row retention."""

    if not isinstance(streams, Mapping) or set(streams) != set(source_bindings):
        raise ValueError("geometry streams must cover exact source assets")
    expected_compilers = (
        None if compiler_fingerprints is None else dict(compiler_fingerprints)
    )
    accumulator = GeometryDiagnosticAccumulator(
        config,
        family,
        candidate_id,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=expected_compilers,
    )
    for asset in sorted(streams):
        value = streams[asset]
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValueError("geometry stream values must be (receipt, rows) tuples")
        receipt, rows = value
        if expected_compilers is None:
            if not isinstance(receipt, TargetCompilerReceipt):
                raise TypeError("geometry stream receipt must be TargetCompilerReceipt")
            accumulator.compiler_fingerprints[asset] = receipt.compiler_fingerprint
        accumulator.consume(asset, receipt, rows)
    return accumulator.finalize()


def joint_utc_block_draw(
    blocks: Iterable[str], *, repetitions: int, seed: str
) -> tuple[tuple[str, ...], ...]:
    """Draw one shared calendar-block sequence, preserving repeated slots."""

    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or repetitions <= 0
    ):
        raise ValueError("repetitions must be a positive integer")
    seed_text = _nonempty(seed, "seed")
    labels = tuple(sorted({_nonempty(item, "calendar block") for item in blocks}))
    if len(labels) <= 1:
        return ()
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16))
    return tuple(
        tuple(labels[rng.randrange(len(labels))] for _ in labels)
        for _ in range(repetitions)
    )


def paired_reaction_lift_interval(
    candidate_by_block: Mapping[str, float],
    baseline_by_block: Mapping[str, float],
    *,
    repetitions: int,
    seed: str,
    confidence: float,
    family_size: int,
) -> tuple[float, float] | None:
    """Return the exact Bonferroni-adjusted paired block interval."""

    if (
        isinstance(family_size, bool)
        or not isinstance(family_size, int)
        or family_size <= 0
    ):
        raise ValueError("family_size must be a positive integer")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 < float(confidence) < 1
    ):
        raise ValueError("confidence must be in (0, 1)")
    common = tuple(sorted(set(candidate_by_block) & set(baseline_by_block)))
    if len(common) <= 1:
        return None
    if set(candidate_by_block) != set(common) or set(baseline_by_block) != set(common):
        raise ValueError("paired block maps must contain exact common blocks")
    if any(
        not math.isfinite(float(candidate_by_block[item]))
        or not math.isfinite(float(baseline_by_block[item]))
        for item in common
    ):
        raise ValueError("paired block values must be finite")
    draws = joint_utc_block_draw(common, repetitions=repetitions, seed=seed)
    if not draws:
        return None
    samples = [
        sum(
            float(candidate_by_block[item]) - float(baseline_by_block[item])
            for item in slots
        )
        / len(slots)
        for slots in draws
    ]
    samples.sort()
    alpha = (1.0 - float(confidence)) / family_size
    lower = max(0, min(len(samples) - 1, math.floor((alpha / 2.0) * len(samples))))
    upper = max(
        0, min(len(samples) - 1, math.ceil((1.0 - alpha / 2.0) * len(samples)) - 1)
    )
    return samples[lower], samples[upper]


def _interval_from_shared_draws(
    candidate_by_block: Mapping[str, float],
    baseline_by_block: Mapping[str, float],
    draws: tuple[tuple[str, ...], ...],
    *,
    confidence: float,
    family_size: int,
) -> tuple[float, float] | None:
    if not draws:
        return None
    common = set(candidate_by_block) & set(baseline_by_block)
    if any(set(slots) - common for slots in draws):
        raise ValueError("shared block draw contains a block without paired evidence")
    samples = [
        sum(
            float(candidate_by_block[item]) - float(baseline_by_block[item])
            for item in slots
        )
        / len(slots)
        for slots in draws
    ]
    samples.sort()
    alpha = (1.0 - float(confidence)) / family_size
    lower = max(0, min(len(samples) - 1, math.floor((alpha / 2.0) * len(samples))))
    upper = max(
        0, min(len(samples) - 1, math.ceil((1.0 - alpha / 2.0) * len(samples)) - 1)
    )
    return samples[lower], samples[upper]


def compose_geometry_family_evidence(
    config: Any,
    family: SealedCandidateFamily,
    streams_by_candidate: Mapping[
        str, Mapping[str, tuple[TargetCompilerReceipt, Iterable[TargetOutcomeRow]]]
    ],
    *,
    source_bindings: Mapping[str, tuple[str, str, str, str]],
    target_fingerprints: Mapping[str, str],
    compiler_fingerprints: Mapping[str, Mapping[str, str]],
) -> GeometryFamilyEvidence:
    """Compose all candidates while retaining only cells and shared draws.

    Candidate streams are consumed in sealed ordinal order.  The returned
    interval metadata is attached after a single block draw for the complete
    family, so every asset/cell shares the same resampling slots.
    """

    if not isinstance(family, SealedCandidateFamily):
        raise TypeError("geometry family must be SealedCandidateFamily")
    candidate_ids = tuple(candidate.candidate_id for candidate in family.candidates)
    if not isinstance(streams_by_candidate, Mapping) or set(
        streams_by_candidate
    ) != set(candidate_ids):
        raise ValueError(
            "geometry family streams must cover the exact candidate family"
        )
    if not isinstance(compiler_fingerprints, Mapping) or set(
        compiler_fingerprints
    ) != set(candidate_ids):
        raise ValueError(
            "geometry family compiler fingerprints must cover exact candidates"
        )
    cells_by_candidate: dict[str, tuple[GeometryCellEvidence, ...]] = {}
    for candidate in family.candidates:
        candidate_id = candidate.candidate_id
        compiler_map = compiler_fingerprints[candidate_id]
        if not isinstance(compiler_map, Mapping) or set(compiler_map) != set(
            source_bindings
        ):
            raise ValueError(
                "geometry family compiler fingerprints must cover exact assets"
            )
        cells_by_candidate[candidate_id] = compose_geometry_evidence(
            config,
            family,
            candidate_id,
            streams_by_candidate[candidate_id],
            source_bindings=source_bindings,
            target_fingerprints=target_fingerprints,
            compiler_fingerprints=compiler_map,
        )

    baseline_cells = cells_by_candidate[family.baseline.candidate_id]
    expected_cell_count = len(baseline_cells)
    if expected_cell_count <= 0:
        raise ValueError("geometry family requires at least one expected cell")
    by_candidate_group = {
        candidate_id: {cell.group: cell for cell in cells}
        for candidate_id, cells in cells_by_candidate.items()
    }
    common_blocks: set[str] | None = None
    block_maps: dict[tuple[str, ScientificGroupKey, str], dict[str, float]] = {}
    baseline_id = family.baseline.candidate_id
    for candidate_id, groups in by_candidate_group.items():
        if candidate_id == baseline_id:
            continue
        for group, cell in groups.items():
            baseline = by_candidate_group[baseline_id].get(group)
            if baseline is None:
                raise ValueError("geometry family baseline is missing a paired cell")
            baseline_values = {
                canonical_issuance_calendar_block(
                    item.cutoff,
                    block=config.inference.joint_utc_block,
                    epoch=config.inference.epoch,
                ): item.reaction_lift
                for item in baseline.cutoff_evidence
            }
            candidate_values = {
                canonical_issuance_calendar_block(
                    item.cutoff,
                    block=config.inference.joint_utc_block,
                    epoch=config.inference.epoch,
                ): item.reaction_lift
                for item in cell.cutoff_evidence
            }
            paired = set(baseline_values) & set(candidate_values)
            common_blocks = paired if common_blocks is None else common_blocks & paired
            block_maps[(candidate_id, group, "candidate")] = candidate_values
            block_maps[(candidate_id, group, "baseline")] = baseline_values
    labels = tuple(sorted(common_blocks or ()))
    minimum_blocks = getattr(config.inference, "minimum_common_joint_utc_blocks", None)
    if minimum_blocks is None:
        minimum_blocks = getattr(config.inference, "minimum_joint_utc_blocks", 1)
    draws = (
        joint_utc_block_draw(
            labels,
            repetitions=config.inference.repetitions,
            seed=getattr(config.search, "seed", "geometry"),
        )
        if len(labels) >= minimum_blocks
        else ()
    )
    family_size = geometry_family_size(family, expected_cell_count)
    adjusted: dict[str, tuple[GeometryCellEvidence, ...]] = {}
    for candidate_id, cells in cells_by_candidate.items():
        if candidate_id == baseline_id:
            adjusted[candidate_id] = cells
            continue
        updated: list[GeometryCellEvidence] = []
        for cell in cells:
            candidate_values = block_maps[(candidate_id, cell.group, "candidate")]
            baseline_values = block_maps[(candidate_id, cell.group, "baseline")]
            interval = _interval_from_shared_draws(
                candidate_values,
                baseline_values,
                draws,
                confidence=config.inference.confidence,
                family_size=family_size,
            )
            updated.append(replace(cell, paired_reaction_lift_interval=interval))
        adjusted[candidate_id] = tuple(updated)
    return GeometryFamilyEvidence(
        family_hash=family.family_hash,
        cells_by_candidate=adjusted,
        block_draws=draws,
        family_size=family_size,
        config_fingerprint=config.config_fingerprint,
        draw_seed=config.search.seed,
        confidence=config.inference.confidence,
        repetitions=config.inference.repetitions,
        common_block_labels=labels,
    )


def geometry_ranking_input_from_family_evidence(
    config: Any,
    family: SealedCandidateFamily,
    evidence: GeometryFamilyEvidence,
    *,
    source_bindings: Mapping[str, tuple[str, str, str, str]],
    target_fingerprints: Mapping[str, str],
    compiler_fingerprints: Mapping[str, Mapping[str, str]],
) -> GeometryRankingInput:
    """Bind one authenticated family receipt to the ranking boundary."""

    if not isinstance(family, SealedCandidateFamily):
        raise TypeError("geometry family must be SealedCandidateFamily")
    if not isinstance(evidence, GeometryFamilyEvidence):
        raise TypeError("geometry evidence must be GeometryFamilyEvidence")
    if not hasattr(config, "config_fingerprint"):
        raise TypeError("geometry ranking config must expose config_fingerprint")
    if evidence.config_fingerprint != config.config_fingerprint:
        raise ValueError("geometry family evidence config differs from ranking config")
    if evidence.draw_seed != config.search.seed:
        raise ValueError("geometry family evidence seed differs from ranking config")
    if evidence.confidence != config.inference.confidence:
        raise ValueError(
            "geometry family evidence confidence differs from ranking config"
        )
    if evidence.repetitions != config.inference.repetitions:
        raise ValueError(
            "geometry family evidence repetitions differ from ranking config"
        )
    if evidence.family_hash != family.family_hash:
        raise ValueError("geometry family evidence hash differs from family")
    candidate_ids = tuple(candidate.candidate_id for candidate in family.candidates)
    if set(evidence.cells_by_candidate) != set(candidate_ids):
        raise ValueError("geometry family evidence must cover exact candidate family")
    cells = tuple(
        cell
        for candidate_id in candidate_ids
        for cell in evidence.cells_by_candidate[candidate_id]
    )
    return GeometryRankingInput(
        family=family,
        cells=cells,
        source_bindings=source_bindings,
        target_fingerprints=target_fingerprints,
        compiler_fingerprints=compiler_fingerprints,
        null_algorithm_id=FEASIBLE_RANDOM_PRICE_ID,
        family_evidence_receipt_fingerprint=evidence.receipt_fingerprint,
        family_common_joint_utc_block_count=len(evidence.common_block_labels),
    )


def geometry_family_size(
    family: SealedCandidateFamily, expected_cell_count: int
) -> int:
    if not isinstance(family, SealedCandidateFamily):
        raise TypeError("family must be SealedCandidateFamily")
    if (
        isinstance(expected_cell_count, bool)
        or not isinstance(expected_cell_count, int)
        or expected_cell_count <= 0
    ):
        raise ValueError("expected_cell_count must be positive")
    return max(1, (len(family.candidates) - 1) * expected_cell_count)


__all__ = [
    "JOINT_BLOCK_DRAW_ALGORITHM",
    "GeometryDiagnosticAccumulator",
    "GeometryFamilyEvidence",
    "compose_geometry_evidence",
    "compose_geometry_family_evidence",
    "geometry_family_size",
    "geometry_ranking_input_from_family_evidence",
    "joint_utc_block_draw",
    "paired_reaction_lift_interval",
]
