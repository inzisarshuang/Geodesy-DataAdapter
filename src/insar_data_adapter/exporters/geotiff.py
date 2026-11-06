"""Atomic single-band GeoTIFF publication for prepared Defsour grids."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import rasterio

from insar_data_adapter.workflows.defsour.grid import GridProfile


def _text(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"GeoTIFF {label} must not be blank")
    return normalized


def write_geotiff(
    path: Path,
    values: np.ndarray,
    valid_mask: np.ndarray,
    profile: GridProfile,
    *,
    unit: str,
    quantity: str,
    nodata: float = np.nan,
) -> Path:
    """Write one masked float grid without exposing a partial replacement."""

    data = np.asarray(values)
    valid = np.asarray(valid_mask, dtype=bool)
    expected = (profile.height, profile.width)
    if data.shape != expected or valid.shape != expected:
        raise ValueError("GeoTIFF values, mask, and profile shape must match")
    normalized_unit = _text(unit, "unit")
    normalized_quantity = _text(quantity, "quantity")
    nodata_value = float(nodata)
    if np.isinf(nodata_value):
        raise ValueError("GeoTIFF nodata must be finite or NaN")
    if not np.isfinite(data[valid]).all():
        raise ValueError("GeoTIFF valid values must be finite")
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tif", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    raster = np.asarray(data, dtype=np.float32).copy()
    raster[~valid] = nodata_value
    try:
        with rasterio.open(
            temporary,
            "w",
            driver="GTiff",
            height=profile.height,
            width=profile.width,
            count=1,
            dtype="float32",
            crs=profile.crs,
            transform=profile.transform,
            nodata=nodata_value,
            compress="deflate",
        ) as dataset:
            dataset.write(raster, 1)
            dataset.update_tags(
                unit=normalized_unit,
                quantity=normalized_quantity,
                pixel_registration=profile.registration,
            )
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return output


__all__ = ["write_geotiff"]
