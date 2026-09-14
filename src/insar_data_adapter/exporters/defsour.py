"""
defsour_export
==============

功能概述:
    将已校验的 X/Y/高程/形变点块按原顺序、受控内存和原子替换规则写为无表头
    Defsour 文本；本模块不读取来源产品，不执行缩放、重投影、插值或重新参考。

函数说明:
    ``DefsourExportMetadata``:
        保存文本列本身无法表达且禁止推断的输出科学语义。
    ``DefsourExportResult``:
        返回已发布文件、点数和显式元数据。
    ``write_defsour_blocks``:
        校验连续点块并原子写出四列 Defsour 文本。
    ``write_defsour_grid``:
        按行块筛选二维网格并复用点块写出契约。
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
from pathlib import Path
import tempfile
from typing import Iterable

import numpy as np
from pyproj import CRS

from ..sources.defsour import DefsourPointBlock


def _required_text(value: str, field: str) -> str:
    """Return stripped required metadata text or reject an empty field."""
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"Defsour export metadata {field} must not be empty")
    return normalized


@dataclass(frozen=True)
class DefsourExportMetadata:
    """Record the explicit scientific meaning of one Defsour export."""

    crs: str
    deformation_unit: str
    deformation_quantity: str
    height_unit: str
    los_positive: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str

    def __post_init__(self) -> None:
        """Normalize required text and validate the declared output CRS."""
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        if self.deformation_quantity not in {
            "cumulative_displacement",
            "velocity",
        }:
            raise ValueError(
                "Defsour deformation_quantity must be cumulative_displacement or velocity"
            )
        try:
            CRS.from_user_input(self.crs)
        except Exception as error:
            raise ValueError(f"invalid Defsour export CRS: {self.crs!r}") from error


@dataclass(frozen=True)
class DefsourExportResult:
    """Summarize an atomically published Defsour point table."""

    output_path: Path
    point_count: int
    metadata: DefsourExportMetadata


def _validate_format(fmt: str) -> str:
    """Require a format that renders one parseable four-column text row."""
    normalized = _required_text(fmt, "format")
    sample = io.StringIO()
    try:
        np.savetxt(sample, np.zeros((1, 4), dtype=np.float64), fmt=normalized)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid Defsour four-column format: {fmt!r}") from error
    lines = sample.getvalue().splitlines()
    if len(lines) != 1 or len(lines[0].split()) != 4:
        raise ValueError("Defsour format must produce exactly four columns on one line")
    try:
        [float(token) for token in lines[0].split()]
    except ValueError as error:
        raise ValueError("Defsour format must produce numeric text columns") from error
    return normalized


def _block_matrix(
    block: DefsourPointBlock,
    expected_start: int,
    expected_crs: CRS,
) -> np.ndarray:
    """Validate one consecutive block and return its four-column matrix."""
    if block.point_start != expected_start:
        raise ValueError(
            f"Defsour block starts at {block.point_start}; expected {expected_start}"
        )
    arrays = tuple(
        np.asarray(values)
        for values in (block.x, block.y, block.height, block.deformation)
    )
    if any(values.ndim != 1 for values in arrays):
        raise ValueError("Defsour block arrays must be one-dimensional")
    sizes = {int(values.size) for values in arrays}
    if len(sizes) != 1 or not sizes or next(iter(sizes)) < 1:
        raise ValueError("Defsour block arrays must have one matching positive size")
    try:
        block_crs = CRS.from_user_input(block.crs)
    except Exception as error:
        raise ValueError(f"invalid Defsour block CRS: {block.crs!r}") from error
    if block_crs != expected_crs:
        raise ValueError(
            f"Defsour block CRS {block.crs!r} does not match export CRS"
        )
    if not np.isfinite(arrays[0]).all() or not np.isfinite(arrays[1]).all():
        raise ValueError("Defsour block coordinates must be finite")
    if np.isinf(arrays[2]).any() or np.isinf(arrays[3]).any():
        raise ValueError("Defsour height and deformation must not contain infinity")
    return np.column_stack(arrays)


def write_defsour_blocks(
    blocks: Iterable[DefsourPointBlock],
    output_file: str | Path,
    metadata: DefsourExportMetadata,
    *,
    fmt: str = "%.6f %.6f %.6f %.6f",
    overwrite: bool = False,
    allow_empty: bool = False,
) -> DefsourExportResult:
    """Validate consecutive point blocks and atomically publish Defsour text."""
    output = Path(output_file).expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(f"Defsour output already exists: {output}")
    normalized_format = _validate_format(fmt)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    expected_crs = CRS.from_user_input(metadata.crs)
    point_count = 0
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            for block in blocks:
                matrix = _block_matrix(block, point_count, expected_crs)
                np.savetxt(stream, matrix, fmt=normalized_format)
                point_count += int(matrix.shape[0])
            if point_count == 0 and not allow_empty:
                raise ValueError("Defsour export requires at least one point block")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return DefsourExportResult(output, point_count, metadata)


def write_defsour_grid(
    x: np.ndarray,
    y: np.ndarray,
    height: np.ndarray,
    deformation: np.ndarray,
    valid_mask: np.ndarray,
    output_file: str | Path,
    metadata: DefsourExportMetadata,
    *,
    fmt: str = "%.6f %.6f %.6f %.6f",
    export_invalid_points: bool = False,
    block_rows: int = 128,
    overwrite: bool = False,
) -> DefsourExportResult:
    """Filter one 2-D grid in bounded row blocks and publish Defsour text."""
    arrays = tuple(
        np.asarray(value)
        for value in (x, y, height, deformation, valid_mask)
    )
    shape = arrays[0].shape
    if any(value.shape != shape for value in arrays[1:]):
        raise ValueError(
            "x, y, height, deformation, and valid_mask must share one shape"
        )
    if len(shape) != 2:
        raise ValueError("Defsour grid inputs must be two-dimensional")
    if block_rows <= 0:
        raise ValueError("block_rows must be positive")

    x_values, y_values, height_values, deformation_values = arrays[:4]
    mask_values = arrays[4].astype(bool, copy=False)

    def blocks() -> Iterable[DefsourPointBlock]:
        point_start = 0
        for row_start in range(0, shape[0], block_rows):
            rows = slice(row_start, min(row_start + block_rows, shape[0]))
            selected = (
                mask_values[rows]
                & np.isfinite(x_values[rows])
                & np.isfinite(y_values[rows])
            )
            if not export_invalid_points:
                selected &= (
                    np.isfinite(height_values[rows])
                    & np.isfinite(deformation_values[rows])
                )
            count = int(np.count_nonzero(selected))
            if count == 0:
                continue
            yield DefsourPointBlock(
                point_start=point_start,
                x=x_values[rows][selected],
                y=y_values[rows][selected],
                height=height_values[rows][selected],
                deformation=deformation_values[rows][selected],
                crs=metadata.crs,
            )
            point_start += count

    return write_defsour_blocks(
        blocks(),
        output_file,
        metadata,
        fmt=fmt,
        overwrite=overwrite,
        allow_empty=True,
    )
