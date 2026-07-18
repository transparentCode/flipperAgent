from __future__ import annotations

import ast
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import os
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.config.identities import ContentIdentity
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.source.frozen import (
    read_verified_frozen_file,
    source_bar_payload,
    source_bars_sha256,
    source_grid_sha256,
)
from libs.models.sr.scripts.cohort_readiness.config import load_cohort_config
from libs.models.sr.scripts.cohort_readiness.contracts import (
    bars_sha256,
    grid_sha256,
)
from libs.models.sr.scripts.cohort_readiness.runner import resolve_frozen_configs
from libs.models.sr.scripts.cohort_readiness.source import load_taousdt_source


def _identity(data: bytes) -> ContentIdentity:
    return ContentIdentity(sha256=sha256(data).hexdigest(), byte_length=len(data))


def _bar(**changes: object) -> SourceBar:
    values: dict[str, object] = {
        "open_time": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "closed_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "bar_id": "binance_usdm:TAOUSDT:1d:1704067200000",
    }
    values.update(changes)
    return SourceBar(**values)  # type: ignore[arg-type]


def test_read_verified_frozen_file_returns_exact_valid_bytes(tmp_path: Path) -> None:
    data = b"frozen\x00source\n"
    path = tmp_path / "source.json"
    path.write_bytes(data)

    assert read_verified_frozen_file(path, identity=_identity(data), description="frozen source") == data


@pytest.mark.parametrize(
    "identity",
    (
        ContentIdentity(sha256="0" * 64, byte_length=3),
        ContentIdentity(sha256=sha256(b"data").hexdigest(), byte_length=5),
    ),
)
def test_read_verified_frozen_file_rejects_identity_mismatch(
    tmp_path: Path,
    identity: ContentIdentity,
) -> None:
    path = tmp_path / "source.json"
    path.write_bytes(b"data")

    with pytest.raises(ContractValidationError, match="frozen source identity mismatch"):
        read_verified_frozen_file(path, identity=identity, description="frozen source")


def test_read_verified_frozen_file_rejects_missing_and_directory_paths(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError, match="frozen source cannot be read"):
        read_verified_frozen_file(
            tmp_path / "missing.json",
            identity=_identity(b""),
            description="frozen source",
        )
    with pytest.raises(ContractValidationError, match="frozen source must be a regular file"):
        read_verified_frozen_file(tmp_path, identity=_identity(b""), description="frozen source")


def test_read_verified_frozen_file_rejects_member_and_parent_symlinks(tmp_path: Path) -> None:
    data = b"frozen"
    target = tmp_path / "target.json"
    target.write_bytes(data)
    member_link = tmp_path / "member.json"
    member_link.symlink_to(target)

    with pytest.raises(ContractValidationError, match="path contains symlink"):
        read_verified_frozen_file(member_link, identity=_identity(data), description="frozen source")

    target_parent = tmp_path / "target-parent"
    target_parent.mkdir()
    (target_parent / "source.json").write_bytes(data)
    parent_link = tmp_path / "linked-parent"
    parent_link.symlink_to(target_parent, target_is_directory=True)

    with pytest.raises(ContractValidationError, match="path contains symlink"):
        read_verified_frozen_file(
            parent_link / "source.json",
            identity=_identity(data),
            description="frozen source",
        )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_read_verified_frozen_file_rejects_non_regular_fifo(tmp_path: Path) -> None:
    fifo = tmp_path / "source.fifo"
    os.mkfifo(fifo)

    with pytest.raises(ContractValidationError, match="frozen source must be a regular file"):
        read_verified_frozen_file(fifo, identity=_identity(b""), description="frozen source")


def test_source_bar_payload_has_exact_order_and_values() -> None:
    bar = _bar()

    assert source_bar_payload(bar) == {
        "open_time": "2024-01-01T00:00:00Z",
        "closed_at": "2024-01-02T00:00:00Z",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "bar_id": "binance_usdm:TAOUSDT:1d:1704067200000",
    }
    assert tuple(source_bar_payload(bar)) == (
        "open_time",
        "closed_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bar_id",
    )


@pytest.mark.parametrize("bars", ((), [], (_bar(), object())))
def test_source_bar_identity_rejects_invalid_collections(bars: object) -> None:
    with pytest.raises(ContractValidationError):
        source_bars_sha256(bars)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        source_grid_sha256(bars)  # type: ignore[arg-type]


def test_cohort_frozen_bar_and_grid_hashes_remain_exact() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    config = load_cohort_config(
        repo_root / "configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml"
    )
    _, _, hashes = resolve_frozen_configs(config, repo_root=repo_root)
    source = load_taousdt_source(
        config,
        repo_root=repo_root,
        resolved_sr_config_hash=hashes["TAOUSDT"][0],
        resolved_input_hash=hashes["TAOUSDT"][1],
    )

    assert source_bars_sha256(source.bars) == (
        "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
    )
    assert source_grid_sha256(source.bars) == (
        "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8"
    )
    assert bars_sha256(source.bars) == source_bars_sha256(source.bars)
    assert grid_sha256(source.bars) == source_grid_sha256(source.bars)


def test_frozen_primitives_import_no_studies_or_forbidden_runtime_modules() -> None:
    import libs.models.sr.research.source.frozen as frozen_module

    parsed = ast.parse(inspect.getsource(frozen_module))
    imported = [
        alias.name
        for node in ast.walk(parsed)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module
        for node in ast.walk(parsed)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    forbidden = (
        "libs.models.sr.scripts",
        "requests",
        "socket",
        "sqlite3",
        "sqlalchemy",
        "pandas",
        "binance",
        "zone_viewer",
    )
    assert not any(module.startswith(forbidden) for module in imported)
