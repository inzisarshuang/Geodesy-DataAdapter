"""Windowed preparation for indexed single-band GeoTIFF Defsour export."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

from insar_data_adapter.grid import aggregate_grid_array
from insar_data_adapter.raster import reproject_downsampled_grid_to_profile

from .grid import GridProfile, PreparedDefsourGrid, coordinate_arrays


@dataclass(frozen=True)
class _StaticGrid:
    height_file: Path
    mask_file: Path
    source_profile: GridProfile
    valid_count: int
    mask_mode: str


def _profile_from_raster(path: str | Path, configured_crs: str) -> GridProfile:
    """Read and validate the reference profile from one deformation raster."""

    source_path = Path(path).expanduser().resolve()
    with rasterio.open(source_path) as dataset:
        if dataset.count != 1:
            raise ValueError("GeoTIFF series deformation raster must be single-band")
        if dataset.crs is None:
            raise ValueError("GeoTIFF series deformation raster requires a declared CRS")
        expected = CRS.from_user_input(configured_crs)
        if CRS.from_user_input(dataset.crs) != expected:
            raise ValueError("configured source_crs conflicts with deformation TIFF CRS")
        return GridProfile(
            dataset.height,
            dataset.width,
            expected.to_string(),
            dataset.transform,
            "pixel_center",
        )


def _native_windows(
    height: int,
    width: int,
    *,
    factor: int,
    chunk_rows: int,
) -> Iterable[Window]:
    """Yield complete, factor-aligned source windows bounded by chunk rows."""

    if factor < 1 or chunk_rows < factor:
        raise ValueError("chunk_rows must be at least the downsample factor")
    output_rows = height // factor
    output_columns = width // factor
    if output_rows < 1 or output_columns < 1:
        raise ValueError("downsample factor is larger than the source raster")
    rows_per_window = max(1, chunk_rows // factor) * factor
    trimmed_rows = output_rows * factor
    trimmed_columns = output_columns * factor
    for row_start in range(0, trimmed_rows, rows_per_window):
        row_stop = min(row_start + rows_per_window, trimmed_rows)
        yield Window(0, row_start, trimmed_columns, row_stop - row_start)


def _aligned_vrts(
    stack: ExitStack,
    height_file: Path,
    mask_file: Path,
    profile: GridProfile,
) -> tuple[WarpedVRT, WarpedVRT]:
    height_source = stack.enter_context(rasterio.open(height_file))
    mask_source = stack.enter_context(rasterio.open(mask_file))
    if height_source.count != 1 or mask_source.count != 1:
        raise ValueError("GeoTIFF Defsour DEM and mask must be single-band")
    if height_source.crs is None or mask_source.crs is None:
        raise ValueError("GeoTIFF Defsour DEM and mask require declared CRS values")
    height = stack.enter_context(
        WarpedVRT(
            height_source,
            crs=profile.crs,
            transform=profile.transform,
            width=profile.width,
            height=profile.height,
            src_nodata=height_source.nodata,
            nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    )
    mask = stack.enter_context(
        WarpedVRT(
            mask_source,
            crs=profile.crs,
            transform=profile.transform,
            width=profile.width,
            height=profile.height,
            src_nodata=mask_source.nodata,
            nodata=0.0,
            resampling=Resampling.nearest,
        )
    )
    return height, mask


def _prepare_static_grid(
    height_file: str | Path,
    mask_file: str | Path,
    source_profile: GridProfile,
    *,
    chunk_rows: int,
    mask_mode: str,
) -> _StaticGrid:
    """Validate aligned static coverage and count valid native cells by window."""

    if mask_mode != "positive":
        raise ValueError("mask_mode must be positive")
    height_path = Path(height_file).expanduser().resolve()
    mask_path = Path(mask_file).expanduser().resolve()
    valid_count = 0
    with ExitStack() as stack:
        height, mask = _aligned_vrts(stack, height_path, mask_path, source_profile)
        for window in _native_windows(
            source_profile.height,
            source_profile.width,
            factor=1,
            chunk_rows=chunk_rows,
        ):
            height_values = height.read(1, window=window, masked=False)
            positive = mask.read(1, window=window, masked=False) > 0
            if np.any(positive & ~np.isfinite(height_values)):
                raise ValueError("positive static mask extends outside finite DEM coverage")
            valid_count += int(np.count_nonzero(positive & np.isfinite(height_values)))
    return _StaticGrid(
        height_path,
        mask_path,
        source_profile,
        valid_count,
        mask_mode,
    )


def _validate_epoch_profile(dataset: rasterio.io.DatasetReader, profile: GridProfile) -> None:
    if dataset.count != 1:
        raise ValueError("GeoTIFF series deformation raster must be single-band")
    if dataset.crs is None or CRS.from_user_input(dataset.crs) != CRS.from_user_input(
        profile.crs
    ):
        raise ValueError("GeoTIFF series deformation raster CRS mismatch")
    if (dataset.height, dataset.width) != (profile.height, profile.width):
        raise ValueError("GeoTIFF series deformation raster shape mismatch")
    if not np.allclose(tuple(dataset.transform)[:6], tuple(profile.transform)[:6]):
        raise ValueError("GeoTIFF series deformation raster transform mismatch")


def _prepare_epoch_grid(
    deformation_file: str | Path,
    static: _StaticGrid,
    *,
    factor: int,
    aggregation: str,
    chunk_rows: int,
    destination_profile: GridProfile | None = None,
) -> PreparedDefsourGrid:
    """Aggregate one epoch from bounded native windows and optionally reproject."""

    profile = static.source_profile
    output_rows = profile.height // factor
    output_columns = profile.width // factor
    height_out = np.full((output_rows, output_columns), np.nan, dtype=np.float64)
    deformation_out = np.full_like(height_out, np.nan)
    with ExitStack() as stack:
        deformation = stack.enter_context(
            rasterio.open(Path(deformation_file).expanduser().resolve())
        )
        _validate_epoch_profile(deformation, profile)
        height, mask = _aligned_vrts(
            stack, static.height_file, static.mask_file, profile
        )
        for window in _native_windows(
            profile.height,
            profile.width,
            factor=factor,
            chunk_rows=chunk_rows,
        ):
            height_values = height.read(1, window=window, masked=False)
            deformation_values = deformation.read(1, window=window, masked=False)
            mask_values = mask.read(1, window=window, masked=False)
            valid = (
                (mask_values > 0)
                & np.isfinite(height_values)
                & np.isfinite(deformation_values)
            )
            output_start = int(window.row_off) // factor
            output_stop = output_start + int(window.height) // factor
            height_out[output_start:output_stop] = aggregate_grid_array(
                height_values, valid, factor, aggregation
            )
            deformation_out[output_start:output_stop] = aggregate_grid_array(
                deformation_values, valid, factor, aggregation
            )
    valid_out = np.isfinite(height_out) & np.isfinite(deformation_out)
    downsampled_profile = profile.downsampled(factor)
    output_profile = downsampled_profile
    if destination_profile is not None:
        height_out, deformation_out, valid_out = (
            reproject_downsampled_grid_to_profile(
                height_out,
                deformation_out,
                valid_out,
                downsampled_profile.rasterio_profile(),
                destination_profile.rasterio_profile(),
            )
        )
        output_profile = destination_profile
    x, y = coordinate_arrays(output_profile)
    return PreparedDefsourGrid(
        x,
        y,
        height_out,
        deformation_out,
        valid_out,
        output_profile,
    )


__all__ = []
