"""Immutable metadata returned by complete Defsour workflow builds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from insar_data_adapter.exporters.defsour import DefsourExportMetadata

_DATE = re.compile(r"\d{8}\Z")
_SOURCE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")


def _relative(path: Path, label: str) -> Path:
    value = Path(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError(f"{label} must be a safe relative path")
    if value.name in {"defsour_manifest.json", "README_DEFSOUR.txt"}:
        raise ValueError(f"{label} uses a reserved snapshot filename")
    return value


@dataclass(frozen=True)
class DefsourEpochResult:
    """Describe the staged products for one output epoch."""

    date: str
    defsour_path: Path
    point_count: int
    geotiff_path: Path | None = None

    def __post_init__(self) -> None:
        if _DATE.fullmatch(self.date) is None:
            raise ValueError("Defsour epoch date must be YYYYMMDD")
        object.__setattr__(
            self, "defsour_path", _relative(self.defsour_path, "Defsour epoch path")
        )
        if self.geotiff_path is not None:
            object.__setattr__(
                self,
                "geotiff_path",
                _relative(self.geotiff_path, "Defsour GeoTIFF path"),
            )
        if isinstance(self.point_count, bool) or self.point_count < 0:
            raise ValueError("Defsour epoch point_count must be non-negative")


@dataclass(frozen=True)
class DefsourSnapshotMetadata:
    """Describe a complete multi-epoch Defsour snapshot before publication."""

    source: str
    epochs: tuple[DefsourEpochResult, ...]
    metadata: DefsourExportMetadata
    transformations: Mapping[str, Any]
    additional_products: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if _SOURCE.fullmatch(self.source) is None:
            raise ValueError("Defsour snapshot source is invalid")
        epochs = tuple(self.epochs)
        if not epochs:
            raise ValueError("Defsour snapshot requires at least one epoch")
        if len({epoch.date for epoch in epochs}) != len(epochs):
            raise ValueError("Defsour snapshot contains duplicate dates")
        object.__setattr__(self, "epochs", epochs)
        object.__setattr__(
            self,
            "additional_products",
            tuple(
                _relative(path, "Defsour additional product")
                for path in self.additional_products
            ),
        )
        object.__setattr__(self, "transformations", dict(self.transformations))


__all__ = ["DefsourEpochResult", "DefsourSnapshotMetadata"]
