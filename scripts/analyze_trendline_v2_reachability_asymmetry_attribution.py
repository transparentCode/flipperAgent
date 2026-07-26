"""Attribute causal R4 reachability asymmetry without reading outcomes.

R5 consumes only the three verified R4 bundle members after invoking the R4
source verifier. It never imports R4 analysis builders or reads temporal/raw
sources directly. Canonical execution is guarded and intentionally not run by
this implementation task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.analyze_trendline_v2_causal_structural_reachability import (
    verify_reachability_bundle,
)


R4_ROOT = Path(
    "/tmp/trendline_v2_phase11r4_causal_structural_reachability/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r5_reachability_asymmetry_attribution/20260522_20260701"
)
EXECUTION_GUARD = "TRENDLINE_V2_ALLOW_PHASE11R5_STUDY"

R4_DIAGNOSTIC_ID = (
    "f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2"
)
R4_MANIFEST_ID = (
    "965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e"
)
R4_INVENTORY = (
    "7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c"
)

R4_MEMBER_PATHS = (
    "manifest.json",
    "reachability_diagnostic.json",
    "source_binding.json",
)
R5_MEMBER_PATHS = (
    "reachability_asymmetry_attribution.json",
    "source_binding.json",
)
R5_SCHEMA = "trendline_v2_phase11r5_reachability_asymmetry_attribution_v1"
R5_SOURCE_BINDING_SCHEMA = "trendline_v2_phase11r5_source_binding_v1"
R5_MANIFEST_SCHEMA = "trendline_v2_phase11r5_manifest_v1"
R5_DIAGNOSTIC_NAMESPACE = "trendline_v2_phase11r5_attribution"
R5_SOURCE_BINDING_NAMESPACE = "trendline_v2_phase11r5_source_binding"
R5_MANIFEST_NAMESPACE = "trendline_v2_phase11r5_manifest"
R5_INCONSISTENCY_NAMESPACE = "trendline_v2_phase11r5_global_inconsistency"

EXPECTED_COMPARISON_COUNT = 51
EXPECTED_CELL_COUNT = 117
EXPECTED_CONTENDER_ONLY = 25
EXPECTED_CONTROL_ONLY = 92
ROLES = ("support", "resistance")
BUDGETS = (1, 2, 3)
PRIMARY_THRESHOLD_ATR = 8.0
PRIMARY_HORIZON_HOURS = 96
PRIMARY_CLASSES = {"contender_only", "control_only"}
ATTRIBUTION_CLASSES = {
    "FULL_LINEAGE_SUBSTITUTION",
    "PARTIAL_LINEAGE_SUBSTITUTION",
    "SHARED_LINEAGE_REACHABILITY_INCONSISTENCY",
    "UNATTRIBUTED_ONE_SIDED_CELL",
}
COMPLETE_ATTRIBUTION_CLASSES = {
    "FULL_LINEAGE_SUBSTITUTION",
    "PARTIAL_LINEAGE_SUBSTITUTION",
}
CROSS_BUDGET_CLASSES = {
    "STRICT_BUDGET_RESCUE",
    "NON_NESTED_HIGHER_BUDGET_PAIRING",
    "PERSISTENT_THROUGH_BUDGET_3",
}


class ReachabilityAsymmetryError(ValueError):
    """Expected R5 contract, source, or publication failure."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _canonical_json(value: Any) -> str:
    return _canonical_bytes(value).decode("utf-8").rstrip("\n")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(namespace: str, value: Any) -> str:
    return _sha256_bytes(f"{namespace}:".encode() + _canonical_json(value).encode())


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReachabilityAsymmetryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReachabilityAsymmetryError(f"non-finite JSON value: {value}")


def _read_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReachabilityAsymmetryError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReachabilityAsymmetryError(f"JSON object required: {path}")
    if raw != _canonical_bytes(value):
        raise ReachabilityAsymmetryError(f"non-canonical JSON: {path}")
    return value


def _safe_relative_path(path: str) -> bool:
    candidate = Path(path)
    return (
        path == candidate.as_posix()
        and not candidate.is_absolute()
        and ".." not in candidate.parts
        and path not in {"", "."}
    )


def _artifact_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir():
        raise ReachabilityAsymmetryError(f"bundle root missing: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not _safe_relative_path(relative):
            raise ReachabilityAsymmetryError("unsafe bundle member path")
        entries.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(entries)


def _inventory_sha256(members: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(members)))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _r4_source(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify R4 first, then read only its three frozen bundle files."""
    result = verify_reachability_bundle(root, source_backed=True)
    if (
        result.get("diagnostic_id") != R4_DIAGNOSTIC_ID
        or result.get("manifest_id") != R4_MANIFEST_ID
        or result.get("output_inventory_sha256") != R4_INVENTORY
        or result.get("member_count") != 2
    ):
        raise ReachabilityAsymmetryError("R4 frozen identity mismatch")
    diagnostic = _read_canonical_json(root / "reachability_diagnostic.json")
    source_binding = _read_canonical_json(root / "source_binding.json")
    manifest = _read_canonical_json(root / "manifest.json")
    if diagnostic.get("diagnostic_id") != R4_DIAGNOSTIC_ID:
        raise ReachabilityAsymmetryError("R4 diagnostic identity mismatch")
    if manifest.get("manifest_id") != R4_MANIFEST_ID:
        raise ReachabilityAsymmetryError("R4 manifest identity mismatch")
    if diagnostic.get("source_binding") != source_binding:
        raise ReachabilityAsymmetryError("R4 source binding mismatch")
    return {"diagnostic": diagnostic, "source_binding": source_binding, "manifest": manifest}, result


def _source_binding_payload(
    source: Mapping[str, Any],
    verification: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    source_binding = source["source_binding"]
    payload = {
        "schema_version": R5_SOURCE_BINDING_SCHEMA,
        "r4_root": str(root),
        "r4_diagnostic_id": verification["diagnostic_id"],
        "r4_manifest_id": verification["manifest_id"],
        "r4_inventory": verification["output_inventory_sha256"],
        "r4_source_binding_id": source_binding.get("source_binding_id"),
        "r4_source_before": source_binding.get("source_before"),
        "r4_source_after": source_binding.get("source_after"),
    }
    payload["source_binding_id"] = _identity_hash(
        R5_SOURCE_BINDING_NAMESPACE,
        payload,
    )
    return payload


def _cell_key(
    comparison: Mapping[str, Any], cell: Mapping[str, Any]
) -> tuple[str, int, str, str, int, str, int]:
    namespace = comparison.get("population_namespace")
    if not isinstance(namespace, list) or len(namespace) != 5:
        raise ReachabilityAsymmetryError("invalid R4 comparison namespace")
    if namespace[2] != "matched_control":
        raise ReachabilityAsymmetryError("R4 comparison is not matched-control")
    checkpoint = cell.get("checkpoint_index")
    role = cell.get("role")
    if not isinstance(checkpoint, int) or checkpoint < 1:
        raise ReachabilityAsymmetryError("invalid R4 checkpoint")
    if role not in ROLES:
        raise ReachabilityAsymmetryError("invalid R4 role")
    budget = namespace[1]
    if not isinstance(budget, int) or budget not in BUDGETS:
        raise ReachabilityAsymmetryError("invalid R4 budget")
    return (
        str(namespace[0]),
        budget,
        str(namespace[3]),
        str(namespace[4]),
        checkpoint,
        str(role),
        PRIMARY_HORIZON_HOURS,
    )


def _sort_identity(identity: Sequence[Any]) -> tuple[Any, ...]:
    """Preserve typed identity fields while sorting deterministic records."""
    if len(identity) == 8:
        return tuple("" if value is None else value for value in identity)
    return tuple(identity)


def _line_identity(row: Mapping[str, Any]) -> tuple[str, int, str, str]:
    dataset = row.get("dataset_id")
    checkpoint = row.get("checkpoint_index")
    role = row.get("semantic_role_at_selection")
    lineage = row.get("lineage_id")
    if not isinstance(dataset, str) or not isinstance(checkpoint, int):
        raise ReachabilityAsymmetryError("malformed selected-line identity")
    if role not in ROLES or not isinstance(lineage, str) or not lineage:
        raise ReachabilityAsymmetryError("malformed selected-line identity")
    return dataset, checkpoint, role, lineage


def _row_namespace(row: Mapping[str, Any]) -> tuple[str, int, str, str | None, str]:
    namespace = row.get("population_namespace")
    if isinstance(namespace, list) and len(namespace) == 5:
        try:
            budget = int(namespace[1])
        except (TypeError, ValueError) as exc:
            raise ReachabilityAsymmetryError("malformed population namespace") from exc
        return (
            str(namespace[0]),
            budget,
            str(namespace[2]),
            None if namespace[3] is None else str(namespace[3]),
            str(namespace[4]),
        )
    try:
        budget = int(row.get("budget_per_role"))
    except (TypeError, ValueError) as exc:
        raise ReachabilityAsymmetryError("malformed population namespace") from exc
    return (
        str(row.get("contender_policy_id")),
        budget,
        str(row.get("derivation_type")),
        row.get("control_policy_id_or_null"),
        str(row.get("dataset_id")),
    )


def _row_matches(row: Mapping[str, Any], cell: tuple[str, int, str, str, int, str, int], *, control: bool) -> bool:
    namespace = _row_namespace(row)
    return (
        namespace[0] == cell[0]
        and namespace[1] == cell[1]
        and namespace[2] == ("matched_control" if control else "contender")
        and namespace[3] == (cell[2] if control else None)
        and namespace[4] == cell[3]
        and row.get("checkpoint_index") == cell[4]
        and row.get("semantic_role_at_selection") == cell[5]
    )


def _numeric(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReachabilityAsymmetryError(f"invalid numeric field: {field}")
    result = float(value)
    if not math.isfinite(result):
        raise ReachabilityAsymmetryError(f"non-finite numeric field: {field}")
    return result


def _reachable(row: Mapping[str, Any]) -> bool:
    if row.get("geometry_evaluable") is not True:
        return False
    distance = row.get("geometry_projected_distance_atr_96h")
    if distance is None:
        return False
    return _numeric(distance, "geometry_projected_distance_atr_96h") <= PRIMARY_THRESHOLD_ATR


def _feature_signature(row: Mapping[str, Any]) -> tuple[str, Any, Any, bool]:
    geometry = row.get("fixed_geometry")
    if not isinstance(geometry, Mapping):
        raise ReachabilityAsymmetryError("selected line geometry missing")
    initial = row.get("initial_distance_atr")
    projected = row.get("geometry_projected_distance_atr_96h")
    if initial is not None:
        _numeric(initial, "initial_distance_atr")
    if projected is not None:
        _numeric(projected, "geometry_projected_distance_atr_96h")
    return (
        _canonical_json(geometry),
        initial,
        projected,
        _reachable(row),
    )


def _global_feature_consistency(
    feature_rows: Sequence[Mapping[str, Any]],
    source_cells: Mapping[tuple[str, int, str, str, int, str, int], Mapping[str, Any]],
) -> tuple[dict[tuple[str, int, str, str], dict[str, Any]], list[str]]:
    occurrences: dict[tuple[str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    errors: list[str] = []
    for row in feature_rows:
        try:
            identity = _line_identity(row)
            signature = _feature_signature(row)
            occurrences[identity].append(
                {"namespace": list(_row_namespace(row)), "signature": signature}
            )
        except ReachabilityAsymmetryError as exc:
            errors.append(str(exc))
    records: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for identity, unsorted_rows in occurrences.items():
        rows = sorted(unsorted_rows, key=_canonical_json)
        signatures = { _canonical_json(item["signature"]) for item in rows }
        namespaces = [item["namespace"] for item in rows]
        if len(namespaces) != len({ _canonical_json(item) for item in namespaces }):
            errors.append(f"duplicate feature identity: {identity}")
        if len(signatures) > 1:
            affected = [
                list(key)
                for key in source_cells
                if identity in _cell_line_identities(key, feature_rows)
            ]
            record = {
                "selected_line_identity": list(identity),
                "occurrences": rows,
                "affected_cell_identities": sorted(affected, key=_sort_identity),
                "reason": "feature_signature_mismatch",
            }
            records[identity] = {
                **record,
                "global_inconsistency_id": _identity_hash(
                    R5_INCONSISTENCY_NAMESPACE,
                    record,
                ),
            }
    return records, sorted(errors)


def _cell_line_identities(
    cell: tuple[str, int, str, str, int, str, int],
    feature_rows: Sequence[Mapping[str, Any]],
) -> set[tuple[str, int, str, str]]:
    result: set[tuple[str, int, str, str]] = set()
    for row in feature_rows:
        try:
            identity = _line_identity(row)
        except ReachabilityAsymmetryError:
            continue
        if _row_matches(row, cell, control=False) or _row_matches(row, cell, control=True):
            result.add(identity)
    return result


def _comparison_records(
    diagnostic: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, int, str, str, int, str, int], dict[str, Any]],
    list[str],
]:
    comparisons = diagnostic.get("comparisons")
    if not isinstance(comparisons, list):
        raise ReachabilityAsymmetryError("R4 comparisons missing")
    one_sided = [
        item
        for item in comparisons
        if isinstance(item, Mapping)
        and (
            int(item.get("contender_only_cells", 0)) > 0
            or int(item.get("control_only_cells", 0)) > 0
        )
    ]
    errors: list[str] = []
    if len(one_sided) != EXPECTED_COMPARISON_COUNT:
        errors.append("one-sided comparison count mismatch")
    index: dict[tuple[str, int, str, str, int, str, int], dict[str, Any]] = {}
    extracted: list[dict[str, Any]] = []
    for comparison in comparisons:
        if not isinstance(comparison, Mapping):
            errors.append("comparison is not an object")
            continue
        comparison_is_one_sided = (
            int(comparison.get("contender_only_cells", 0)) > 0
            or int(comparison.get("control_only_cells", 0)) > 0
        )
        cells = comparison.get("cells")
        if not isinstance(cells, list):
            errors.append("comparison cells missing")
            continue
        for cell in cells:
            if not isinstance(cell, Mapping):
                errors.append("cell is not an object")
                continue
            try:
                key = _cell_key(comparison, cell)
            except ReachabilityAsymmetryError as exc:
                errors.append(str(exc))
                continue
            if key in index:
                errors.append(f"duplicate cell identity: {key}")
                continue
            primary = cell.get("primary_stratum_class")
            terminal = cell.get("terminal_cell_class")
            reconciliation = cell.get("reconciliation_errors")
            record = {
                "key": key,
                "comparison": comparison,
                "cell": cell,
                "primary_stratum_class": primary,
                "terminal_cell_class": terminal,
                "reconciliation_errors": reconciliation,
            }
            index[key] = record
            if comparison_is_one_sided and primary in PRIMARY_CLASSES:
                if terminal != primary or reconciliation != []:
                    errors.append(f"invalid extracted cell: {key}")
                else:
                    extracted.append(record)
        if comparison_is_one_sided:
            primary_counts = Counter(
                cell.get("primary_stratum_class")
                for cell in cells
                if isinstance(cell, Mapping)
            )
            for label in PRIMARY_CLASSES:
                if primary_counts[label] != int(comparison.get(f"{label}_cells", 0)):
                    errors.append(f"comparison {label} count mismatch")
    actual_contender = sum(
        record["primary_stratum_class"] == "contender_only" for record in extracted
    )
    actual_control = sum(
        record["primary_stratum_class"] == "control_only" for record in extracted
    )
    if len(extracted) != EXPECTED_CELL_COUNT:
        errors.append("one-sided cell count mismatch")
    if actual_contender != EXPECTED_CONTENDER_ONLY:
        errors.append("contender-only cell count mismatch")
    if actual_control != EXPECTED_CONTROL_ONLY:
        errors.append("control-only cell count mismatch")
    return extracted, index, sorted(set(errors))


def _relevant_source_keys(
    extracted: Sequence[Mapping[str, Any]],
    source_index: Mapping[tuple[str, int, str, str, int, str, int], Mapping[str, Any]],
) -> set[tuple[str, int, str, str, int, str, int]]:
    """Return source cells used by primary and cross-budget attribution."""
    relevant = {tuple(record["key"]) for record in extracted}
    for record in extracted:
        key = tuple(record["key"])
        if key[1] == 3:
            continue
        for candidate_budget in range(key[1] + 1, 4):
            candidate_key = (
                key[0],
                candidate_budget,
                key[2],
                key[3],
                key[4],
                key[5],
                key[6],
            )
            source = source_index.get(candidate_key)
            if source is None:
                continue
            relevant.add(candidate_key)
            if (
                source.get("primary_stratum_class") == "paired"
                and source.get("terminal_cell_class") == "paired"
                and source.get("reconciliation_errors") == []
            ):
                break
    return relevant


def _relevant_feature_rows(
    feature_rows: Sequence[Mapping[str, Any]],
    source_keys: set[tuple[str, int, str, str, int, str, int]],
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for row in feature_rows:
        if any(
            _row_matches(row, key, control=control)
            for key in source_keys
            for control in (False, True)
        ):
            rows.append(row)
    return rows


def _side_rows(
    feature_rows: Sequence[Mapping[str, Any]],
    key: tuple[str, int, str, str, int, str, int],
    *,
    control: bool,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    rows = [row for row in feature_rows if _row_matches(row, key, control=control)]
    errors: list[str] = []
    identities: list[tuple[str, int, str, str]] = []
    for row in rows:
        try:
            identities.append(_line_identity(row))
            _feature_signature(row)
        except ReachabilityAsymmetryError as exc:
            errors.append(str(exc))
    if len(identities) != len(set(identities)):
        errors.append("duplicate selected-line identity")
    return rows, errors


def _identity_lists(values: set[tuple[str, int, str, str]]) -> list[list[Any]]:
    return [list(value) for value in sorted(values, key=_sort_identity)]


def _derive_cell(
    extracted: Mapping[str, Any],
    feature_rows: Sequence[Mapping[str, Any]],
    inconsistency_records: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    key = extracted["key"]
    contender_rows, contender_errors = _side_rows(feature_rows, key, control=False)
    control_rows, control_errors = _side_rows(feature_rows, key, control=True)
    errors = list(extracted["reconciliation_errors"] or [])
    errors.extend(contender_errors)
    errors.extend(control_errors)

    def identity_set(rows: Sequence[Mapping[str, Any]]) -> set[tuple[str, int, str, str]]:
        return {_line_identity(row) for row in rows}

    contender_selected = identity_set(contender_rows)
    control_selected = identity_set(control_rows)
    contender_reachable = {
        _line_identity(row) for row in contender_rows if _reachable(row)
    }
    control_reachable = {_line_identity(row) for row in control_rows if _reachable(row)}
    shared = contender_selected & control_selected
    contender_unique = contender_selected - control_selected
    control_unique = control_selected - contender_selected
    inconsistent = sorted(
        (contender_selected | control_selected) & set(inconsistency_records),
        key=_sort_identity,
    )
    inconsistency_ids = [
        str(inconsistency_records[identity]["global_inconsistency_id"])
        for identity in inconsistent
    ]
    if inconsistent:
        attribution_class = "SHARED_LINEAGE_REACHABILITY_INCONSISTENCY"
        errors.append("shared lineage feature inconsistency")
    else:
        contender_has = bool(contender_reachable)
        control_has = bool(control_reachable)
        if contender_has == control_has:
            attribution_class = "UNATTRIBUTED_ONE_SIDED_CELL"
            errors.append("reachable-direction XOR failure")
        elif not shared:
            attribution_class = "FULL_LINEAGE_SUBSTITUTION"
        elif (
            (contender_has and bool(contender_reachable & contender_unique))
            or (control_has and bool(control_reachable & control_unique))
        ) and not (contender_reachable & control_reachable):
            attribution_class = "PARTIAL_LINEAGE_SUBSTITUTION"
        else:
            attribution_class = "UNATTRIBUTED_ONE_SIDED_CELL"
            errors.append("reachable substitution membership unresolved")

    source_direction = extracted["primary_stratum_class"]
    derived_direction = (
        "contender_only" if contender_reachable else "control_only" if control_reachable else None
    )
    if derived_direction != source_direction:
        errors.append("primary stratum direction mismatch")

    denominator = len(contender_selected | control_selected)
    overlap_numerator = len(shared)
    if denominator == 0:
        errors.append("zero selected-line overlap denominator")
    overlap_rate = overlap_numerator / denominator if denominator else None

    reachable_rows = contender_rows if contender_reachable else control_rows
    missing_rows = control_rows if contender_reachable else contender_rows
    reachable_distances = sorted(
        _numeric(row.get("geometry_projected_distance_atr_96h"), "projected distance")
        for row in reachable_rows
        if _reachable(row)
    )
    missing_distances: list[float] = []
    for row in missing_rows:
        value = row.get("geometry_projected_distance_atr_96h")
        if value is None:
            errors.append("missing distance on missing side")
            continue
        missing_distances.append(_numeric(value, "projected distance"))
    missing_distances.sort()
    if not reachable_distances or not missing_distances:
        errors.append("distance evidence is empty")
        minimum_missing = None
        minimum_excess = None
        headroom = None
    else:
        minimum_missing = missing_distances[0]
        minimum_excess = minimum_missing - PRIMARY_THRESHOLD_ATR
        headroom = min(PRIMARY_THRESHOLD_ATR - value for value in reachable_distances)
        if minimum_excess <= 0:
            errors.append("missing-side distance is reachable")
        if headroom < 0:
            errors.append("reachable-side headroom is negative")

    resolved = not errors and attribution_class != "UNATTRIBUTED_ONE_SIDED_CELL"
    return {
        "cell_identity": list(key),
        "contender_policy_id": key[0],
        "control_policy_id": key[2],
        "budget_per_role": key[1],
        "dataset_id": key[3],
        "checkpoint_index": key[4],
        "semantic_role_at_selection": key[5],
        "horizon_hours": key[6],
        "one_sided_direction": source_direction,
        "attribution_class": attribution_class,
        "contender_selected": _identity_lists(contender_selected),
        "control_selected": _identity_lists(control_selected),
        "contender_reachable": _identity_lists(contender_reachable),
        "control_reachable": _identity_lists(control_reachable),
        "shared_selected": _identity_lists(shared),
        "contender_unique": _identity_lists(contender_unique),
        "control_unique": _identity_lists(control_unique),
        "selected_lineage_overlap_numerator": overlap_numerator,
        "selected_lineage_overlap_denominator": denominator,
        "selected_lineage_overlap_rate": overlap_rate,
        "reachable_side_projected_distances": reachable_distances,
        "missing_side_projected_distances": missing_distances,
        "minimum_missing_side_projected_distance": minimum_missing,
        "minimum_excess_above_8_atr": minimum_excess,
        "reachable_side_headroom_below_8_atr": headroom,
        "shared_lineage_projected_distance_equality": not bool(inconsistent),
        "global_inconsistency_identities": _identity_lists(set(inconsistent)),
        "global_inconsistency_ids": sorted(inconsistency_ids),
        "resolved": resolved,
        "reconciliation_errors": sorted(set(errors)),
    }


def _cross_budget(
    cell: dict[str, Any],
    source_index: Mapping[tuple[str, int, str, str, int, str, int], Mapping[str, Any]],
    feature_rows: Sequence[Mapping[str, Any]],
    derived_by_key: dict[tuple[str, int, str, str, int, str, int], dict[str, Any]],
) -> None:
    key = tuple(cell["cell_identity"])
    contender, budget, control, dataset, checkpoint, role, horizon = key
    inspected_keys: list[tuple[str, int, str, str, int, str, int]] = []
    cell["cross_budget_source_cell_identities"] = []
    if budget == 3:
        cell.update(
            {
                "cross_budget_class": "PERSISTENT_THROUGH_BUDGET_3",
                "rescue_budget": None,
                "contender_nested": None,
                "control_nested": None,
                "missing_side_reachable_gain": 0,
                "budget3_direction": cell["one_sided_direction"],
                "direction_preserved": True,
            }
        )
        return

    higher: dict[str, Any] | None = None
    for candidate_budget in range(budget + 1, 4):
        candidate_key = (
            contender,
            candidate_budget,
            control,
            dataset,
            checkpoint,
            role,
            horizon,
        )
        source = source_index.get(candidate_key)
        if source is None:
            continue
        inspected_keys.append(candidate_key)
        if (
            source.get("primary_stratum_class") == "paired"
            and source.get("terminal_cell_class") == "paired"
            and source.get("reconciliation_errors") == []
        ):
            higher = {"key": candidate_key, "source": source}
            break

    cell["cross_budget_source_cell_identities"] = [
        list(candidate_key) for candidate_key in inspected_keys
    ]

    if higher is not None:
        higher_key = higher["key"]
        if higher_key not in derived_by_key:
            derived_by_key[higher_key] = _derive_cell(
                {
                    **higher["source"],
                    "key": higher_key,
                    "reconciliation_errors": higher["source"].get("reconciliation_errors", []),
                },
                feature_rows,
                {},
            )
        higher_cell = derived_by_key[higher_key]
        lower_contender = {tuple(item) for item in cell["contender_selected"]}
        lower_control = {tuple(item) for item in cell["control_selected"]}
        higher_contender = {tuple(item) for item in higher_cell["contender_selected"]}
        higher_control = {tuple(item) for item in higher_cell["control_selected"]}
        contender_nested = lower_contender <= higher_contender
        control_nested = lower_control <= higher_control
        missing_side = (
            "control" if cell["one_sided_direction"] == "contender_only" else "contender"
        )
        lower_missing = (
            {tuple(item) for item in cell["control_reachable"]}
            if missing_side == "control"
            else {tuple(item) for item in cell["contender_reachable"]}
        )
        higher_missing = (
            {tuple(item) for item in higher_cell["control_reachable"]}
            if missing_side == "control"
            else {tuple(item) for item in higher_cell["contender_reachable"]}
        )
        gain = len(higher_missing - lower_missing)
        cell.update(
            {
                "rescue_budget": higher_key[1],
                "contender_nested": contender_nested,
                "control_nested": control_nested,
                "missing_side_reachable_gain": gain,
            }
        )
        if contender_nested and control_nested and gain >= 1:
            cell["cross_budget_class"] = "STRICT_BUDGET_RESCUE"
        elif not contender_nested or not control_nested:
            cell["cross_budget_class"] = "NON_NESTED_HIGHER_BUDGET_PAIRING"
        else:
            cell["cross_budget_class"] = None
            cell["cross_budget_unresolved_reason"] = (
                "paired_higher_budget_without_missing_side_reachable_gain"
            )
            cell["resolved"] = False
            cell["reconciliation_errors"].append(
                "paired_higher_budget_without_missing_side_reachable_gain"
            )
        return

    budget3_key = (
        contender,
        3,
        control,
        dataset,
        checkpoint,
        role,
        horizon,
    )
    budget3 = source_index.get(budget3_key)
    if budget3_key not in inspected_keys and budget3 is not None:
        cell["cross_budget_source_cell_identities"].append(list(budget3_key))
    if budget3 is None:
        cell["cross_budget_class"] = None
        cell["cross_budget_unresolved_reason"] = "budget3_missing"
        cell["resolved"] = False
        cell["reconciliation_errors"].append("budget3_missing")
        return
    budget3_primary = budget3.get("primary_stratum_class")
    if budget3_primary not in PRIMARY_CLASSES:
        reason = {
            "empty_both": "budget3_empty_both",
            "paired": "budget3_paired_without_valid_higher_pairing",
        }.get(str(budget3_primary), "budget3_unresolved_or_duplicate")
        cell["cross_budget_class"] = None
        cell["cross_budget_unresolved_reason"] = reason
        cell["resolved"] = False
        cell["reconciliation_errors"].append(reason)
        return
    cell.update(
        {
            "cross_budget_class": "PERSISTENT_THROUGH_BUDGET_3",
            "rescue_budget": None,
            "contender_nested": None,
            "control_nested": None,
            "missing_side_reachable_gain": 0,
            "budget3_direction": budget3_primary,
            "direction_preserved": budget3_primary == cell["one_sided_direction"],
        }
    )


def _summary_rows(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for cell in cells:
        key = (
            str(cell["contender_policy_id"]),
            str(cell["control_policy_id"]),
            int(cell["budget_per_role"]),
            str(cell["dataset_id"]),
            str(cell["semantic_role_at_selection"]),
            str(cell["one_sided_direction"]),
            str(cell["attribution_class"]),
            str(cell.get("cross_budget_class")),
        )
        grouped[key].append(cell)
    rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items(), key=lambda item: _sort_identity(item[0])):
        rows.append(
            {
                "contender_policy_id": key[0],
                "control_policy_id": key[1],
                "budget_per_role": key[2],
                "dataset_id": key[3],
                "semantic_role_at_selection": key[4],
                "one_sided_direction": key[5],
                "attribution_class": key[6],
                "cross_budget_class": None if key[7] == "None" else key[7],
                "cell_count": len(values),
                "resolved_cell_count": sum(bool(item["resolved"]) for item in values),
            }
        )
    return rows


def _refresh_attribution_identity(payload: dict[str, Any]) -> dict[str, Any]:
    identity_payload = {key: value for key, value in payload.items() if key != "attribution_id"}
    payload["attribution_id"] = _identity_hash(R5_DIAGNOSTIC_NAMESPACE, identity_payload)
    return payload


def _validate_complete_payload(attribution: Mapping[str, Any]) -> None:
    primary_population = attribution.get("primary_population")
    if not isinstance(primary_population, Mapping):
        raise ReachabilityAsymmetryError("complete R5 population is missing")
    expected_population = {
        "comparison_count": EXPECTED_COMPARISON_COUNT,
        "cell_count": EXPECTED_CELL_COUNT,
        "contender_only_cells": EXPECTED_CONTENDER_ONLY,
        "control_only_cells": EXPECTED_CONTROL_ONLY,
        "expected_comparison_count": EXPECTED_COMPARISON_COUNT,
        "expected_cell_count": EXPECTED_CELL_COUNT,
        "expected_contender_only_cells": EXPECTED_CONTENDER_ONLY,
        "expected_control_only_cells": EXPECTED_CONTROL_ONLY,
    }
    for field, expected in expected_population.items():
        actual = primary_population.get(field)
        if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
            raise ReachabilityAsymmetryError(
                f"complete R5 population mismatch: {field}"
            )
    unresolved = attribution.get("unresolved_evidence_count")
    if isinstance(unresolved, bool) or not isinstance(unresolved, int) or unresolved != 0:
        raise ReachabilityAsymmetryError("complete R5 payload has unresolved evidence")
    if attribution.get("reconciliation_errors") != []:
        raise ReachabilityAsymmetryError("complete R5 payload has reconciliation errors")
    if attribution.get("global_inconsistencies") != []:
        raise ReachabilityAsymmetryError("complete R5 payload has global inconsistencies")
    if attribution.get("forbidden_outcome_fields_used") != []:
        raise ReachabilityAsymmetryError("complete R5 payload uses outcome fields")
    cells = attribution.get("cells")
    if not isinstance(cells, list) or len(cells) != EXPECTED_CELL_COUNT:
        raise ReachabilityAsymmetryError("complete R5 cell count mismatch")
    identities: list[tuple[Any, ...]] = []
    direction_counts: Counter[str] = Counter()
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise ReachabilityAsymmetryError("complete R5 cell is not an object")
        identity = cell.get("cell_identity")
        if not isinstance(identity, list) or len(identity) != 7:
            raise ReachabilityAsymmetryError("complete R5 cell identity is invalid")
        if not (
            isinstance(identity[0], str)
            and isinstance(identity[1], int)
            and not isinstance(identity[1], bool)
            and isinstance(identity[2], str)
            and isinstance(identity[3], str)
            and isinstance(identity[4], int)
            and not isinstance(identity[4], bool)
            and isinstance(identity[5], str)
            and isinstance(identity[6], int)
            and not isinstance(identity[6], bool)
        ):
            raise ReachabilityAsymmetryError("complete R5 cell identity types are invalid")
        identities.append(tuple(identity))
        direction = cell.get("one_sided_direction")
        if not isinstance(direction, str) or direction not in PRIMARY_CLASSES:
            raise ReachabilityAsymmetryError("complete R5 direction is invalid")
        direction_counts[str(direction)] += 1
        attribution_class = cell.get("attribution_class")
        if (
            not isinstance(attribution_class, str)
            or attribution_class not in COMPLETE_ATTRIBUTION_CLASSES
        ):
            raise ReachabilityAsymmetryError("complete R5 attribution class is invalid")
        cross_budget_class = cell.get("cross_budget_class")
        if not isinstance(cross_budget_class, str) or cross_budget_class not in CROSS_BUDGET_CLASSES:
            raise ReachabilityAsymmetryError("complete R5 cross-budget class is invalid")
        if cell.get("resolved") is not True:
            raise ReachabilityAsymmetryError("complete R5 payload contains unresolved cell")
        if cell.get("reconciliation_errors") != []:
            raise ReachabilityAsymmetryError("complete R5 payload contains cell errors")
        if cell.get("global_inconsistency_ids") != []:
            raise ReachabilityAsymmetryError(
                "complete R5 payload contains inconsistency references"
            )
        if cell.get("global_inconsistency_identities") != []:
            raise ReachabilityAsymmetryError(
                "complete R5 payload contains inconsistency identities"
            )
        if cell.get("shared_lineage_projected_distance_equality") is not True:
            raise ReachabilityAsymmetryError(
                "complete R5 payload has shared-lineage inconsistency"
            )
    if len(set(identities)) != len(identities):
        raise ReachabilityAsymmetryError("complete R5 cell identities are not unique")
    if identities != sorted(identities, key=_sort_identity):
        raise ReachabilityAsymmetryError("complete R5 cells are not canonically ordered")
    if direction_counts != Counter(
        {
            "contender_only": EXPECTED_CONTENDER_ONLY,
            "control_only": EXPECTED_CONTROL_ONLY,
        }
    ):
        raise ReachabilityAsymmetryError("complete R5 direction counts mismatch")
    if attribution.get("summary_rows") != _summary_rows(cells):
        raise ReachabilityAsymmetryError("complete R5 summary rows mismatch")


def build_attribution(
    diagnostic: Mapping[str, Any],
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive R5 evidence from R4 feature and comparison fields only."""
    feature_rows = diagnostic.get("feature_rows")
    if not isinstance(feature_rows, list):
        raise ReachabilityAsymmetryError("R4 feature rows missing")
    extracted, source_index, extraction_errors = _comparison_records(diagnostic)
    relevant_source_keys = _relevant_source_keys(extracted, source_index)
    relevant_source_index = {
        key: source_index[key] for key in relevant_source_keys
    }
    relevant_feature_rows = _relevant_feature_rows(feature_rows, relevant_source_keys)
    consistency, consistency_errors = _global_feature_consistency(
        relevant_feature_rows,
        relevant_source_index,
    )
    cells = [
        _derive_cell(record, relevant_feature_rows, consistency)
        for record in sorted(extracted, key=lambda item: _sort_identity(item["key"]))
    ]
    derived_by_key = {
        tuple(cell["cell_identity"]): cell for cell in cells
    }
    for cell in cells:
        _cross_budget(cell, source_index, relevant_feature_rows, derived_by_key)
        affected_records = [
            record
            for record in consistency.values()
            if any(
                tuple(affected_key)
                in {
                    tuple(cell["cell_identity"]),
                    *(
                        tuple(key)
                        for key in cell.get("cross_budget_source_cell_identities", [])
                    ),
                }
                for affected_key in record.get("affected_cell_identities", [])
            )
        ]
        if affected_records:
            affected_identities = {
                tuple(record["selected_line_identity"])
                for record in affected_records
            }
            cell["global_inconsistency_identities"] = _identity_lists(
                affected_identities
            )
            cell["global_inconsistency_ids"] = sorted(
                str(record["global_inconsistency_id"])
                for record in affected_records
            )
            cell["shared_lineage_projected_distance_equality"] = False
            cell["attribution_class"] = "SHARED_LINEAGE_REACHABILITY_INCONSISTENCY"
            cell["resolved"] = False
            cell["reconciliation_errors"].append(
                "shared lineage feature inconsistency"
            )
        cell["reconciliation_errors"] = sorted(set(cell["reconciliation_errors"]))
        if cell.get("cross_budget_class") not in CROSS_BUDGET_CLASSES:
            cell["resolved"] = False
    global_records = [consistency[key] for key in sorted(consistency, key=_sort_identity)]
    all_errors = sorted(set(extraction_errors + consistency_errors))
    unresolved_cells = sum(not cell["resolved"] for cell in cells)
    if (
        len(cells) != EXPECTED_CELL_COUNT
        or any(cell["reconciliation_errors"] for cell in cells)
        or all_errors
        or unresolved_cells
        or global_records
    ):
        status = "R5_ATTRIBUTION_INCOMPLETE"
    else:
        status = "R5_ATTRIBUTION_COMPLETE"
    primary_population = {
        "comparison_count": sum(
            isinstance(item, Mapping)
            and (
                int(item.get("contender_only_cells", 0)) > 0
                or int(item.get("control_only_cells", 0)) > 0
            )
            for item in diagnostic.get("comparisons", [])
        ),
        "cell_count": len(cells),
        "contender_only_cells": sum(
            cell["one_sided_direction"] == "contender_only" for cell in cells
        ),
        "control_only_cells": sum(
            cell["one_sided_direction"] == "control_only" for cell in cells
        ),
        "expected_comparison_count": EXPECTED_COMPARISON_COUNT,
        "expected_cell_count": EXPECTED_CELL_COUNT,
        "expected_contender_only_cells": EXPECTED_CONTENDER_ONLY,
        "expected_control_only_cells": EXPECTED_CONTROL_ONLY,
    }
    payload = {
        "schema_version": R5_SCHEMA,
        "status": status,
        "source_binding": dict(source_binding),
        "primary_population": primary_population,
        "global_inconsistencies": global_records,
        "cells": cells,
        "summary_rows": _summary_rows(cells),
        "reconciliation_errors": all_errors,
        "unresolved_evidence_count": len(all_errors) + unresolved_cells + len(global_records),
        "forbidden_outcome_fields_used": [],
    }
    return _refresh_attribution_identity(payload)


def _prepare_bundle_payload(
    payload: Mapping[str, Any], source_binding: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    attribution = dict(payload)
    binding = dict(source_binding)
    if attribution.get("source_binding") != binding:
        raise ReachabilityAsymmetryError("attribution/source binding mismatch")
    identity_payload = {key: value for key, value in attribution.items() if key != "attribution_id"}
    if attribution.get("attribution_id") != _identity_hash(
        R5_DIAGNOSTIC_NAMESPACE, identity_payload
    ):
        raise ReachabilityAsymmetryError("R5 attribution identity mismatch")
    binding_payload = {key: value for key, value in binding.items() if key != "source_binding_id"}
    if binding.get("source_binding_id") != _identity_hash(
        R5_SOURCE_BINDING_NAMESPACE, binding_payload
    ):
        raise ReachabilityAsymmetryError("R5 source binding identity mismatch")
    if attribution.get("status") not in {
        "R5_ATTRIBUTION_COMPLETE",
        "R5_ATTRIBUTION_INCOMPLETE",
        "R5_ATTRIBUTION_BLOCKED",
    }:
        raise ReachabilityAsymmetryError("invalid R5 status")
    if attribution.get("status") == "R5_ATTRIBUTION_COMPLETE":
        _validate_complete_payload(attribution)
    return attribution, binding


def _render_bundle(
    payload: Mapping[str, Any], source_binding: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    attribution, binding = _prepare_bundle_payload(payload, source_binding)
    attribution_bytes = _canonical_bytes(attribution)
    binding_bytes = _canonical_bytes(binding)
    members = [
        {
            "path": "reachability_asymmetry_attribution.json",
            "byte_length": len(attribution_bytes),
            "sha256": _sha256_bytes(attribution_bytes),
        },
        {
            "path": "source_binding.json",
            "byte_length": len(binding_bytes),
            "sha256": _sha256_bytes(binding_bytes),
        },
    ]
    manifest_payload = {
        "schema_version": R5_MANIFEST_SCHEMA,
        "attribution_id": attribution["attribution_id"],
        "source_binding_id": binding["source_binding_id"],
        "member_count": 2,
        "members": members,
        "output_inventory_sha256": _inventory_sha256(members),
    }
    manifest = {
        **manifest_payload,
        "manifest_id": _identity_hash(R5_MANIFEST_NAMESPACE, manifest_payload),
    }
    return {
        "reachability_asymmetry_attribution.json": attribution_bytes,
        "source_binding.json": binding_bytes,
        "manifest.json": _canonical_bytes(manifest),
    }, manifest


def _write_bundle_files(
    root: Path, payload: Mapping[str, Any], source_binding: Mapping[str, Any]
) -> dict[str, Any]:
    rendered, manifest = _render_bundle(payload, source_binding)
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in rendered.items():
        _atomic_write(root / relative, content)
    return manifest


def publish_bundle(
    output_root: Path,
    payload: Mapping[str, Any],
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish exactly three R5 files with identical-only overwrite."""
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        manifest = _write_bundle_files(staging, payload, source_binding)
        candidate = {
            item["path"]: item["sha256"]
            for item in _artifact_inventory(staging)
        }
        if output_root.exists():
            existing = {
                item["path"]: item["sha256"]
                for item in _artifact_inventory(output_root)
            }
            if candidate != existing:
                raise ReachabilityAsymmetryError("refusing non-identical bundle overwrite")
            return manifest
        os.replace(staging, output_root)
        staging = None  # type: ignore[assignment]
        return manifest
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def _expected_bundle_from_evidence(
    expected_evidence: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    payload = expected_evidence.get("attribution")
    source_binding = expected_evidence.get("source_binding")
    if not isinstance(payload, Mapping) or not isinstance(source_binding, Mapping):
        raise ReachabilityAsymmetryError("synthetic verification requires explicit evidence")
    return _render_bundle(payload, source_binding)


def verify_attribution_bundle(
    root: Path,
    *,
    source_backed: bool = True,
    expected_evidence: Mapping[str, Any] | None = None,
    r4_root: Path = R4_ROOT,
) -> dict[str, Any]:
    """Verify R5 identities and either strict R4-backed or explicit synthetic bytes."""
    inventory = _artifact_inventory(root)
    if {item["path"] for item in inventory} != {
        "manifest.json",
        *R5_MEMBER_PATHS,
    }:
        raise ReachabilityAsymmetryError("R5 bundle paths are not exact")
    attribution = _read_canonical_json(root / R5_MEMBER_PATHS[0])
    source_binding = _read_canonical_json(root / R5_MEMBER_PATHS[1])
    manifest = _read_canonical_json(root / "manifest.json")
    _prepare_bundle_payload(attribution, source_binding)
    actual_members = tuple(item for item in inventory if item["path"] != "manifest.json")
    if tuple(manifest.get("members", [])) != actual_members:
        raise ReachabilityAsymmetryError("R5 manifest members do not match bytes")
    if manifest.get("member_count") != 2:
        raise ReachabilityAsymmetryError("R5 manifest member count mismatch")
    manifest_payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _identity_hash(R5_MANIFEST_NAMESPACE, manifest_payload):
        raise ReachabilityAsymmetryError("R5 manifest identity mismatch")
    if manifest.get("output_inventory_sha256") != _inventory_sha256(actual_members):
        raise ReachabilityAsymmetryError("R5 output inventory mismatch")
    if (
        manifest.get("attribution_id") != attribution.get("attribution_id")
        or manifest.get("source_binding_id") != source_binding.get("source_binding_id")
    ):
        raise ReachabilityAsymmetryError("R5 manifest cross-binding mismatch")
    if source_backed:
        source, verification = _r4_source(r4_root)
        expected_binding = _source_binding_payload(source, verification, r4_root)
        expected_payload = build_attribution(source["diagnostic"], expected_binding)
        expected_rendered, expected_manifest = _render_bundle(
            expected_payload, expected_binding
        )
    else:
        if expected_evidence is None:
            raise ReachabilityAsymmetryError("synthetic verification requires expected evidence")
        expected_rendered, expected_manifest = _expected_bundle_from_evidence(expected_evidence)
    for relative, expected_bytes in expected_rendered.items():
        if (root / relative).read_bytes() != expected_bytes:
            raise ReachabilityAsymmetryError(f"R5 artifact mismatch: {relative}")
    if manifest != expected_manifest:
        raise ReachabilityAsymmetryError("R5 manifest mismatch")
    return {
        "status": attribution["status"],
        "attribution_id": attribution["attribution_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "member_count": manifest["member_count"],
        "unresolved_evidence_count": attribution.get("unresolved_evidence_count"),
    }


def execute_attribution_study(
    *,
    r4_root: Path = R4_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if os.environ.get(EXECUTION_GUARD) != "1":
        raise ReachabilityAsymmetryError(f"missing execution guard: {EXECUTION_GUARD}=1")
    if output_root.exists():
        raise ReachabilityAsymmetryError("R5 output already exists; refusing rerun")
    before, verification_before = _r4_source(r4_root)
    binding = _source_binding_payload(before, verification_before, r4_root)
    payload = build_attribution(before["diagnostic"], binding)
    after, verification_after = _r4_source(r4_root)
    before_binding = before["source_binding"]
    after_binding = after["source_binding"]
    if (
        before_binding.get("source_before") != after_binding.get("source_before")
        or before_binding.get("source_after") != after_binding.get("source_after")
    ):
        raise ReachabilityAsymmetryError("R4 source mutation during R5 derivation")
    if verification_before != verification_after:
        raise ReachabilityAsymmetryError("R4 verification identity changed during R5")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        _write_bundle_files(staging, payload, binding)
        verify_attribution_bundle(staging, source_backed=True, r4_root=r4_root)
        if output_root.exists():
            raise ReachabilityAsymmetryError("R5 output appeared during execution")
        os.replace(staging, output_root)
        staging = None  # type: ignore[assignment]
        return verify_attribution_bundle(output_root, source_backed=True, r4_root=r4_root)
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-attribution-study", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.execute_attribution_study:
        print(json.dumps(execute_attribution_study(), sort_keys=True))
        return 0
    if args.verify:
        if not OUTPUT_ROOT.exists():
            raise ReachabilityAsymmetryError("R5 output absent")
        print(json.dumps(verify_attribution_bundle(OUTPUT_ROOT), sort_keys=True))
        return 0
    parser.error("select --verify or --execute-attribution-study")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
