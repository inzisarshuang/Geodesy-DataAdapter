"""
gamma
=====

功能概述:
    只读解析地理编码 GAMMA 规则经纬网格、日期清单和无文件头二进制栅格，
    使用 NumPy memmap 按连续行读取；不推断 dtype、字节序、单位或参考。

函数说明:
    ``GammaGeoGridSource``:
        严格校验 par、tab、日期、DEM、mask 和每一期位移文件，并提供行块读取。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


def _parse_par(path: Path) -> dict[str, str]:
    """Parse colon-separated GAMMA parameters while preserving full values."""
    if not path.is_file():
        raise FileNotFoundError(f"GAMMA parameter file not found: {path}")
    parameters: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in raw_line:
            continue
        key, value = (part.strip() for part in raw_line.split(":", 1))
        if key:
            parameters[key] = value
    if not parameters:
        raise ValueError(f"no GAMMA parameters parsed from: {path}")
    return parameters


def _number(parameters: dict[str, str], key: str, cast: type) -> Any:
    """Read and cast the first token of one required GAMMA parameter."""
    if key not in parameters or not parameters[key].split():
        raise ValueError(f"GAMMA parameter {key!r} is missing")
    try:
        return cast(parameters[key].split()[0])
    except ValueError as error:
        raise ValueError(f"invalid GAMMA parameter {key}: {parameters[key]!r}") from error


def _read_noncomment_lines(path: Path) -> list[str]:
    """Read non-empty, non-comment lines from one required text manifest."""
    if not path.is_file():
        raise FileNotFoundError(f"manifest file not found: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _binary_dtype(name: str, byte_order: str, label: str) -> np.dtype:
    """Build an explicit fixed-size real numeric dtype and byte order."""
    try:
        dtype = np.dtype(name)
    except TypeError as error:
        raise ValueError(f"invalid {label}_dtype: {name!r}") from error
    if dtype.kind not in {"f", "i", "u"} or dtype.itemsize not in {1, 2, 4, 8}:
        raise ValueError(f"{label}_dtype must be a fixed-size real numeric type")
    if byte_order not in {"big", "little", "native"}:
        raise ValueError(f"{label}_byte_order must be big, little, or native")
    marker = {"big": ">", "little": "<", "native": "="}[byte_order]
    return dtype.newbyteorder(marker)


class GammaGeoGridSource:
    """Read a geocoded GAMMA binary grid stack through bounded memmap slices."""

    def __init__(
        self,
        tab_file: str | Path,
        dates_file: str | Path,
        parameter_file: str | Path,
        height_file: str | Path,
        mask_file: str | Path,
        *,
        longitude_file: str | Path | None = None,
        latitude_file: str | Path | None = None,
        longitude_dtype: str | None = None,
        longitude_byte_order: str | None = None,
        latitude_dtype: str | None = None,
        latitude_byte_order: str | None = None,
        deformation_dtype: str,
        deformation_byte_order: str,
        height_dtype: str,
        height_byte_order: str,
        mask_dtype: str,
        mask_byte_order: str,
    ) -> None:
        """Resolve all inputs and require explicit binary representations."""
        self.tab_path = Path(tab_file).expanduser().resolve()
        self.dates_path = Path(dates_file).expanduser().resolve()
        self.parameter_path = Path(parameter_file).expanduser().resolve()
        self.height_path = Path(height_file).expanduser().resolve()
        self.mask_path = Path(mask_file).expanduser().resolve()
        self.longitude_path = (
            Path(longitude_file).expanduser().resolve()
            if longitude_file is not None
            else None
        )
        self.latitude_path = (
            Path(latitude_file).expanduser().resolve()
            if latitude_file is not None
            else None
        )
        if (self.longitude_path is None) != (self.latitude_path is None):
            raise ValueError("longitude_file and latitude_file must be supplied together")
        if self.longitude_path is not None:
            if None in {
                longitude_dtype,
                longitude_byte_order,
                latitude_dtype,
                latitude_byte_order,
            }:
                raise ValueError("explicit coordinate dtype and byte order are required")
            self.longitude_dtype = _binary_dtype(
                str(longitude_dtype), str(longitude_byte_order), "longitude"
            )
            self.latitude_dtype = _binary_dtype(
                str(latitude_dtype), str(latitude_byte_order), "latitude"
            )
        else:
            self.longitude_dtype = None
            self.latitude_dtype = None
        self.deformation_dtype = _binary_dtype(
            deformation_dtype, deformation_byte_order, "deformation"
        )
        self.height_dtype = _binary_dtype(height_dtype, height_byte_order, "height")
        self.mask_dtype = _binary_dtype(mask_dtype, mask_byte_order, "mask")
        self.deformation_paths: tuple[Path, ...] = ()
        self.dates: tuple[str, ...] = ()
        self.rows = 0
        self.columns = 0
        self.x = np.empty(0, dtype=np.float64)
        self.y = np.empty(0, dtype=np.float64)
        self.declared_crs: str | None = None
        self._active = False

    def __enter__(self) -> "GammaGeoGridSource":
        """Validate manifests, grid metadata, and every binary file size."""
        self._validate()
        self._active = True
        return self

    def _validate(self) -> None:
        """Validate a regular lon/lat grid without reading any complete raster."""
        parameters = _parse_par(self.parameter_path)
        required_grid = {
            "width",
            "nlines",
            "corner_lon",
            "corner_lat",
            "post_lon",
            "post_lat",
        }
        regular = required_grid.issubset(parameters)
        if regular:
            self.columns = int(_number(parameters, "width", int))
            self.rows = int(_number(parameters, "nlines", int))
        elif self.longitude_path is not None and {
            "range_samples",
            "azimuth_lines",
        }.issubset(parameters):
            self.columns = int(_number(parameters, "range_samples", int))
            self.rows = int(_number(parameters, "azimuth_lines", int))
        else:
            missing = sorted(required_grid.difference(parameters))
            raise ValueError(
                "GAMMA parameter file is not a regular geocoded grid and no "
                f"explicit radar-grid coordinates were supplied; missing: {missing}"
            )
        if self.rows < 1 or self.columns < 1:
            raise ValueError("GAMMA width and nlines must be positive")
        if regular and self.longitude_path is None:
            corner_lon = float(_number(parameters, "corner_lon", float))
            corner_lat = float(_number(parameters, "corner_lat", float))
            post_lon = float(_number(parameters, "post_lon", float))
            post_lat = float(_number(parameters, "post_lat", float))
            if not np.isfinite([corner_lon, corner_lat, post_lon, post_lat]).all():
                raise ValueError("GAMMA grid coordinates must be finite")
            if post_lon == 0 or post_lat == 0:
                raise ValueError("GAMMA post_lon and post_lat must be non-zero")
            self.x = corner_lon + np.arange(self.columns, dtype=np.float64) * post_lon
            self.y = corner_lat + np.arange(self.rows, dtype=np.float64) * post_lat
        else:
            assert self.longitude_path is not None
            assert self.latitude_path is not None
            assert self.longitude_dtype is not None
            assert self.latitude_dtype is not None
            self._validate_binary_size(
                self.longitude_path, self.longitude_dtype, "longitude"
            )
            self._validate_binary_size(
                self.latitude_path, self.latitude_dtype, "latitude"
            )
            self.x = np.empty((self.rows, self.columns), dtype=np.float64)
            self.y = np.empty((self.rows, self.columns), dtype=np.float64)
        if "EPSG" in parameters:
            epsg = str(_number(parameters, "EPSG", int))
            self.declared_crs = f"EPSG:{epsg}"

        tab_lines = _read_noncomment_lines(self.tab_path)
        date_lines = _read_noncomment_lines(self.dates_path)
        if not tab_lines:
            raise ValueError("GAMMA tab_file contains no deformation paths")
        if len(tab_lines) != len(date_lines):
            raise ValueError(
                "GAMMA tab_file and dates_file must contain the same number of entries"
            )
        paths: list[Path] = []
        for line in tab_lines:
            token = line.split()[0]
            candidate = Path(token).expanduser()
            if not candidate.is_absolute():
                candidate = self.tab_path.parent / candidate
            paths.append(candidate.resolve())
        if len(paths) != len(set(paths)):
            raise ValueError("GAMMA tab_file contains duplicate deformation paths")
        self.deformation_paths = tuple(paths)

        dates: list[str] = []
        for line in date_lines:
            if len(line.split()) != 1:
                raise ValueError("GAMMA dates_file requires exactly one YYYYMMDD per line")
            date = line.strip()
            try:
                datetime.strptime(date, "%Y%m%d")
            except ValueError as error:
                raise ValueError(f"invalid GAMMA YYYYMMDD date: {date!r}") from error
            dates.append(date)
        if len(dates) != len(set(dates)):
            raise ValueError("GAMMA dates_file contains duplicate dates")
        self.dates = tuple(dates)

        for path in self.deformation_paths:
            self._validate_binary_size(path, self.deformation_dtype, "deformation")
        self._validate_binary_size(self.height_path, self.height_dtype, "height")
        self._validate_binary_size(self.mask_path, self.mask_dtype, "mask")

    def _validate_binary_size(self, path: Path, dtype: np.dtype, label: str) -> None:
        """Require one headerless raster to match rows, columns, and dtype exactly."""
        if not path.is_file():
            raise FileNotFoundError(f"GAMMA {label} file not found: {path}")
        expected = self.rows * self.columns * dtype.itemsize
        actual = path.stat().st_size
        if actual != expected:
            raise ValueError(
                f"GAMMA {label} size mismatch for {path}: {actual} != {expected} bytes"
            )

    def _row_range(self, row_start: int, row_stop: int) -> tuple[int, int]:
        """Validate one non-empty half-open row range while the source is active."""
        if not self._active:
            raise RuntimeError("GAMMA source is not active")
        start, stop = int(row_start), int(row_stop)
        if start < 0 or stop <= start or stop > self.rows:
            raise ValueError(f"invalid row range [{start}:{stop}] for {self.rows} rows")
        return start, stop

    def _read_rows(
        self, path: Path, dtype: np.dtype, row_start: int, row_stop: int
    ) -> np.ndarray:
        """Map one binary raster read-only and copy only the requested rows."""
        start, stop = self._row_range(row_start, row_stop)
        mapped = np.memmap(
            path, dtype=dtype, mode="r", shape=(self.rows, self.columns)
        )
        return np.asarray(mapped[start:stop, :], dtype=np.float32).copy()

    def read_deformation_rows(
        self, epoch_index: int, row_start: int, row_stop: int
    ) -> np.ndarray:
        """Read one epoch row block without unit scaling or nodata replacement."""
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= len(self.dates):
            raise IndexError(f"epoch_index out of range: {epoch}")
        return self._read_rows(
            self.deformation_paths[epoch],
            self.deformation_dtype,
            row_start,
            row_stop,
        )

    def read_height_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read one real-elevation row block from the explicit DEM binary."""
        return self._read_rows(
            self.height_path, self.height_dtype, row_start, row_stop
        )

    def read_mask_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read validity where the explicit GAMMA mask is finite and positive."""
        values = self._read_rows(
            self.mask_path, self.mask_dtype, row_start, row_stop
        )
        return np.isfinite(values) & (values > 0)

    def read_longitude_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read explicit longitude rows for a radar-coordinate grid."""
        if self.longitude_path is None or self.longitude_dtype is None:
            raise ValueError("explicit longitude_file is not configured")
        start, stop = self._row_range(row_start, row_stop)
        mapped = np.memmap(
            self.longitude_path,
            dtype=self.longitude_dtype,
            mode="r",
            shape=(self.rows, self.columns),
        )
        return np.asarray(mapped[start:stop, :], dtype=np.float64).copy()

    def read_latitude_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read explicit latitude rows for a radar-coordinate grid."""
        if self.latitude_path is None or self.latitude_dtype is None:
            raise ValueError("explicit latitude_file is not configured")
        start, stop = self._row_range(row_start, row_stop)
        mapped = np.memmap(
            self.latitude_path,
            dtype=self.latitude_dtype,
            mode="r",
            shape=(self.rows, self.columns),
        )
        return np.asarray(mapped[start:stop, :], dtype=np.float64).copy()

    def close(self) -> None:
        """Deactivate the source; memmaps are scoped to individual row reads."""
        self._active = False

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Deactivate the read-only source on context exit."""
        self.close()
