"""
defsour
=======

功能概述:
    只读解析无文件头 Defsour 点表，以固定点数分块返回 X、Y、高程和形变，
    并在调用者明确要求时将坐标转换到目标 CRS。来源单位、LOS 符号、
    nodata 规则和参考信息均由元数据显式声明；本模块不执行单位缩放或插值。

函数说明:
    ``DefsourMetadata``:
        保存 Defsour 快照不可从数值列可靠推断的数据语义。
    ``DefsourPointBlock``:
        表示一个连续、受控大小的点块。
    ``DefsourPointSource``:
        逐行校验点表，并提供可选坐标转换的分块迭代接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from pyproj import CRS, Transformer


def _required_text(value: str, field: str) -> str:
    """Return one stripped required metadata value or reject an empty field."""
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"Defsour metadata {field} must not be empty")
    return normalized


@dataclass(frozen=True)
class DefsourMetadata:
    """Describe the explicit scientific meaning and provenance of a Defsour table."""

    input_crs: str
    deformation_unit: str
    deformation_quantity: str
    height_unit: str
    los_positive: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str

    def __post_init__(self) -> None:
        """Require every non-inferable source attribute to be explicit and valid."""
        fields = (
            "input_crs",
            "deformation_unit",
            "deformation_quantity",
            "height_unit",
            "los_positive",
            "nodata_policy",
            "temporal_reference",
            "spatial_reference",
            "source_provenance",
        )
        for field in fields:
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        try:
            CRS.from_user_input(self.input_crs)
        except Exception as error:
            raise ValueError(
                f"invalid Defsour metadata input_crs: {self.input_crs!r}"
            ) from error


@dataclass(frozen=True)
class DefsourPointBlock:
    """Hold one consecutive Defsour point block in a declared coordinate system."""

    point_start: int
    x: np.ndarray
    y: np.ndarray
    height: np.ndarray
    deformation: np.ndarray
    crs: str

    @property
    def point_stop(self) -> int:
        """Return the exclusive point index following this block."""
        return self.point_start + int(self.x.size)

    @property
    def size(self) -> int:
        """Return the number of points in this block."""
        return int(self.x.size)


class DefsourPointSource:
    """Read a headerless Defsour table through bounded, validated point blocks."""

    def __init__(
        self,
        path: str | Path,
        metadata: DefsourMetadata,
        *,
        chunk_points: int = 250_000,
        x_column: int = 0,
        y_column: int = 1,
        height_column: int = 2,
        deformation_column: int = 3,
    ) -> None:
        """Resolve the table and record explicit zero-based column assignments."""
        self.path = Path(path).expanduser().resolve()
        self.metadata = metadata
        self.chunk_points = int(chunk_points)
        self.x_column = int(x_column)
        self.y_column = int(y_column)
        self.height_column = int(height_column)
        self.deformation_column = int(deformation_column)
        self._active = False

    def __enter__(self) -> "DefsourPointSource":
        """Validate the file and static reader configuration without scanning it."""
        if not self.path.is_file():
            raise FileNotFoundError(f"Defsour table not found: {self.path}")
        if self.chunk_points < 1:
            raise ValueError("Defsour chunk_points must be positive")
        columns = (
            self.x_column,
            self.y_column,
            self.height_column,
            self.deformation_column,
        )
        if any(column < 0 for column in columns):
            raise ValueError("Defsour column indices must be non-negative")
        if len(set(columns)) != len(columns):
            raise ValueError("Defsour X, Y, height, and deformation columns must be distinct")
        self._active = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Mark the source inactive after its bounded iteration scope ends."""
        self._active = False

    def iter_blocks(self, target_crs: str | None = None) -> Iterator[DefsourPointBlock]:
        """Yield consecutive point blocks, optionally transformed to ``target_crs``."""
        if not self._active:
            raise RuntimeError("Defsour source is not active")
        output_crs = self.metadata.input_crs
        transformer: Transformer | None = None
        if target_crs is not None:
            output_crs = _required_text(target_crs, "target_crs")
            try:
                transformer = Transformer.from_crs(
                    self.metadata.input_crs, output_crs, always_xy=True
                )
            except Exception as error:
                raise ValueError(f"invalid Defsour target_crs: {output_crs!r}") from error

        point_start = 0
        rows: list[tuple[float, float, float, float]] = []
        maximum_column = max(
            self.x_column,
            self.y_column,
            self.height_column,
            self.deformation_column,
        )
        with self.path.open("r", encoding="utf-8", errors="strict") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                tokens = line.split()
                if len(tokens) <= maximum_column:
                    raise ValueError(
                        f"Defsour line {line_number} has {len(tokens)} columns; "
                        f"column {maximum_column} is required"
                    )
                try:
                    row = (
                        float(tokens[self.x_column]),
                        float(tokens[self.y_column]),
                        float(tokens[self.height_column]),
                        float(tokens[self.deformation_column]),
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Defsour line {line_number} contains a non-numeric required value"
                    ) from error
                if not np.isfinite(row[:2]).all():
                    raise ValueError(
                        f"Defsour line {line_number} contains a non-finite coordinate"
                    )
                rows.append(row)
                if len(rows) == self.chunk_points:
                    yield self._make_block(rows, point_start, output_crs, transformer)
                    point_start += len(rows)
                    rows = []
        if rows:
            yield self._make_block(rows, point_start, output_crs, transformer)
        elif point_start == 0:
            raise ValueError(f"Defsour table contains no data rows: {self.path}")

    @staticmethod
    def _make_block(
        rows: list[tuple[float, float, float, float]],
        point_start: int,
        output_crs: str,
        transformer: Transformer | None,
    ) -> DefsourPointBlock:
        """Convert one bounded Python row buffer into independent NumPy arrays."""
        values = np.asarray(rows, dtype=np.float64)
        x, y = values[:, 0], values[:, 1]
        if transformer is not None:
            x, y = transformer.transform(x, y)
            x = np.asarray(x, dtype=np.float64)
            y = np.asarray(y, dtype=np.float64)
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Defsour coordinate transformation produced non-finite values")
        return DefsourPointBlock(
            point_start=point_start,
            x=x.copy(),
            y=y.copy(),
            height=values[:, 2].copy(),
            deformation=values[:, 3].copy(),
            crs=output_crs,
        )
