"""
canonical
=========

功能概述:
    分块读写标准规则栅格 HDF5，并在完整校验后原子替换目标；不解析上游格式，
    不执行单位缩放、重投影、插值或时间/空间参考变换。

函数说明:
    ``GridMetadata``:
        保存标准规则栅格产品必须显式记录的科学元数据。
    ``CanonicalGridWriter``:
        按时期和连续行块写入形变及几何数据，拒绝重叠和不完整输出。
    ``CanonicalGridReader``:
        只读打开标准规则栅格，提供单时期、行块和几何切片读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence

import h5py
import numpy as np

from .hdf5 import inspect_hdf5


GRID_SCHEMA = "insar_grid_timeseries/1.0"
_TARGET_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class GridMetadata:
    """Record required scientific metadata without applying any transformation."""

    source_format: str
    deformation_unit: str
    deformation_quantity: str
    los_positive: str
    crs: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str
    height_unit: str = "m"
    grid_registration: str = "pixel"

    def validate(self) -> None:
        """Reject blank or unsupported metadata values before creating output."""
        for name, value in self.__dict__.items():
            if not str(value).strip():
                raise ValueError(f"metadata field {name} must not be blank")
        if self.deformation_quantity not in {"cumulative_displacement", "velocity"}:
            raise ValueError(
                "deformation_quantity must be cumulative_displacement or velocity"
            )
        if self.grid_registration not in {"pixel", "gridline"}:
            raise ValueError("grid_registration must be pixel or gridline")


def _validate_axis(values: Sequence[float], expected_size: int, name: str) -> np.ndarray:
    """Return one finite, strictly monotonic float64 coordinate axis."""
    axis = np.asarray(values, dtype=np.float64)
    if axis.shape != (expected_size,):
        raise ValueError(f"{name} must have shape ({expected_size},), got {axis.shape}")
    if not np.isfinite(axis).all():
        raise ValueError(f"{name} contains NaN or infinite coordinates")
    differences = np.diff(axis)
    if differences.size and not (np.all(differences > 0) or np.all(differences < 0)):
        raise ValueError(f"{name} must be strictly monotonic")
    return axis


def _validate_dates(dates: Sequence[str]) -> tuple[str, ...]:
    """Normalize YYYYMMDD dates while allowing distinct same-day epoch identities."""
    normalized = tuple(str(value) for value in dates)
    if not normalized:
        raise ValueError("at least one acquisition date is required")
    for value in normalized:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as error:
            raise ValueError(f"invalid YYYYMMDD acquisition date: {value}") from error
    return normalized


class CanonicalGridWriter:
    """Write one canonical grid product by non-overlapping row blocks."""

    def __init__(
        self,
        output_file: str | Path,
        dates: Sequence[str],
        rows: int,
        columns: int,
        x: Sequence[float],
        y: Sequence[float],
        metadata: GridMetadata,
        *,
        chunk_rows: int = 256,
        compression: str | None = "gzip",
        compression_level: int = 4,
        include_lonlat: bool = False,
        overwrite: bool = False,
    ) -> None:
        """Validate dimensions and retain options without creating any file yet."""
        self.output = Path(output_file).expanduser().resolve()
        self.dates = _validate_dates(dates)
        self.rows = int(rows)
        self.columns = int(columns)
        if self.rows < 1 or self.columns < 1:
            raise ValueError("rows and columns must be positive")
        self.x = _validate_axis(x, self.columns, "x")
        self.y = _validate_axis(y, self.rows, "y")
        metadata.validate()
        self.metadata = metadata
        if chunk_rows < 1:
            raise ValueError("chunk_rows must be positive")
        if compression not in {None, "gzip", "lzf"}:
            raise ValueError("compression must be none, gzip, or lzf")
        if compression == "gzip" and not 0 <= compression_level <= 9:
            raise ValueError("compression_level must be between 0 and 9")
        bytes_per_row = self.columns * np.dtype("float32").itemsize
        memory_limited_rows = max(1, _TARGET_CHUNK_BYTES // bytes_per_row)
        self.chunk_rows = min(int(chunk_rows), self.rows, memory_limited_rows)
        self.compression = compression
        self.compression_level = int(compression_level)
        self.include_lonlat = bool(include_lonlat)
        self.overwrite = bool(overwrite)
        self._handle: h5py.File | None = None
        self._temporary: Path | None = None
        self._deformation_written = np.zeros((len(self.dates), self.rows), dtype=bool)
        self._geometry_written = np.zeros(self.rows, dtype=bool)
        self._lonlat_written = np.zeros(self.rows, dtype=bool)
        self._completed = False

    def __enter__(self) -> "CanonicalGridWriter":
        """Create a unique sibling HDF5 temporary file and initialize its schema."""
        if self._handle is not None or self._completed:
            raise RuntimeError("writer cannot be entered more than once")
        if self.output.exists() and not self.overwrite:
            raise FileExistsError(f"output already exists: {self.output}")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.output.name}.", suffix=".tmp", dir=self.output.parent
        )
        os.close(descriptor)
        self._temporary = Path(temporary_name)
        self._temporary.unlink()
        self._handle = h5py.File(self._temporary, "w")
        self._initialize_file()
        return self

    def _dataset_options(self) -> dict[str, Any]:
        """Return compression options shared by chunked numeric datasets."""
        options: dict[str, Any] = {
            "compression": self.compression,
            "shuffle": self.compression is not None,
            "fletcher32": True,
        }
        if self.compression == "gzip":
            options["compression_opts"] = self.compression_level
        return options

    def _initialize_file(self) -> None:
        """Create required attributes and empty chunked datasets."""
        handle = self._require_handle()
        handle.attrs.update(
            {
                "insar_schema": GRID_SCHEMA,
                "source_format": self.metadata.source_format,
                "deformation_unit": self.metadata.deformation_unit,
                "deformation_quantity": self.metadata.deformation_quantity,
                "los_positive": self.metadata.los_positive,
                "crs": self.metadata.crs,
                "nodata_policy": self.metadata.nodata_policy,
                "temporal_reference": self.metadata.temporal_reference,
                "spatial_reference": self.metadata.spatial_reference,
                "source_provenance": self.metadata.source_provenance,
                "height_unit": self.metadata.height_unit,
                "grid_registration": self.metadata.grid_registration,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "write_complete": False,
            }
        )
        text_dtype = h5py.string_dtype(encoding="utf-8")
        handle.create_dataset("time/date_yyyymmdd", data=self.dates, dtype=text_dtype)
        handle.create_dataset(
            "time/epoch_id", data=np.arange(1, len(self.dates) + 1, dtype=np.int64)
        )
        handle.create_dataset("geometry/x", data=self.x)
        handle.create_dataset("geometry/y", data=self.y)
        grid_chunks = (self.chunk_rows, self.columns)
        options = self._dataset_options()
        handle.create_dataset(
            "data/displacement",
            shape=(len(self.dates), self.rows, self.columns),
            dtype="float32",
            chunks=(1, *grid_chunks),
            fillvalue=np.nan,
            **options,
        )
        handle.create_dataset(
            "geometry/height",
            shape=(self.rows, self.columns),
            dtype="float32",
            chunks=grid_chunks,
            fillvalue=np.nan,
            **options,
        )
        handle.create_dataset(
            "geometry/valid_mask",
            shape=(self.rows, self.columns),
            dtype="uint8",
            chunks=grid_chunks,
            fillvalue=0,
            **options,
        )
        if self.include_lonlat:
            for name in ("longitude", "latitude"):
                handle.create_dataset(
                    f"geometry/{name}",
                    shape=(self.rows, self.columns),
                    dtype="float64",
                    chunks=grid_chunks,
                    fillvalue=np.nan,
                    **options,
                )

    def _require_handle(self) -> h5py.File:
        """Return the active output handle or reject use outside its context."""
        if self._handle is None:
            raise RuntimeError("writer is not active")
        return self._handle

    def _row_bounds(self, row_start: int, block_rows: int) -> tuple[int, int]:
        """Validate one contiguous row block and return its half-open bounds."""
        start = int(row_start)
        stop = start + int(block_rows)
        if start < 0 or block_rows < 1 or stop > self.rows:
            raise ValueError(f"invalid row block [{start}:{stop}] for {self.rows} rows")
        return start, stop

    def write_deformation_rows(
        self, epoch_index: int, row_start: int, values: np.ndarray
    ) -> None:
        """Write full-column deformation rows for one zero-based epoch index."""
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= len(self.dates):
            raise IndexError(f"epoch_index out of range: {epoch}")
        block = np.asarray(values, dtype=np.float32)
        if block.ndim != 2 or block.shape[1] != self.columns:
            raise ValueError(
                f"deformation block must have shape (rows, {self.columns}), got {block.shape}"
            )
        start, stop = self._row_bounds(row_start, block.shape[0])
        if self._deformation_written[epoch, start:stop].any():
            raise ValueError(f"deformation rows overlap an existing block: epoch {epoch}")
        self._require_handle()["data/displacement"][epoch, start:stop, :] = block
        self._deformation_written[epoch, start:stop] = True

    def write_epoch(self, epoch_index: int, values: np.ndarray) -> None:
        """Write one complete epoch as a convenience for moderate-size grids."""
        self.write_deformation_rows(epoch_index, 0, values)

    def write_geometry_rows(
        self,
        row_start: int,
        height: np.ndarray,
        valid_mask: np.ndarray,
        *,
        longitude: np.ndarray | None = None,
        latitude: np.ndarray | None = None,
    ) -> None:
        """Write height, validity, and optional curvilinear coordinates by row block."""
        height_block = np.asarray(height, dtype=np.float32)
        mask_block = np.asarray(valid_mask, dtype=bool)
        if height_block.ndim != 2 or height_block.shape[1] != self.columns:
            raise ValueError(
                f"height block must have shape (rows, {self.columns}), got {height_block.shape}"
            )
        if mask_block.shape != height_block.shape:
            raise ValueError("valid_mask block must match the height block shape")
        start, stop = self._row_bounds(row_start, height_block.shape[0])
        if self._geometry_written[start:stop].any():
            raise ValueError("geometry rows overlap an existing block")
        if np.any(mask_block & ~np.isfinite(height_block)):
            raise ValueError("valid_mask marks non-finite height values as valid")
        handle = self._require_handle()
        handle["geometry/height"][start:stop, :] = height_block
        handle["geometry/valid_mask"][start:stop, :] = mask_block.astype(np.uint8)
        self._geometry_written[start:stop] = True

        coordinates_supplied = longitude is not None or latitude is not None
        if self.include_lonlat != coordinates_supplied:
            raise ValueError(
                "longitude and latitude must be supplied together for every geometry block "
                "when include_lonlat is true"
            )
        if self.include_lonlat:
            lon_block = np.asarray(longitude, dtype=np.float64)
            lat_block = np.asarray(latitude, dtype=np.float64)
            if lon_block.shape != height_block.shape or lat_block.shape != height_block.shape:
                raise ValueError("longitude/latitude blocks must match the height block shape")
            if not np.isfinite(lon_block[mask_block]).all() or not np.isfinite(
                lat_block[mask_block]
            ).all():
                raise ValueError("valid longitude/latitude cells must be finite")
            handle["geometry/longitude"][start:stop, :] = lon_block
            handle["geometry/latitude"][start:stop, :] = lat_block
            self._lonlat_written[start:stop] = True

    def finalize(self) -> Path:
        """Validate completeness, close the temporary file, and atomically publish it."""
        if self._completed:
            return self.output
        handle = self._require_handle()
        if not self._deformation_written.all():
            missing = int(np.count_nonzero(~self._deformation_written))
            raise ValueError(f"cannot finalize: {missing} deformation epoch-row blocks are missing")
        if not self._geometry_written.all():
            missing = int(np.count_nonzero(~self._geometry_written))
            raise ValueError(f"cannot finalize: {missing} geometry rows are missing")
        if self.include_lonlat and not self._lonlat_written.all():
            missing = int(np.count_nonzero(~self._lonlat_written))
            raise ValueError(f"cannot finalize: {missing} longitude/latitude rows are missing")
        handle.attrs["write_complete"] = True
        handle.flush()
        handle.close()
        self._handle = None
        if self._temporary is None:
            raise RuntimeError("writer temporary path is unavailable")
        inspect_hdf5(self._temporary, expected_format="standard", require_unit=True)
        if self.output.exists() and not self.overwrite:
            raise FileExistsError(f"output appeared during write: {self.output}")
        os.replace(self._temporary, self.output)
        self._temporary = None
        self._completed = True
        return self.output

    def abort(self) -> None:
        """Close and remove only this writer's unpublished temporary file."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._temporary is not None:
            self._temporary.unlink(missing_ok=True)
            self._temporary = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Finalize a successful context or discard its private temporary file."""
        if exc_type is not None:
            self.abort()
            return
        try:
            self.finalize()
        except Exception:
            self.abort()
            raise


class CanonicalGridReader:
    """Read selected epochs and row ranges from one validated canonical grid."""

    def __init__(self, input_file: str | Path) -> None:
        """Retain a resolved input path without opening it."""
        self.path = Path(input_file).expanduser().resolve()
        self.summary = None
        self._handle: h5py.File | None = None

    def __enter__(self) -> "CanonicalGridReader":
        """Validate the product and open a read-only HDF5 handle."""
        self.summary = inspect_hdf5(
            self.path, expected_format="standard", require_unit=True
        )
        if self.summary.layout != "grid":
            raise ValueError(f"canonical product is not a grid: {self.path}")
        self._handle = h5py.File(self.path, "r")
        return self

    def _require_handle(self) -> h5py.File:
        """Return the active read-only handle or reject use outside its context."""
        if self._handle is None:
            raise RuntimeError("reader is not active")
        return self._handle

    @property
    def metadata(self) -> GridMetadata:
        """Return all validated scientific metadata from the active canonical grid."""
        attributes = self._require_handle().attrs

        def text(name: str) -> str:
            """Normalize one required HDF5 text attribute without inference."""
            value = attributes[name]
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)

        metadata = GridMetadata(
            source_format=text("source_format"),
            deformation_unit=text("deformation_unit"),
            deformation_quantity=text("deformation_quantity"),
            los_positive=text("los_positive"),
            crs=text("crs"),
            nodata_policy=text("nodata_policy"),
            temporal_reference=text("temporal_reference"),
            spatial_reference=text("spatial_reference"),
            source_provenance=text("source_provenance"),
            height_unit=text("height_unit"),
            grid_registration=text("grid_registration"),
        )
        metadata.validate()
        return metadata

    @property
    def grid_registration(self) -> str:
        """Return the validated pixel or gridline registration of the active grid."""
        return self.metadata.grid_registration

    def read_axis(self, name: str) -> np.ndarray:
        """Read the complete one-dimensional X or Y coordinate axis."""
        if name not in {"x", "y"}:
            raise ValueError(f"unsupported coordinate axis: {name}")
        return self._require_handle()[f"geometry/{name}"][...]

    def read_epoch(
        self, epoch_index: int, row_start: int = 0, row_stop: int | None = None
    ) -> np.ndarray:
        """Read one zero-based epoch and optional half-open row range."""
        dataset = self._require_handle()["data/displacement"]
        epoch = int(epoch_index)
        stop = dataset.shape[1] if row_stop is None else int(row_stop)
        start = int(row_start)
        if epoch < 0 or epoch >= dataset.shape[0]:
            raise IndexError(f"epoch_index out of range: {epoch}")
        if start < 0 or stop <= start or stop > dataset.shape[1]:
            raise ValueError(f"invalid row range [{start}:{stop}]")
        return dataset[epoch, start:stop, :]

    def read_geometry_rows(
        self, name: str, row_start: int = 0, row_stop: int | None = None
    ) -> np.ndarray:
        """Read a row range from height, valid_mask, longitude, or latitude."""
        if name not in {"height", "valid_mask", "longitude", "latitude"}:
            raise ValueError(f"unsupported geometry dataset: {name}")
        handle = self._require_handle()
        dataset_name = f"geometry/{name}"
        if dataset_name not in handle:
            raise KeyError(f"optional geometry dataset is absent: {dataset_name}")
        dataset = handle[dataset_name]
        stop = dataset.shape[0] if row_stop is None else int(row_stop)
        start = int(row_start)
        if start < 0 or stop <= start or stop > dataset.shape[0]:
            raise ValueError(f"invalid row range [{start}:{stop}]")
        return dataset[start:stop, :]

    def close(self) -> None:
        """Close the active HDF5 handle if present."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the read-only handle when leaving its context."""
        self.close()
