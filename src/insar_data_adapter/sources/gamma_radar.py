"""Read-only GAMMA radar-coordinate source primitives.

功能概述:
    严格解析 GAMMA 参数文件、无文件头实数/复数栅格及地理网格 lookup，所有
    dtype、字节序、形状和目标范围均由调用方显式提供或由参数文件校验获得。

函数说明:
    ``read_gamma_par_value`` 读取参数的首个数值；``gamma_par_shape`` 解析地理或
    雷达栅格形状；``read_binary_raster`` 与 ``read_complex_binary_raster`` 校验
    文件大小后只读加载；``radar_indices_from_lookup`` 将目标地理范围映射为唯一
    雷达像元索引。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np


def _parse_gamma_parameters(path: str | Path) -> dict[str, str]:
    """Parse colon-separated GAMMA parameters while retaining full values."""

    parameter_path = Path(path)
    if not parameter_path.is_file():
        raise FileNotFoundError(f"parameter file not found: {parameter_path}")
    parameters: dict[str, str] = {}
    for raw_line in parameter_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        if key:
            parameters[key] = value.strip()
    if not parameters:
        raise ValueError(f"no parameters parsed from {parameter_path}")
    return parameters


def _parameter_number(
    parameters: dict[str, str], key: str, cast: type, source: str | Path
):
    """Return the first required parameter token cast to one numeric type."""

    normalised_key = key.rstrip(":")
    value = parameters.get(normalised_key, "")
    if not value.split():
        raise ValueError(f"Missing key {key} in {source}")
    try:
        return cast(value.split()[0])
    except ValueError as error:
        raise ValueError(f"invalid GAMMA parameter {key}: {value!r}") from error


def read_gamma_par_value(par_path: str | Path, key: str) -> float:
    """Read the first numeric value associated with one GAMMA parameter key."""

    return float(_parameter_number(_parse_gamma_parameters(par_path), key, float, par_path))


def gamma_par_shape(par_file: str | Path) -> tuple[int, int]:
    """Return ``(rows, columns)`` for a geographic or radar GAMMA grid."""

    parameters = _parse_gamma_parameters(par_file)
    if "width" in parameters and "nlines" in parameters:
        return (
            int(_parameter_number(parameters, "nlines", int, par_file)),
            int(_parameter_number(parameters, "width", int, par_file)),
        )
    if "range_samples" in parameters and "azimuth_lines" in parameters:
        return (
            int(_parameter_number(parameters, "azimuth_lines", int, par_file)),
            int(_parameter_number(parameters, "range_samples", int, par_file)),
        )
    raise ValueError(
        f"cannot infer raster shape from {par_file}; expected width/nlines "
        "or range_samples/azimuth_lines"
    )


def _real_dtype(dtype: str, endian: str) -> np.dtype:
    """Build an explicit real dtype using the requested byte order."""

    if endian not in {"big", "little"}:
        raise ValueError("endian must be 'big' or 'little'")
    try:
        result = np.dtype(dtype)
    except TypeError as error:
        raise ValueError(f"invalid raster dtype: {dtype!r}") from error
    if result.kind not in {"f", "i", "u"}:
        raise ValueError("dtype must be a real numeric type")
    return result.newbyteorder(">" if endian == "big" else "<")


def read_binary_raster(
    path: str | Path,
    shape: tuple[int, int],
    dtype: str = "float32",
    endian: str = "big",
    memmap: bool = False,
) -> np.ndarray:
    """Read one exact-size headerless real raster with explicit representation."""

    raster_dtype = _real_dtype(dtype, endian)
    expected = int(shape[0]) * int(shape[1])
    actual = Path(path).stat().st_size
    expected_bytes = expected * raster_dtype.itemsize
    if actual != expected_bytes:
        raise ValueError(
            f"read size mismatch: {path}, got {actual} bytes, expected {expected_bytes}"
        )
    if memmap:
        return np.memmap(path, dtype=raster_dtype, mode="r", shape=shape)
    return np.fromfile(path, dtype=raster_dtype).reshape(shape)


def read_complex_binary_raster(
    path: str | Path,
    shape: tuple[int, int],
    dtype: str = "float32",
    endian: str = "big",
    memmap: bool = False,
) -> np.ndarray:
    """Read one exact-size real/imaginary-interleaved complex raster."""

    raster_dtype = _real_dtype(dtype, endian)
    expected = int(shape[0]) * int(shape[1]) * 2
    actual = Path(path).stat().st_size
    expected_bytes = expected * raster_dtype.itemsize
    if actual != expected_bytes:
        raise ValueError(
            f"read size mismatch: {path}, got {actual} bytes, expected {expected_bytes}"
        )
    if memmap:
        complex_dtype = np.dtype(f"c{raster_dtype.itemsize * 2}").newbyteorder(
            ">" if endian == "big" else "<"
        )
        return np.memmap(path, dtype=complex_dtype, mode="r", shape=shape)
    data = np.fromfile(path, dtype=raster_dtype)
    component_dtype = np.float32 if raster_dtype.itemsize == 4 else np.float64
    components = data.reshape((-1, 2)).astype(component_dtype)
    output = components[:, 0] + 1j * components[:, 1]
    complex_dtype = np.complex64 if raster_dtype.itemsize == 4 else np.complex128
    return output.astype(complex_dtype, copy=False).reshape(shape)


def _gamma_geographic_grid(par_file: str | Path) -> dict[str, float | int]:
    """Read the regular geographic grid fields required for lookup sampling."""

    parameters = _parse_gamma_parameters(par_file)
    required = ("width", "nlines", "corner_lat", "corner_lon", "post_lat", "post_lon")
    if not all(key in parameters for key in required):
        raise ValueError(f"{par_file} is not a regular geographic GAMMA grid")
    return {
        "rows": int(_parameter_number(parameters, "nlines", int, par_file)),
        "cols": int(_parameter_number(parameters, "width", int, par_file)),
        "corner_lat": float(
            _parameter_number(parameters, "corner_lat", float, par_file)
        ),
        "corner_lon": float(
            _parameter_number(parameters, "corner_lon", float, par_file)
        ),
        "post_lat": float(_parameter_number(parameters, "post_lat", float, par_file)),
        "post_lon": float(_parameter_number(parameters, "post_lon", float, par_file)),
    }


def radar_indices_from_lookup(
    lookup: np.ndarray,
    geo_par_file: str | Path,
    bounds: Tuple[float, float, float, float],
    radar_shape: Tuple[int, int],
    radar_mask: Optional[np.ndarray] = None,
    region_shape: str = "ellipse",
    max_pixels: Optional[int] = None,
) -> np.ndarray:
    """Map geographic rectangle or ellipse bounds to unique flat radar indices."""

    grid = _gamma_geographic_grid(geo_par_file)
    geo_shape = (int(grid["rows"]), int(grid["cols"]))
    if lookup.shape != geo_shape:
        raise ValueError(f"lookup shape {lookup.shape} != geographic grid {geo_shape}")

    west, east, south, north = (float(value) for value in bounds)
    if not west < east or not south < north:
        raise ValueError("bounds must satisfy west < east and south < north")
    if region_shape not in {"ellipse", "rectangle"}:
        raise ValueError("region_shape must be 'ellipse' or 'rectangle'")
    if max_pixels is not None and int(max_pixels) < 1:
        raise ValueError("max_pixels must be positive")

    def index_limits(
        lower: float, upper: float, origin: float, spacing: float, size: int
    ) -> tuple[int, int]:
        if spacing == 0:
            raise ValueError("geographic grid spacing cannot be zero")
        indexes = ((lower - origin) / spacing, (upper - origin) / spacing)
        return (
            max(0, int(np.floor(min(indexes)))),
            min(size - 1, int(np.ceil(max(indexes)))),
        )

    col0, col1 = index_limits(
        west, east, float(grid["corner_lon"]), float(grid["post_lon"]), geo_shape[1]
    )
    row0, row1 = index_limits(
        south, north, float(grid["corner_lat"]), float(grid["post_lat"]), geo_shape[0]
    )
    if col0 > col1 or row0 > row1:
        return np.empty(0, dtype=np.int64)

    rows = np.arange(row0, row1 + 1)
    columns = np.arange(col0, col1 + 1)
    column_grid, row_grid = np.meshgrid(columns, rows)
    longitude = float(grid["corner_lon"]) + column_grid * float(grid["post_lon"])
    latitude = float(grid["corner_lat"]) + row_grid * float(grid["post_lat"])
    inside = (
        (longitude >= west)
        & (longitude <= east)
        & (latitude >= south)
        & (latitude <= north)
    )
    if region_shape == "ellipse":
        center_lon = (west + east) / 2.0
        center_lat = (south + north) / 2.0
        inside &= (
            ((longitude - center_lon) / ((east - west) / 2.0)) ** 2
            + ((latitude - center_lat) / ((north - south) / 2.0)) ** 2
            <= 1.0
        )

    values = np.asarray(lookup[row0 : row1 + 1, col0 : col1 + 1])[inside]
    finite = np.isfinite(values.real) & np.isfinite(values.imag)
    values = values[finite]
    radar_column = np.rint(values.real).astype(np.int64)
    radar_row = np.rint(values.imag).astype(np.int64)
    valid = (
        (radar_column >= 0)
        & (radar_column < radar_shape[1])
        & (radar_row >= 0)
        & (radar_row < radar_shape[0])
    )
    flat = np.unique(radar_row[valid] * radar_shape[1] + radar_column[valid])

    if radar_mask is not None:
        mask = np.asarray(radar_mask)
        if mask.shape != radar_shape:
            raise ValueError(f"radar mask shape {mask.shape} != SAR grid {radar_shape}")
        mask_values = mask.reshape(-1)[flat]
        flat = flat[np.isfinite(mask_values) & (mask_values > 0)]

    if max_pixels is not None and flat.size > int(max_pixels):
        selected = np.linspace(0, flat.size - 1, int(max_pixels), dtype=int)
        flat = flat[selected]
    return flat
