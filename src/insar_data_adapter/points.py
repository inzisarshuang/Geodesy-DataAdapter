"""
points
======

功能概述:
    按连续点块读写标准 PS/DS 稀疏点时序 HDF5，并在完整校验后原子发布；
    使用 O(time) 完成度状态，避免为大型时序分配 time×point 跟踪矩阵。

函数说明:
    ``PointMetadata``:
        保存点时序必须显式记录的科学元数据。
    ``PointQualitySpec``:
        声明点级或时变质量字段的名称、dtype、单位、说明和 nodata 规则。
    ``CanonicalPointWriter``:
        顺序写入静态点字段及每个时期的连续点块。
    ``CanonicalPointReader``:
        只读打开标准点时序并按显式点范围读取字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

from .hdf5 import inspect_hdf5


POINT_SCHEMA = "insar_point_timeseries/1.0"
_TARGET_CHUNK_BYTES = 1024 * 1024
_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PointMetadata:
    """Record required point-product science metadata without guessing values."""

    source_format: str
    deformation_unit: str
    deformation_quantity: str
    los_positive: str
    crs: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str
    height_unit: str

    def validate(self) -> None:
        """Reject blank or unsupported metadata before output creation."""
        for name, value in self.__dict__.items():
            if not str(value).strip():
                raise ValueError(f"metadata field {name} must not be blank")
        if self.deformation_quantity not in {
            "cumulative_displacement",
            "velocity",
        }:
            raise ValueError(
                "deformation_quantity must be cumulative_displacement or velocity"
            )


@dataclass(frozen=True)
class PointQualitySpec:
    """Describe one numeric quality dataset and whether it varies with time."""

    name: str
    temporal: bool
    dtype: str
    unit: str
    description: str
    nodata_policy: str

    def validated_dtype(self) -> np.dtype:
        """Validate field identity, documentation, and fixed-size numeric dtype."""
        if _FIELD_PATTERN.fullmatch(self.name) is None:
            raise ValueError(f"invalid quality field name: {self.name!r}")
        for field_name in ("unit", "description", "nodata_policy"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(
                    f"quality field {self.name} {field_name} must not be blank"
                )
        try:
            dtype = np.dtype(self.dtype)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"invalid dtype for quality field {self.name}: {self.dtype!r}"
            ) from error
        if dtype.kind not in {"f", "i", "u"} or dtype.itemsize not in {1, 2, 4, 8}:
            raise ValueError(f"quality field {self.name} must use a real numeric dtype")
        return dtype


def _validate_dates(dates: Sequence[str]) -> tuple[str, ...]:
    """Validate a non-empty YYYYMMDD acquisition vector."""
    values = tuple(str(value) for value in dates)
    if not values:
        raise ValueError("at least one acquisition date is required")
    for value in values:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as error:
            raise ValueError(f"invalid YYYYMMDD acquisition date: {value}") from error
    return values


class CanonicalPointWriter:
    """Atomically write a canonical PS/DS point time series in ordered point blocks."""

    def __init__(
        self,
        output_file: str | Path,
        dates: Sequence[str],
        point_count: int,
        metadata: PointMetadata,
        *,
        chunk_points: int = 65536,
        compression: str | None = "gzip",
        compression_level: int = 4,
        include_row_column: bool = False,
        include_velocity: bool = False,
        velocity_unit: str | None = None,
        velocity_description: str | None = None,
        velocity_nodata_policy: str | None = None,
        quality_specs: Sequence[PointQualitySpec] = (),
        overwrite: bool = True,
    ) -> None:
        """Validate schema choices without creating an output file."""
        self.output = Path(output_file).expanduser().resolve()
        self.dates = _validate_dates(dates)
        self.point_count = int(point_count)
        if self.point_count < 1:
            raise ValueError("point_count must be positive")
        metadata.validate()
        self.metadata = metadata
        if chunk_points < 1:
            raise ValueError("chunk_points must be positive")
        memory_limited_points = max(
            1, _TARGET_CHUNK_BYTES // np.dtype("float32").itemsize
        )
        self.chunk_points = min(
            int(chunk_points), self.point_count, memory_limited_points
        )
        if compression not in {None, "gzip", "lzf"}:
            raise ValueError("compression must be none, gzip, or lzf")
        if compression == "gzip" and not 0 <= compression_level <= 9:
            raise ValueError("compression_level must be between 0 and 9")
        self.compression = compression
        self.compression_level = int(compression_level)
        self.include_row_column = bool(include_row_column)
        self.include_velocity = bool(include_velocity)
        velocity_metadata = {
            "unit": velocity_unit,
            "description": velocity_description,
            "nodata_policy": velocity_nodata_policy,
        }
        if self.include_velocity:
            missing = [
                name
                for name, value in velocity_metadata.items()
                if value is None or not str(value).strip()
            ]
            if missing:
                raise ValueError(
                    "include_velocity requires non-blank metadata: "
                    f"{sorted(missing)}"
                )
        elif any(value is not None for value in velocity_metadata.values()):
            raise ValueError("velocity metadata requires include_velocity=true")
        self.velocity_metadata = (
            {name: str(value) for name, value in velocity_metadata.items()}
            if self.include_velocity
            else {}
        )
        specs: dict[str, tuple[PointQualitySpec, np.dtype]] = {}
        for spec in quality_specs:
            if spec.name in specs:
                raise ValueError(f"duplicate quality field: {spec.name}")
            specs[spec.name] = (spec, spec.validated_dtype())
        self.quality_specs = specs
        self.static_quality_names = {
            name for name, (spec, _) in specs.items() if not spec.temporal
        }
        self.temporal_quality_names = {
            name for name, (spec, _) in specs.items() if spec.temporal
        }
        self.overwrite = bool(overwrite)
        self._handle: h5py.File | None = None
        self._temporary: Path | None = None
        self._next_static_point = 0
        self._next_deformation_point = np.zeros(len(self.dates), dtype=np.int64)
        self._last_point_id: int | None = None
        self._completed = False

    def __enter__(self) -> "CanonicalPointWriter":
        """Create one private sibling HDF5 file and initialize all declared fields."""
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
        """Return compression and integrity options for chunked numeric fields."""
        options: dict[str, Any] = {
            "compression": self.compression,
            "shuffle": self.compression is not None,
            "fletcher32": True,
        }
        if self.compression == "gzip":
            options["compression_opts"] = self.compression_level
        return options

    def _initialize_file(self) -> None:
        """Create root metadata and empty core, optional, and quality datasets."""
        handle = self._require_handle()
        handle.attrs.update(
            {
                "insar_schema": POINT_SCHEMA,
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
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "write_complete": False,
            }
        )
        text_dtype = h5py.string_dtype(encoding="utf-8")
        handle.create_dataset("time/date_yyyymmdd", data=self.dates, dtype=text_dtype)
        handle.create_dataset(
            "time/epoch_id", data=np.arange(1, len(self.dates) + 1, dtype=np.int64)
        )
        point_chunks = (self.chunk_points,)
        options = self._dataset_options()
        handle.create_dataset(
            "data/displacement",
            shape=(len(self.dates), self.point_count),
            dtype="float32",
            chunks=(1, self.chunk_points),
            fillvalue=np.nan,
            **options,
        )
        core_fields = {
            "point_id": ("int64", -1),
            "x": ("float64", np.nan),
            "y": ("float64", np.nan),
            "height": ("float32", np.nan),
        }
        for name, (dtype, fillvalue) in core_fields.items():
            handle.create_dataset(
                f"points/{name}",
                shape=(self.point_count,),
                dtype=dtype,
                chunks=point_chunks,
                fillvalue=fillvalue,
                **options,
            )
        if self.include_row_column:
            for name in ("row", "column"):
                dataset = handle.create_dataset(
                    f"points/{name}",
                    shape=(self.point_count,),
                    dtype="int64",
                    chunks=point_chunks,
                    fillvalue=-1,
                    **options,
                )
                dataset.attrs.update(
                    {
                        "dimensions": "point",
                        "description": f"Zero-based source raster {name} index",
                        "index_origin": "zero_based",
                    }
                )
        if self.include_velocity:
            dataset = handle.create_dataset(
                "points/velocity",
                shape=(self.point_count,),
                dtype="float32",
                chunks=point_chunks,
                fillvalue=np.nan,
                **options,
            )
            dataset.attrs.update(
                {
                    **self.velocity_metadata,
                    "dimensions": "point",
                }
            )
        for name, (spec, dtype) in self.quality_specs.items():
            shape = (
                (len(self.dates), self.point_count)
                if spec.temporal
                else (self.point_count,)
            )
            chunks = (1, self.chunk_points) if spec.temporal else point_chunks
            dataset = handle.create_dataset(
                f"quality/{name}",
                shape=shape,
                dtype=dtype,
                chunks=chunks,
                **options,
            )
            dataset.attrs.update(
                {
                    "unit": spec.unit,
                    "description": spec.description,
                    "nodata_policy": spec.nodata_policy,
                    "dimensions": "time,point" if spec.temporal else "point",
                }
            )

    def _require_handle(self) -> h5py.File:
        """Return the active output handle."""
        if self._handle is None:
            raise RuntimeError("writer is not active")
        return self._handle

    def _point_block(self, point_start: int, size: int) -> tuple[int, int]:
        """Validate one non-empty contiguous point range."""
        start, stop = int(point_start), int(point_start) + int(size)
        if start < 0 or size < 1 or stop > self.point_count:
            raise ValueError(
                f"invalid point block [{start}:{stop}] for {self.point_count} points"
            )
        return start, stop

    @staticmethod
    def _quality_keys(
        values: Mapping[str, np.ndarray] | None, expected: set[str], label: str
    ) -> Mapping[str, np.ndarray]:
        """Require exactly the declared quality fields for one block role."""
        supplied = {} if values is None else values
        if set(supplied) != expected:
            raise ValueError(
                f"{label} quality fields must be {sorted(expected)}, "
                f"got {sorted(supplied)}"
            )
        return supplied

    def write_points(
        self,
        point_start: int,
        point_id: np.ndarray,
        x: np.ndarray,
        y: np.ndarray,
        height: np.ndarray,
        *,
        row: np.ndarray | None = None,
        column: np.ndarray | None = None,
        velocity: np.ndarray | None = None,
        quality: Mapping[str, np.ndarray] | None = None,
    ) -> None:
        """Write the next static point block, enforcing increasing integer identities."""
        raw_ids = np.asarray(point_id)
        if raw_ids.ndim != 1 or raw_ids.dtype.kind not in {"i", "u"}:
            raise ValueError("point_id must be a one-dimensional integer array")
        if (
            raw_ids.dtype.kind == "u"
            and raw_ids.size
            and raw_ids.max() > np.iinfo(np.int64).max
        ):
            raise ValueError("point_id values must fit in signed int64")
        ids = raw_ids.astype(np.int64, copy=False)
        start, stop = self._point_block(point_start, ids.size)
        if start != self._next_static_point:
            raise ValueError(
                f"static point blocks must be sequential; expected start "
                f"{self._next_static_point}, got {start}"
            )
        if np.any(ids < 0):
            raise ValueError("point_id values must be non-negative")
        if np.any(ids[1:] <= ids[:-1]) or (
            self._last_point_id is not None and int(ids[0]) <= self._last_point_id
        ):
            raise ValueError("point_id values must be globally strictly increasing")
        arrays = {
            "point_id": ids,
            "x": np.asarray(x, dtype=np.float64),
            "y": np.asarray(y, dtype=np.float64),
            "height": np.asarray(height, dtype=np.float32),
        }
        for name, values in arrays.items():
            if values.shape != (ids.size,):
                raise ValueError(f"points/{name} block must have shape ({ids.size},)")
        for name in ("x", "y", "height"):
            if not np.isfinite(arrays[name]).all():
                raise ValueError(f"points/{name} must contain only finite values")
        if self.include_row_column != (row is not None and column is not None):
            raise ValueError(
                "row and column must both be supplied exactly when include_row_column is true"
            )
        if self.include_velocity != (velocity is not None):
            raise ValueError(
                "velocity must be supplied exactly when include_velocity is true"
            )
        handle = self._require_handle()
        for name, values in arrays.items():
            handle[f"points/{name}"][start:stop] = values
        if self.include_row_column:
            for name, values in (("row", row), ("column", column)):
                raw = np.asarray(values)
                if raw.shape != (ids.size,) or raw.dtype.kind not in {"i", "u"}:
                    raise ValueError(
                        f"points/{name} must be a one-dimensional integer block"
                    )
                if np.any(raw < 0):
                    raise ValueError(f"points/{name} must be non-negative")
                if (
                    raw.dtype.kind == "u"
                    and raw.size
                    and raw.max() > np.iinfo(np.int64).max
                ):
                    raise ValueError(f"points/{name} values must fit in signed int64")
                handle[f"points/{name}"][start:stop] = raw.astype(np.int64)
        if self.include_velocity:
            velocity_values = np.asarray(velocity, dtype=np.float32)
            if velocity_values.shape != (ids.size,):
                raise ValueError(f"points/velocity block must have shape ({ids.size},)")
            handle["points/velocity"][start:stop] = velocity_values
        quality_values = self._quality_keys(
            quality, self.static_quality_names, "static"
        )
        for name, values in quality_values.items():
            block = np.asarray(values, dtype=self.quality_specs[name][1])
            if block.shape != (ids.size,):
                raise ValueError(f"quality/{name} block must have shape ({ids.size},)")
            handle[f"quality/{name}"][start:stop] = block
        self._last_point_id = int(ids[-1])
        self._next_static_point = stop

    def write_deformation_points(
        self,
        epoch_index: int,
        point_start: int,
        values: np.ndarray,
        *,
        quality: Mapping[str, np.ndarray] | None = None,
    ) -> None:
        """Write the next deformation and temporal-quality point block for one epoch."""
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= len(self.dates):
            raise IndexError(f"epoch_index out of range: {epoch}")
        block = np.asarray(values, dtype=np.float32)
        if block.ndim != 1:
            raise ValueError("deformation point block must be one-dimensional")
        start, stop = self._point_block(point_start, block.size)
        expected_start = int(self._next_deformation_point[epoch])
        if start != expected_start:
            raise ValueError(
                f"epoch {epoch} point blocks must be sequential; "
                f"expected start {expected_start}, got {start}"
            )
        handle = self._require_handle()
        handle["data/displacement"][epoch, start:stop] = block
        quality_values = self._quality_keys(
            quality, self.temporal_quality_names, "temporal"
        )
        for name, values in quality_values.items():
            quality_block = np.asarray(values, dtype=self.quality_specs[name][1])
            if quality_block.shape != (block.size,):
                raise ValueError(
                    f"quality/{name} temporal block must have shape ({block.size},)"
                )
            handle[f"quality/{name}"][epoch, start:stop] = quality_block
        self._next_deformation_point[epoch] = stop

    def finalize(self) -> Path:
        """Validate completeness and atomically replace the destination."""
        if self._completed:
            return self.output
        handle = self._require_handle()
        if self._next_static_point != self.point_count:
            raise ValueError(
                f"cannot finalize: static points stop at {self._next_static_point}, "
                f"expected {self.point_count}"
            )
        incomplete = np.flatnonzero(
            self._next_deformation_point != self.point_count
        )
        if incomplete.size:
            raise ValueError(
                f"cannot finalize: deformation is incomplete for epochs "
                f"{incomplete.tolist()}"
            )
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
        """Publish a complete context or discard its private temporary file."""
        if exc_type is not None:
            self.abort()
            return
        try:
            self.finalize()
        except Exception:
            self.abort()
            raise


class CanonicalPointReader:
    """Read explicit point ranges from one validated canonical point product."""

    def __init__(self, input_file: str | Path) -> None:
        """Retain a resolved input path without opening it."""
        self.path = Path(input_file).expanduser().resolve()
        self.summary = None
        self.point_count = 0
        self._handle: h5py.File | None = None

    def __enter__(self) -> "CanonicalPointReader":
        """Validate the point product and open one read-only HDF5 handle."""
        self.summary = inspect_hdf5(
            self.path, expected_format="standard", require_unit=True
        )
        if self.summary.layout != "points":
            raise ValueError(f"canonical product is not a point time series: {self.path}")
        self._handle = h5py.File(self.path, "r")
        self.point_count = int(self._handle["data/displacement"].shape[1])
        return self

    def _require_handle(self) -> h5py.File:
        """Return the active read-only HDF5 handle."""
        if self._handle is None:
            raise RuntimeError("reader is not active")
        return self._handle

    def _point_range(self, point_start: int, point_stop: int) -> tuple[int, int]:
        """Validate an explicit non-empty half-open point range."""
        start, stop = int(point_start), int(point_stop)
        if start < 0 or stop <= start or stop > self.point_count:
            raise ValueError(
                f"invalid point range [{start}:{stop}] for {self.point_count} points"
            )
        return start, stop

    def read_epoch(
        self, epoch_index: int, point_start: int, point_stop: int
    ) -> np.ndarray:
        """Read one epoch and one required point range."""
        epoch = int(epoch_index)
        dataset = self._require_handle()["data/displacement"]
        if epoch < 0 or epoch >= dataset.shape[0]:
            raise IndexError(f"epoch_index out of range: {epoch}")
        start, stop = self._point_range(point_start, point_stop)
        return dataset[epoch, start:stop]

    def read_point_fields(
        self, fields: Sequence[str], point_start: int, point_stop: int
    ) -> dict[str, np.ndarray]:
        """Read selected core or optional point fields over one explicit range."""
        start, stop = self._point_range(point_start, point_stop)
        handle = self._require_handle()
        result: dict[str, np.ndarray] = {}
        for field in fields:
            if field not in {
                "point_id",
                "x",
                "y",
                "height",
                "row",
                "column",
                "velocity",
            }:
                raise ValueError(f"unsupported point field: {field}")
            path = f"points/{field}"
            if path not in handle:
                raise KeyError(f"optional point field is absent: {path}")
            result[field] = handle[path][start:stop]
        return result

    def read_quality(
        self,
        name: str,
        point_start: int,
        point_stop: int,
        *,
        epoch_index: int | None = None,
    ) -> np.ndarray:
        """Read one static or temporal quality field over an explicit point range."""
        start, stop = self._point_range(point_start, point_stop)
        handle = self._require_handle()
        if _FIELD_PATTERN.fullmatch(name) is None:
            raise ValueError(f"invalid quality field name: {name!r}")
        path = f"quality/{name}"
        if path not in handle:
            raise KeyError(f"quality field is absent: {path}")
        dataset = handle[path]
        if dataset.ndim == 1:
            if epoch_index is not None:
                raise ValueError(f"static quality field {name} does not accept epoch_index")
            return dataset[start:stop]
        if epoch_index is None:
            raise ValueError(f"temporal quality field {name} requires epoch_index")
        epoch = int(epoch_index)
        if epoch < 0 or epoch >= dataset.shape[0]:
            raise IndexError(f"epoch_index out of range: {epoch}")
        return dataset[epoch, start:stop]

    def close(self) -> None:
        """Close the active HDF5 handle if present."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the read-only point product on context exit."""
        self.close()
