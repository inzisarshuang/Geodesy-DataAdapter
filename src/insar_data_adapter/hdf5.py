"""
hdf5
====

功能概述:
    只读取 HDF5 结构、日期向量和属性，识别 MintPy、LiCSBAS 及标准产品；
    不读取完整形变数组，也不修改输入文件。

函数说明:
    ``detect_hdf5_format``:
        根据根属性和数据集签名识别 HDF5 来源格式。
    ``inspect_hdf5``:
        返回统一摘要并校验时间维、空间维、日期和必要单位。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import h5py

from .model import DatasetSummary


def _text(value: Any) -> str:
    """Normalize one HDF5 scalar or attribute to text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _attribute(attributes: h5py.AttributeManager, *names: str) -> str | None:
    """Return the first present attribute from a case-aware candidate list."""
    for name in names:
        if name in attributes:
            return _text(attributes[name])
    return None


def _dates(dataset: h5py.Dataset) -> tuple[str, ...]:
    """Read only the one-dimensional acquisition-date vector."""
    if dataset.ndim != 1:
        raise ValueError(f"date dataset must be one-dimensional, got {dataset.shape}")
    return tuple(_text(value) for value in dataset[...])


def _normalize_crs(value: str | None) -> str | None:
    """Normalize a numeric EPSG attribute without guessing a missing CRS."""
    if value is None:
        return None
    normalized = value.strip()
    return f"EPSG:{normalized}" if normalized.isdigit() else normalized


def _validate_canonical(handle: h5py.File, schema: str) -> None:
    """Validate required metadata and dimensions for one canonical product."""
    required_attributes = {
        "source_format",
        "deformation_unit",
        "deformation_quantity",
        "los_positive",
        "crs",
        "nodata_policy",
        "temporal_reference",
        "spatial_reference",
        "source_provenance",
        "height_unit",
        "write_complete",
    }
    if schema == "insar_grid_timeseries/1.0":
        required_attributes.add("grid_registration")
    missing_attributes = sorted(required_attributes.difference(handle.attrs.keys()))
    if missing_attributes:
        raise ValueError(f"canonical HDF5 is missing root attributes: {missing_attributes}")
    if not bool(handle.attrs["write_complete"]):
        raise ValueError("canonical HDF5 was not finalized successfully")
    for name in required_attributes.difference({"write_complete"}):
        if not _text(handle.attrs[name]).strip():
            raise ValueError(f"canonical root attribute {name} must not be blank")

    common_datasets = {
        "data/displacement",
        "time/date_yyyymmdd",
        "time/epoch_id",
    }
    required_datasets = set(common_datasets)
    if schema == "insar_grid_timeseries/1.0":
        required_datasets.update(
            {
                "geometry/x",
                "geometry/y",
                "geometry/height",
                "geometry/valid_mask",
            }
        )
    else:
        required_datasets.update(
            {"points/point_id", "points/x", "points/y", "points/height"}
        )
    missing_datasets = sorted(name for name in required_datasets if name not in handle)
    if missing_datasets:
        raise ValueError(f"canonical HDF5 is missing datasets: {missing_datasets}")

    displacement = handle["data/displacement"]
    dates = handle["time/date_yyyymmdd"]
    epoch_ids = handle["time/epoch_id"]
    if displacement.chunks is None:
        raise ValueError("canonical displacement dataset must be chunked")
    if dates.ndim != 1 or epoch_ids.ndim != 1:
        raise ValueError("canonical date and epoch_id datasets must be one-dimensional")
    if len(dates) != len(epoch_ids) or displacement.shape[0] != len(dates):
        raise ValueError("canonical time dimensions are inconsistent")
    epoch_values = epoch_ids[...].tolist()
    if len(epoch_values) != len(set(epoch_values)):
        raise ValueError("canonical epoch_id values must be unique")

    if schema == "insar_grid_timeseries/1.0":
        if displacement.ndim != 3:
            raise ValueError("canonical grid displacement must be [time, row, column]")
        spatial_shape = displacement.shape[1:]
        if handle["geometry/height"].shape != spatial_shape:
            raise ValueError("canonical height shape does not match displacement")
        if handle["geometry/valid_mask"].shape != spatial_shape:
            raise ValueError("canonical valid_mask shape does not match displacement")
        if handle["geometry/x"].shape != (spatial_shape[1],):
            raise ValueError("canonical x length does not match grid columns")
        if handle["geometry/y"].shape != (spatial_shape[0],):
            raise ValueError("canonical y length does not match grid rows")
        has_longitude = "geometry/longitude" in handle
        has_latitude = "geometry/latitude" in handle
        if has_longitude != has_latitude:
            raise ValueError("canonical longitude and latitude must occur together")
        if has_longitude and (
            handle["geometry/longitude"].shape != spatial_shape
            or handle["geometry/latitude"].shape != spatial_shape
        ):
            raise ValueError("canonical longitude/latitude shapes do not match displacement")
    else:
        if displacement.ndim != 2:
            raise ValueError("canonical point displacement must be [time, point]")
        point_count = displacement.shape[1]
        for name in ("point_id", "x", "y", "height"):
            if handle[f"points/{name}"].shape != (point_count,):
                raise ValueError(f"canonical points/{name} length is inconsistent")


def detect_hdf5_format(path: str | Path) -> str:
    """Detect a supported HDF5 layout from attributes and root dataset names."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"HDF5 input not found: {source}")
    with h5py.File(source, "r") as handle:
        schema = _attribute(handle.attrs, "insar_schema")
        if schema in {"insar_grid_timeseries/1.0", "insar_point_timeseries/1.0"}:
            return "standard"
        keys = set(handle.keys())
        if {"timeseries", "date"}.issubset(keys):
            return "mintpy"
        if {"cum", "imdates", "hgt", "mask"}.issubset(keys):
            return "licsbas"
    return "unknown"


def inspect_hdf5(
    path: str | Path,
    expected_format: str = "auto",
    require_unit: bool = True,
) -> DatasetSummary:
    """Inspect and validate supported HDF5 metadata without reading its data cube."""
    source = Path(path).expanduser().resolve()
    if expected_format not in {"auto", "mintpy", "licsbas", "standard"}:
        raise ValueError(f"unsupported expected_format: {expected_format}")
    source_format = detect_hdf5_format(source)
    if source_format == "unknown":
        raise ValueError(f"unsupported or unrecognized InSAR HDF5 layout: {source}")
    if expected_format != "auto" and source_format != expected_format:
        raise ValueError(
            f"expected {expected_format} input but detected {source_format}: {source}"
        )

    with h5py.File(source, "r") as handle:
        schema = _attribute(handle.attrs, "insar_schema")
        if source_format == "mintpy":
            displacement = handle["timeseries"]
            dates = _dates(handle["date"])
            unit = _attribute(displacement.attrs, "UNIT", "unit") or _attribute(
                handle.attrs, "UNIT", "unit"
            )
            crs = _normalize_crs(_attribute(handle.attrs, "EPSG", "crs"))
            reference = _attribute(handle.attrs, "REF_DATE", "temporal_reference")
            layout = "grid"
            dataset_name = "/timeseries"
        elif source_format == "licsbas":
            displacement = handle["cum"]
            dates = _dates(handle["imdates"])
            unit = _attribute(displacement.attrs, "UNIT", "unit") or _attribute(
                handle.attrs, "UNIT", "unit"
            )
            crs = _normalize_crs(_attribute(handle.attrs, "CRS", "crs", "EPSG"))
            reference = _attribute(handle.attrs, "temporal_reference")
            layout = "grid"
            dataset_name = "/cum"
        else:
            layout = "grid" if schema == "insar_grid_timeseries/1.0" else "points"
            dataset_name = "/data/displacement"
            date_name = "/time/date_yyyymmdd"
            _validate_canonical(handle, str(schema))
            displacement = handle[dataset_name]
            dates = _dates(handle[date_name])
            unit = _attribute(handle.attrs, "deformation_unit")
            crs = _normalize_crs(_attribute(handle.attrs, "crs"))
            reference = _attribute(handle.attrs, "temporal_reference")

        shape = tuple(int(value) for value in displacement.shape)
        if displacement.ndim not in {2, 3} or shape[0] != len(dates):
            raise ValueError(
                f"deformation/date dimensions are inconsistent: {shape} versus {len(dates)} dates"
            )
        if not dates or any(not value.strip() for value in dates):
            raise ValueError(f"date vector is empty or contains blank values: {source}")
        for date in dates:
            try:
                datetime.strptime(date, "%Y%m%d")
            except ValueError as error:
                raise ValueError(f"invalid YYYYMMDD date {date!r}: {source}") from error
        if require_unit and not unit:
            raise ValueError(f"deformation unit is missing: {source}")

        return DatasetSummary(
            path=str(source),
            source_format=source_format,
            layout=layout,
            deformation_dataset=dataset_name,
            deformation_shape=shape,
            dates=dates,
            deformation_unit=unit,
            crs=crs,
            temporal_reference=reference,
            schema=schema,
        )
