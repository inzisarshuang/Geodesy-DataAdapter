"""
mintpy
======

功能概述:
    只读访问地理编码 MintPy 时序、DEM 和静态掩膜，按连续行切片返回数据；
    不缩放单位、不改变参考、不将零值自动解释为 nodata。

函数说明:
    ``MintPyGridSource``:
        校验三份输入的尺寸与关键元数据，并提供受控内存的行块读取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np


def _text(value: Any) -> str:
    """Decode one HDF5 scalar or attribute without changing its meaning."""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class MintPyGridSource:
    """Read one geocoded MintPy grid time series and explicit geometry inputs."""

    def __init__(
        self,
        timeseries_file: str | Path,
        geometry_file: str | Path | None = None,
        mask_file: str | Path | None = None,
        *,
        timeseries_dataset: str = "timeseries",
        date_dataset: str = "date",
        height_dataset: str = "height",
        mask_dataset: str = "mask",
    ) -> None:
        """Retain resolved paths; files are opened read-only by the context manager."""
        self.timeseries_path = Path(timeseries_file).expanduser().resolve()
        self.geometry_path = (
            Path(geometry_file).expanduser().resolve()
            if geometry_file is not None
            else None
        )
        self.mask_path = (
            Path(mask_file).expanduser().resolve() if mask_file is not None else None
        )
        self.timeseries_dataset = timeseries_dataset.strip("/")
        self.date_dataset = date_dataset.strip("/")
        self.height_dataset = height_dataset.strip("/")
        self.mask_dataset = mask_dataset.strip("/")
        if not all(
            (
                self.timeseries_dataset,
                self.date_dataset,
                self.height_dataset,
                self.mask_dataset,
            )
        ):
            raise ValueError("MintPy dataset names must not be blank")
        self._timeseries_handle: h5py.File | None = None
        self._geometry_handle: h5py.File | None = None
        self._mask_handle: h5py.File | None = None
        self.dates: tuple[str, ...] = ()
        self.rows = 0
        self.columns = 0
        self.x = np.empty(0, dtype=np.float64)
        self.y = np.empty(0, dtype=np.float64)
        self.deformation_unit = ""
        self.crs = ""
        self.temporal_reference = ""
        self.spatial_reference = ""

    def __enter__(self) -> "MintPyGridSource":
        """Open inputs read-only and validate all metadata before data access."""
        try:
            self._timeseries_handle = h5py.File(self.timeseries_path, "r")
            if self.geometry_path is not None:
                self._geometry_handle = h5py.File(self.geometry_path, "r")
            if self.mask_path is not None:
                if self.geometry_path == self.mask_path:
                    self._mask_handle = self._geometry_handle
                else:
                    self._mask_handle = h5py.File(self.mask_path, "r")
            self._validate()
        except Exception:
            self.close()
            raise
        return self

    def _validate(self) -> None:
        """Require geocoded axes, units, CRS, references, and consistent datasets."""
        handle = self._require_timeseries()
        if self.timeseries_dataset not in handle or self.date_dataset not in handle:
            raise ValueError(f"not a MintPy time-series HDF5: {self.timeseries_path}")
        displacement = handle[self.timeseries_dataset]
        if displacement.ndim != 3:
            raise ValueError(
                f"MintPy timeseries must be [time,row,column], got {displacement.shape}"
            )
        self.rows, self.columns = (int(value) for value in displacement.shape[1:])
        dates = handle[self.date_dataset]
        if dates.ndim != 1 or len(dates) != displacement.shape[0]:
            raise ValueError("MintPy date and time dimensions are inconsistent")
        self.dates = tuple(_text(value) for value in dates[...])

        attrs = handle.attrs
        required_attrs = {
            "X_FIRST",
            "X_STEP",
            "Y_FIRST",
            "Y_STEP",
            "EPSG",
            "REF_DATE",
            "REF_X",
            "REF_Y",
        }
        missing = sorted(required_attrs.difference(attrs.keys()))
        if missing:
            raise ValueError(f"MintPy geocoded metadata is missing attributes: {missing}")
        if "LENGTH" in attrs and int(attrs["LENGTH"]) != self.rows:
            raise ValueError("MintPy LENGTH does not match timeseries rows")
        if "WIDTH" in attrs and int(attrs["WIDTH"]) != self.columns:
            raise ValueError("MintPy WIDTH does not match timeseries columns")
        x_step = float(attrs["X_STEP"])
        y_step = float(attrs["Y_STEP"])
        if not np.isfinite([x_step, y_step]).all() or x_step == 0 or y_step == 0:
            raise ValueError("MintPy X_STEP and Y_STEP must be finite and non-zero")
        self.x = float(attrs["X_FIRST"]) + np.arange(self.columns, dtype=np.float64) * x_step
        self.y = float(attrs["Y_FIRST"]) + np.arange(self.rows, dtype=np.float64) * y_step
        unit = displacement.attrs.get(
            "UNIT",
            displacement.attrs.get("unit", attrs.get("UNIT", attrs.get("unit"))),
        )
        if unit is None or not _text(unit).strip():
            raise ValueError("MintPy deformation unit is missing")
        self.deformation_unit = _text(unit).strip()
        epsg = _text(attrs["EPSG"]).strip()
        if not epsg:
            raise ValueError("MintPy EPSG must not be blank")
        self.crs = f"EPSG:{epsg}" if epsg.isdigit() else epsg
        reference_date = _text(attrs["REF_DATE"]).strip()
        if reference_date not in self.dates:
            raise ValueError("MintPy REF_DATE is not present in the date dataset")
        reference_x_value = float(attrs["REF_X"])
        reference_y_value = float(attrs["REF_Y"])
        if not reference_x_value.is_integer() or not reference_y_value.is_integer():
            raise ValueError("MintPy REF_X and REF_Y must be integer pixel indices")
        reference_x, reference_y = int(reference_x_value), int(reference_y_value)
        if not 0 <= reference_x < self.columns or not 0 <= reference_y < self.rows:
            raise ValueError("MintPy reference pixel is outside the timeseries grid")
        self.temporal_reference = f"mintpy_REF_DATE={reference_date}"
        self.spatial_reference = f"mintpy_REF_Y={reference_y},REF_X={reference_x}"

        expected_shape = (self.rows, self.columns)
        if self._geometry_handle is not None:
            if self.height_dataset not in self._geometry_handle:
                raise ValueError(f"geometry dataset /{self.height_dataset} is missing")
            if self._geometry_handle[self.height_dataset].shape != expected_shape:
                raise ValueError("MintPy height shape does not match timeseries grid")
            for name in ("X_FIRST", "X_STEP", "Y_FIRST", "Y_STEP"):
                if name in self._geometry_handle.attrs and not np.isclose(
                    float(self._geometry_handle.attrs[name]), float(attrs[name])
                ):
                    raise ValueError(
                        f"MintPy geometry attribute {name} does not match timeseries"
                    )
            if "EPSG" in self._geometry_handle.attrs and _text(
                self._geometry_handle.attrs["EPSG"]
            ).strip() != epsg:
                raise ValueError("MintPy geometry attribute EPSG does not match timeseries")
        if self._mask_handle is not None:
            if self.mask_dataset not in self._mask_handle:
                raise ValueError(f"mask dataset /{self.mask_dataset} is missing")
            if self._mask_handle[self.mask_dataset].shape != expected_shape:
                raise ValueError("MintPy mask shape does not match timeseries grid")

    def _require_timeseries(self) -> h5py.File:
        """Return the active time-series handle."""
        if self._timeseries_handle is None:
            raise RuntimeError("MintPy source is not active")
        return self._timeseries_handle

    def _row_range(self, row_start: int, row_stop: int) -> tuple[int, int]:
        """Validate one non-empty, half-open source row interval."""
        start, stop = int(row_start), int(row_stop)
        if start < 0 or stop <= start or stop > self.rows:
            raise ValueError(f"invalid row range [{start}:{stop}] for {self.rows} rows")
        return start, stop

    def read_deformation_rows(
        self, epoch_index: int, row_start: int, row_stop: int
    ) -> np.ndarray:
        """Read one epoch row block and preserve source values as float32."""
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= len(self.dates):
            raise IndexError(f"epoch_index out of range: {epoch}")
        start, stop = self._row_range(row_start, row_stop)
        return np.asarray(
            self._require_timeseries()[self.timeseries_dataset][epoch, start:stop, :],
            dtype=np.float32,
        )

    def read_height_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read one DEM row block; an explicit geometry file is required."""
        if self._geometry_handle is None:
            raise ValueError("geometry_file is required to read MintPy height")
        start, stop = self._row_range(row_start, row_stop)
        return np.asarray(
            self._geometry_handle[self.height_dataset][start:stop, :], dtype=np.float32
        )

    def read_mask_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read one static validity-mask row block; non-zero means valid."""
        if self._mask_handle is None:
            raise ValueError("mask_file is required to read MintPy validity")
        start, stop = self._row_range(row_start, row_stop)
        return np.asarray(self._mask_handle[self.mask_dataset][start:stop, :], dtype=bool)

    def close(self) -> None:
        """Close each distinct HDF5 handle opened by this adapter."""
        if self._mask_handle is not None and self._mask_handle is not self._geometry_handle:
            self._mask_handle.close()
        if self._geometry_handle is not None:
            self._geometry_handle.close()
        if self._timeseries_handle is not None:
            self._timeseries_handle.close()
        self._mask_handle = None
        self._geometry_handle = None
        self._timeseries_handle = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close read-only sources on normal or exceptional context exit."""
        self.close()
