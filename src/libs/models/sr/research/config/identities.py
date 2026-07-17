"""Minimal immutable identities shared across SR research studies."""

from __future__ import annotations

from dataclasses import dataclass

from .primitives import (
    require_git_commit,
    require_integer,
    require_safe_relative_path,
    require_sha256,
)


@dataclass(frozen=True)
class ConfigReference:
    """Immutable reference to one frozen configuration document."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_safe_relative_path(self.path, path="config.path"))
        object.__setattr__(self, "sha256", require_sha256(self.sha256, path="config.sha256"))

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class BundleReference:
    """Immutable reference to one implementation-bound research bundle."""

    path: str
    bundle_id: str
    implementation_commit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_safe_relative_path(self.path, path="bundle.path"))
        object.__setattr__(self, "bundle_id", require_sha256(self.bundle_id, path="bundle.bundle_id"))
        object.__setattr__(
            self,
            "implementation_commit",
            require_git_commit(self.implementation_commit, path="bundle.implementation_commit"),
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "path": self.path,
            "bundle_id": self.bundle_id,
            "implementation_commit": self.implementation_commit,
        }


@dataclass(frozen=True)
class ContentIdentity:
    """Immutable identity for one serialized evidence member."""

    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", require_sha256(self.sha256, path="content.sha256"))
        object.__setattr__(
            self,
            "byte_length",
            require_integer(self.byte_length, path="content.byte_length", minimum=0),
        )

    def to_payload(self) -> dict[str, str | int]:
        return {"sha256": self.sha256, "byte_length": self.byte_length}


@dataclass(frozen=True)
class SourceIdentity:
    """Immutable identifier subset for a non-empty frozen source."""

    source_bundle_id: str
    source_id: str
    bars_sha256: str
    row_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_bundle_id",
            require_sha256(self.source_bundle_id, path="source.source_bundle_id"),
        )
        object.__setattr__(self, "source_id", require_sha256(self.source_id, path="source.source_id"))
        object.__setattr__(self, "bars_sha256", require_sha256(self.bars_sha256, path="source.bars_sha256"))
        object.__setattr__(
            self,
            "row_count",
            require_integer(self.row_count, path="source.row_count", minimum=1),
        )

    def to_payload(self) -> dict[str, str | int]:
        return {
            "source_bundle_id": self.source_bundle_id,
            "source_id": self.source_id,
            "bars_sha256": self.bars_sha256,
            "row_count": self.row_count,
        }


__all__ = [
    "BundleReference",
    "ConfigReference",
    "ContentIdentity",
    "SourceIdentity",
]
