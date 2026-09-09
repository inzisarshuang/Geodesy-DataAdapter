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
            unit = _attribute(displacement.attrs, "UNIT", "unit") or "mm"
            crs = _normalize_crs(_attribute(handle.attrs, "crs")) or "EPSG:4326"
            reference = _attribute(handle.attrs, "refarea", "temporal_reference")
            layout = "grid"
            dataset_name = "/cum"
        else:
            layout = "grid" if schema == "insar_grid_timeseries/1.0" else "points"
            dataset_name = "/data/displacement"
            date_name = "/time/date_yyyymmdd"
            if dataset_name not in handle or date_name not in handle:
                raise ValueError(f"canonical HDF5 is missing {dataset_name} or {date_name}")
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
