"""Immutable metadata returned by complete Defsour workflow builds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from insar_data_adapter.exporters.defsour import DefsourExportMetadata

_DATE = re.compile(r"\d{8}\Z")
_EPOCH_ID = re.compile(r"\d{8}T\d{6}\Z")
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
    defsour_path: Path | None
    point_count: int
    geotiff_path: Path | None = None
    epoch_id: str | None = None

    def __post_init__(self) -> None:
        if _DATE.fullmatch(self.date) is None:
            raise ValueError("Defsour epoch date must be YYYYMMDD")
        if self.epoch_id is not None:
            if _EPOCH_ID.fullmatch(self.epoch_id) is None:
                raise ValueError("Defsour epoch_id must be YYYYMMDDTHHMMSS")
            try:
                datetime.strptime(self.epoch_id, "%Y%m%dT%H%M%S")
            except ValueError as error:
                raise ValueError(
                    "Defsour epoch_id must contain a valid calendar date and time"
                ) from error
            if not self.epoch_id.startswith(self.date):
                raise ValueError("Defsour epoch_id date must match Defsour epoch date")
        if self.defsour_path is not None:
            object.__setattr__(
                self,
                "defsour_path",
                _relative(self.defsour_path, "Defsour epoch path"),
            )
        if self.geotiff_path is not None:
            object.__setattr__(
                self,
                "geotiff_path",
                _relative(self.geotiff_path, "Defsour GeoTIFF path"),
            )
        if self.defsour_path is None and self.geotiff_path is None:
            raise ValueError("Defsour epoch requires a text or GeoTIFF product")
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
        identities = tuple(epoch.epoch_id or epoch.date for epoch in epochs)
        if len(set(identities)) != len(epochs):
            raise ValueError("Defsour snapshot contains duplicate epoch identities")
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
