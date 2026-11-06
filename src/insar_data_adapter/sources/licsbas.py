"""
licsbas
=======

功能概述:
    只读访问 LiCSBAS 累积形变、内嵌 DEM、质量掩膜和经纬度规则网格，按连续
    行切片返回数据；不推断单位、CRS、LOS 方向或时间参考。

函数说明:
    ``LiCSBASGridSource``:
        校验 LiCSBAS HDF5 的尺寸、日期、坐标和参考区，并提供受控内存读取。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

import h5py
import numpy as np


_REFAREA_PATTERN = re.compile(r"^(\d+):(\d+)/(\d+):(\d+)$")


def _text(value: Any) -> str:
    """Decode one HDF5 scalar or attribute without changing its meaning."""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class LiCSBASGridSource:
    """Read one native LiCSBAS grid time series without loading its full cube."""

    def __init__(
        self,
        input_file: str | Path,
        *,
        deformation_dataset: str = "cum",
        date_dataset: str = "imdates",
        height_dataset: str = "hgt",
        mask_dataset: str = "mask",
        refarea_dataset: str = "refarea",
    ) -> None:
        """Retain a resolved input path and explicit dataset names."""
        self.path = Path(input_file).expanduser().resolve()
        self.deformation_dataset = deformation_dataset.strip("/")
        self.date_dataset = date_dataset.strip("/")
        self.height_dataset = height_dataset.strip("/")
        self.mask_dataset = mask_dataset.strip("/")
        self.refarea_dataset = refarea_dataset.strip("/")
        if not all(
            (
                self.deformation_dataset,
                self.date_dataset,
                self.height_dataset,
                self.mask_dataset,
                self.refarea_dataset,
            )
        ):
            raise ValueError("LiCSBAS dataset names must not be blank")
        self._handle: h5py.File | None = None
        self.dates: tuple[str, ...] = ()
        self.rows = 0
        self.columns = 0
        self.x = np.empty(0, dtype=np.float64)
        self.y = np.empty(0, dtype=np.float64)
        self.spatial_reference = ""
        self.declared_unit: str | None = None
        self.declared_crs: str | None = None

    def __enter__(self) -> "LiCSBASGridSource":
        """Open the LiCSBAS HDF5 read-only and validate its lightweight metadata."""
        try:
            self._handle = h5py.File(self.path, "r")
            self._validate()
        except Exception:
            self.close()
            raise
        return self

    def _require_handle(self) -> h5py.File:
        """Return the active read-only HDF5 handle."""
        if self._handle is None:
            raise RuntimeError("LiCSBAS source is not active")
        return self._handle

    def _validate(self) -> None:
        """Validate datasets, dates, pixel-centre axes, and the spatial reference area."""
        handle = self._require_handle()
        required = {
            self.deformation_dataset,
            self.date_dataset,
            self.height_dataset,
            self.mask_dataset,
            "corner_lon",
            "corner_lat",
            "post_lon",
            "post_lat",
            self.refarea_dataset,
        }
        missing = sorted(required.difference(handle.keys()))
        if missing:
            raise ValueError(f"LiCSBAS HDF5 is missing datasets: {missing}")
        deformation = handle[self.deformation_dataset]
        if deformation.ndim != 3:
            raise ValueError(
                f"LiCSBAS deformation must be [time,row,column], got {deformation.shape}"
            )
        self.rows, self.columns = (int(value) for value in deformation.shape[1:])
        dates = handle[self.date_dataset]
        if dates.ndim != 1 or len(dates) != deformation.shape[0]:
            raise ValueError("LiCSBAS deformation/date dimensions are inconsistent")
        self.dates = tuple(_text(value).strip() for value in dates[...])
        for date in self.dates:
            try:
                datetime.strptime(date, "%Y%m%d")
            except ValueError as error:
                raise ValueError(f"invalid LiCSBAS YYYYMMDD date: {date!r}") from error
        if len(set(self.dates)) != len(self.dates):
            raise ValueError("LiCSBAS date dataset contains duplicate dates")

        expected_shape = (self.rows, self.columns)
        if handle[self.height_dataset].shape != expected_shape:
            raise ValueError("LiCSBAS height shape does not match deformation grid")
        if handle[self.mask_dataset].shape != expected_shape:
            raise ValueError("LiCSBAS mask shape does not match deformation grid")

        corner_lon = float(handle["corner_lon"][()])
        corner_lat = float(handle["corner_lat"][()])
        post_lon = float(handle["post_lon"][()])
        post_lat = float(handle["post_lat"][()])
        if not np.isfinite([corner_lon, corner_lat, post_lon, post_lat]).all():
            raise ValueError("LiCSBAS grid coordinates must be finite")
        if post_lon == 0 or post_lat == 0:
            raise ValueError("LiCSBAS post_lon and post_lat must be non-zero")
        self.x = corner_lon + np.arange(self.columns, dtype=np.float64) * post_lon
        self.y = corner_lat + np.arange(self.rows, dtype=np.float64) * post_lat

        refarea = _text(handle[self.refarea_dataset][()]).strip()
        match = _REFAREA_PATTERN.fullmatch(refarea)
        if match is None:
            raise ValueError(f"invalid LiCSBAS refarea: {refarea!r}")
        x_start, x_stop, y_start, y_stop = (int(value) for value in match.groups())
        if not (
            0 <= x_start < x_stop <= self.columns
            and 0 <= y_start < y_stop <= self.rows
        ):
            raise ValueError("LiCSBAS refarea is outside the deformation grid")
        self.spatial_reference = f"licsbas_refarea={refarea}"

        unit = deformation.attrs.get(
            "UNIT",
            deformation.attrs.get(
                "unit", handle.attrs.get("UNIT", handle.attrs.get("unit"))
            ),
        )
        self.declared_unit = _text(unit).strip() if unit is not None else None
        crs = handle.attrs.get("CRS", handle.attrs.get("crs", handle.attrs.get("EPSG")))
        if crs is not None:
            value = _text(crs).strip()
            if value.isdigit():
                value = f"EPSG:{value}"
            elif value.upper().startswith("EPSG:"):
                value = value.upper()
            self.declared_crs = value

    def _row_range(self, row_start: int, row_stop: int) -> tuple[int, int]:
        """Validate one non-empty, half-open source row interval."""
        start, stop = int(row_start), int(row_stop)
        if start < 0 or stop <= start or stop > self.rows:
            raise ValueError(f"invalid row range [{start}:{stop}] for {self.rows} rows")
        return start, stop

    def read_deformation_rows(
        self, epoch_index: int, row_start: int, row_stop: int
    ) -> np.ndarray:
        """Read one cumulative-deformation row block as float32 without scaling."""
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= len(self.dates):
            raise IndexError(f"epoch_index out of range: {epoch}")
        start, stop = self._row_range(row_start, row_stop)
        return np.asarray(
            self._require_handle()[self.deformation_dataset][epoch, start:stop, :],
            dtype=np.float32,
        )

    def read_height_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read one embedded LiCSBAS DEM row block as float32."""
        start, stop = self._row_range(row_start, row_stop)
        return np.asarray(
            self._require_handle()[self.height_dataset][start:stop, :], dtype=np.float32
        )

    def read_mask_rows(self, row_start: int, row_stop: int) -> np.ndarray:
        """Read validity where the LiCSBAS mask is finite and strictly positive."""
        start, stop = self._row_range(row_start, row_stop)
        values = np.asarray(
            self._require_handle()[self.mask_dataset][start:stop, :], dtype=np.float32
        )
        return np.isfinite(values) & (values > 0)

    def close(self) -> None:
        """Close the active source handle if present."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the read-only source on normal or exceptional context exit."""
        self.close()
