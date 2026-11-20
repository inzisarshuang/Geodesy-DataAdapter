"""Strict read-only index for one scalar GeoTIFF time series."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_EPOCH_ID = re.compile(r"\d{8}T\d{6}\Z")


@dataclass(frozen=True)
class GeoTIFFSeriesEpoch:
    """Associate one exact acquisition identity with one GeoTIFF."""

    epoch_id: str
    date: str
    path: Path

    def __post_init__(self) -> None:
        if _EPOCH_ID.fullmatch(self.epoch_id) is None:
            raise ValueError("GeoTIFF series epoch_id must be YYYYMMDDTHHMMSS")
        try:
            datetime.strptime(self.epoch_id, "%Y%m%dT%H%M%S")
        except ValueError as error:
            raise ValueError(
                "GeoTIFF series epoch_id must contain a valid date and time"
            ) from error
        if self.date != self.epoch_id[:8]:
            raise ValueError("GeoTIFF series date must match epoch_id")
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())


def read_geotiff_series_index(
    index_file: str | Path,
) -> tuple[GeoTIFFSeriesEpoch, ...]:
    """Read an ordered two-column ``epoch_id TIFF`` index."""

    index = Path(index_file).expanduser().resolve()
    if not index.is_file():
        raise FileNotFoundError(f"GeoTIFF series index not found: {index}")
    epochs: list[GeoTIFFSeriesEpoch] = []
    epoch_ids: set[str] = set()
    paths: set[Path] = set()
    for line_number, raw_line in enumerate(
        index.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        columns = stripped.split()
        if len(columns) != 2:
            raise ValueError(
                f"GeoTIFF series index line {line_number} must contain exactly two columns"
            )
        epoch_id, raw_path = columns
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = index.parent / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"GeoTIFF series TIFF is missing or not a file: {path}"
            )
        epoch = GeoTIFFSeriesEpoch(epoch_id, epoch_id[:8], path)
        if epoch.epoch_id in epoch_ids:
            raise ValueError(
                f"GeoTIFF series index contains duplicate epoch_id: {epoch.epoch_id}"
            )
        if path in paths:
            raise ValueError(f"GeoTIFF series index contains duplicate TIFF path: {path}")
        epochs.append(epoch)
        epoch_ids.add(epoch.epoch_id)
        paths.add(path)
    if not epochs:
        raise ValueError("GeoTIFF series index requires at least one epoch")
    return tuple(epochs)


__all__ = ["GeoTIFFSeriesEpoch", "read_geotiff_series_index"]
