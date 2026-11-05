"""Explicit InSAR phase and LOS-displacement unit conversions."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Callable, Literal

import numpy as np

from .geotiff import (
    GeoTiffConversionResult,
    GeoTiffValueMetadata,
    convert_geotiff_raster,
)

_DISPLACEMENT_UNITS_TO_METRES = {"m": 1.0, "cm": 0.01, "mm": 0.001}
_PHASE_UNITS = {"rad", "radian", "radians"}


def _wavelength_m(value: float) -> float:
    """Return one valid radar wavelength in metres."""

    if isinstance(value, bool):
        raise ValueError("wavelength_m must be positive and finite")
    try:
        wavelength = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("wavelength_m must be positive and finite") from error
    if not np.isfinite(wavelength) or wavelength <= 0.0:
        raise ValueError("wavelength_m must be positive and finite")
    return wavelength


def _displacement_unit(unit: str) -> str:
    normalized = str(unit).strip().lower()
    if normalized not in _DISPLACEMENT_UNITS_TO_METRES:
        raise ValueError("displacement unit must be 'm', 'cm', or 'mm'")
    return normalized


def phase_to_los_displacement(
    phase_radians: np.ndarray | float,
    wavelength_m: float,
    output_unit: str = "mm",
) -> np.ndarray:
    """Convert radians to LOS displacement, positive toward the satellite."""

    wavelength = _wavelength_m(wavelength_m)
    unit = _displacement_unit(output_unit)
    return (
        np.asarray(phase_radians, dtype=np.float64)
        * (-wavelength / (4.0 * np.pi))
        / _DISPLACEMENT_UNITS_TO_METRES[unit]
    )


def los_displacement_to_phase(
    displacement: np.ndarray | float,
    wavelength_m: float,
    input_unit: str = "mm",
) -> np.ndarray:
    """Convert LOS displacement to radians using the inverse phase convention."""

    wavelength = _wavelength_m(wavelength_m)
    unit = _displacement_unit(input_unit)
    return (
        np.asarray(displacement, dtype=np.float64)
        * _DISPLACEMENT_UNITS_TO_METRES[unit]
        * (-4.0 * np.pi / wavelength)
    )


def _binary_dtype(byte_order: str) -> np.dtype:
    normalized = str(byte_order).strip().lower()
    if normalized not in {"big", "little"}:
        raise ValueError("byte_order must be 'big' or 'little'")
    return np.dtype(">f4" if normalized == "big" else "<f4")


def _raster_shape(shape: tuple[int, int]) -> tuple[int, int]:
    if (
        len(shape) != 2
        or any(isinstance(size, bool) or not isinstance(size, int) for size in shape)
        or any(size <= 0 for size in shape)
    ):
        raise ValueError("shape must contain positive integer rows and columns")
    return shape


def _convert_float32_binary_raster(
    input_path: str | Path,
    output_path: str | Path,
    shape: tuple[int, int],
    wavelength_m: float,
    *,
    byte_order: Literal["big", "little"],
    block_rows: int,
    overwrite: bool,
    convert_block: Callable[[np.ndarray, float], np.ndarray],
) -> Path:
    source = Path(input_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    rows, columns = _raster_shape(shape)
    dtype = _binary_dtype(byte_order)
    wavelength = _wavelength_m(wavelength_m)
    if isinstance(block_rows, bool) or not isinstance(block_rows, int) or block_rows <= 0:
        raise ValueError("block_rows must be a positive integer")
    if source == output:
        raise ValueError("input and output paths must be different")
    if not source.is_file():
        raise FileNotFoundError(f"input raster is not a regular file: {source}")
    expected_size = rows * columns * dtype.itemsize
    actual_size = source.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"input raster size mismatch: {actual_size} bytes, "
            f"expected {expected_size} for shape {rows}x{columns}"
        )
    if output.exists() and not overwrite:
        raise FileExistsError(f"output raster already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    source_data: np.memmap | None = None
    output_data: np.memmap | None = None
    try:
        source_data = np.memmap(source, dtype=dtype, mode="r", shape=(rows, columns))
        output_data = np.memmap(
            temporary, dtype=dtype, mode="w+", shape=(rows, columns)
        )
        for row_start in range(0, rows, block_rows):
            row_stop = min(row_start + block_rows, rows)
            output_data[row_start:row_stop] = convert_block(
                source_data[row_start:row_stop], wavelength
            ).astype(dtype, copy=False)
        output_data.flush()
        del output_data
        output_data = None
        del source_data
        source_data = None
        os.replace(temporary, output)
    finally:
        if output_data is not None:
            del output_data
        if source_data is not None:
            del source_data
        temporary.unlink(missing_ok=True)
    return output


def convert_phase_binary_raster(
    input_path: str | Path,
    output_path: str | Path,
    shape: tuple[int, int],
    wavelength_m: float,
    *,
    output_unit: str = "mm",
    byte_order: Literal["big", "little"],
    block_rows: int = 256,
    overwrite: bool = True,
) -> Path:
    """Convert a headerless float32 phase raster to LOS displacement in blocks."""

    unit = _displacement_unit(output_unit)
    return _convert_float32_binary_raster(
        input_path,
        output_path,
        shape,
        wavelength_m,
        byte_order=byte_order,
        block_rows=block_rows,
        overwrite=overwrite,
        convert_block=lambda values, wavelength: (
            values.astype(np.float64)
            * (-wavelength / (4.0 * np.pi))
            / _DISPLACEMENT_UNITS_TO_METRES[unit]
        ),
    )


def convert_los_displacement_binary_raster(
    input_path: str | Path,
    output_path: str | Path,
    shape: tuple[int, int],
    wavelength_m: float,
    *,
    input_unit: str = "mm",
    byte_order: Literal["big", "little"],
    block_rows: int = 256,
    overwrite: bool = True,
) -> Path:
    """Convert a headerless float32 LOS-displacement raster to radians in blocks."""

    unit = _displacement_unit(input_unit)
    return _convert_float32_binary_raster(
        input_path,
        output_path,
        shape,
        wavelength_m,
        byte_order=byte_order,
        block_rows=block_rows,
        overwrite=overwrite,
        convert_block=lambda values, wavelength: (
            values.astype(np.float64)
            * _DISPLACEMENT_UNITS_TO_METRES[unit]
            * (-4.0 * np.pi / wavelength)
        ),
    )


def _geotiff_scale(
    metadata: GeoTiffValueMetadata,
    wavelength_m: float,
    *,
    phase_to_displacement: bool,
) -> float:
    wavelength = _wavelength_m(wavelength_m)
    input_unit = metadata.input_unit.strip().lower()
    output_unit = metadata.output_unit.strip().lower()
    if phase_to_displacement:
        if input_unit not in _PHASE_UNITS:
            raise ValueError("phase GeoTIFF metadata input_unit must be radians ('rad')")
        unit = _displacement_unit(output_unit)
        return (
            -wavelength
            / (4.0 * np.pi)
            / _DISPLACEMENT_UNITS_TO_METRES[unit]
        )
    unit = _displacement_unit(input_unit)
    if output_unit not in _PHASE_UNITS:
        raise ValueError("phase GeoTIFF metadata output_unit must be radians ('rad')")
    return (
        _DISPLACEMENT_UNITS_TO_METRES[unit]
        * (-4.0 * np.pi / wavelength)
    )


def convert_phase_geotiff_to_los_displacement(
    input_path: str | Path,
    output_path: str | Path,
    wavelength_m: float,
    metadata: GeoTiffValueMetadata,
    *,
    overwrite: bool = True,
) -> GeoTiffConversionResult:
    """Convert a phase GeoTIFF to LOS displacement while preserving its grid."""

    scale = _geotiff_scale(metadata, wavelength_m, phase_to_displacement=True)
    return convert_geotiff_raster(
        input_path,
        output_path,
        metadata,
        target_crs=None,
        scale=scale,
        nan_to_zero=False,
        resampling="nearest",
        overwrite=overwrite,
    )


def convert_los_displacement_geotiff_to_phase(
    input_path: str | Path,
    output_path: str | Path,
    wavelength_m: float,
    metadata: GeoTiffValueMetadata,
    *,
    overwrite: bool = True,
) -> GeoTiffConversionResult:
    """Convert a displacement GeoTIFF to radians while preserving its grid."""

    scale = _geotiff_scale(metadata, wavelength_m, phase_to_displacement=False)
    return convert_geotiff_raster(
        input_path,
        output_path,
        metadata,
        target_crs=None,
        scale=scale,
        nan_to_zero=False,
        resampling="nearest",
        overwrite=overwrite,
    )


__all__ = [
    "convert_los_displacement_binary_raster",
    "convert_los_displacement_geotiff_to_phase",
    "convert_phase_binary_raster",
    "convert_phase_geotiff_to_los_displacement",
    "los_displacement_to_phase",
    "phase_to_los_displacement",
]
