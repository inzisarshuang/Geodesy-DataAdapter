"""
text_points
===========

功能概述:
    只读解析带表头的空白分隔点值表，以固定点数分块返回 X、Y 和一个具名科学
    数值列，并在调用者明确要求时转换坐标。表头、CRS、单位、LOS、nodata 和
    参考信息均需明确；本模块不执行单位缩放、插值或持久格式导出。

函数说明:
    ``PointValueMetadata``:
        保存通用点值表不可从字段名可靠推断的科学语义。
    ``PointValueBlock``:
        表示一个连续、受控大小的具名点值块。
    ``HeaderedPointTableSource``:
        校验表头和数据行，并提供可选坐标转换的分块迭代接口。
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
        raise ValueError(f"point-value metadata {field} must not be empty")
    return normalized


@dataclass(frozen=True)
class PointValueMetadata:
    """Describe the explicit meaning and provenance of a generic point-value table."""

    source_format: str
    value_unit: str
    value_quantity: str
    los_positive: str
    crs: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str

    def __post_init__(self) -> None:
        """Require every source attribute and a valid CRS without inferring science."""
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        try:
            CRS.from_user_input(self.crs)
        except Exception as error:
            raise ValueError(f"invalid point-value metadata CRS: {self.crs!r}") from error


@dataclass(frozen=True)
class PointValueBlock:
    """Hold one consecutive block from a headered point-value table."""

    point_start: int
    x: np.ndarray
    y: np.ndarray
    value: np.ndarray
    x_name: str
    y_name: str
    value_name: str
    crs: str

    @property
    def point_stop(self) -> int:
        """Return the exclusive point index following this block."""
        return self.point_start + int(self.x.size)

    @property
    def size(self) -> int:
        """Return the number of points in this block."""
        return int(self.x.size)


class HeaderedPointTableSource:
    """Read a whitespace-delimited point-value table in bounded blocks."""

    def __init__(
        self,
        path: str | Path,
        metadata: PointValueMetadata,
        *,
        chunk_points: int = 250_000,
        x_column: str = "lon",
        y_column: str = "lat",
        value_column: str | None = None,
    ) -> None:
        """Resolve the input and record explicit header names and block size."""
        self.path = Path(path).expanduser().resolve()
        self.metadata = metadata
        self.chunk_points = int(chunk_points)
        self.x_column = str(x_column).strip()
        self.y_column = str(y_column).strip()
        self.requested_value_column = (
            None if value_column is None else str(value_column).strip()
        )
        self.headers: tuple[str, ...] = ()
        self.value_column = ""
        self._header_line_number = 0
        self._indices = (0, 1, 2)
        self._active = False

    def __enter__(self) -> "HeaderedPointTableSource":
        """Validate metadata and parse only the first non-comment header line."""
        if not self.path.is_file():
            raise FileNotFoundError(f"headered point table not found: {self.path}")
        if self.chunk_points < 1:
            raise ValueError("point-table chunk_points must be positive")
        if not self.x_column or not self.y_column:
            raise ValueError("point-table X and Y column names must not be empty")
        if self.x_column == self.y_column:
            raise ValueError("point-table X and Y column names must be distinct")
        if self.requested_value_column == "":
            raise ValueError("point-table value column name must not be empty")
        self._read_header()
        self._active = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Mark the point-table source inactive after its managed scope ends."""
        self._active = False

    def _read_header(self) -> None:
        """Read and validate the first non-empty, non-comment line as the header."""
        with self.path.open("r", encoding="utf-8", errors="strict") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                headers = tuple(line.split())
                self._header_line_number = line_number
                break
            else:
                raise ValueError(f"point table contains no header: {self.path}")
        if len(headers) < 3:
            raise ValueError("point-table header must contain at least three columns")
        if len(set(headers)) != len(headers):
            raise ValueError("point-table header contains duplicate column names")
        for required in (self.x_column, self.y_column):
            if required not in headers:
                raise ValueError(f"point-table header is missing required column: {required}")
        value_column = self.requested_value_column or headers[2]
        if value_column not in headers:
            raise ValueError(
                f"point-table header is missing requested value column: {value_column}"
            )
        if value_column in {self.x_column, self.y_column}:
            raise ValueError("point-table coordinate and value columns must be distinct")
        self.headers = headers
        self.value_column = value_column
        self._indices = (
            headers.index(self.x_column),
            headers.index(self.y_column),
            headers.index(value_column),
        )

    def iter_blocks(self, target_crs: str | None = None) -> Iterator[PointValueBlock]:
        """Yield consecutive point blocks, optionally transformed to ``target_crs``."""
        if not self._active:
            raise RuntimeError("headered point-table source is not active")
        output_crs = self.metadata.crs
        transformer: Transformer | None = None
        if target_crs is not None:
            output_crs = str(target_crs).strip()
            if not output_crs:
                raise ValueError("point-table target_crs must not be empty")
            try:
                transformer = Transformer.from_crs(
                    self.metadata.crs, output_crs, always_xy=True
                )
            except Exception as error:
                raise ValueError(f"invalid point-table target_crs: {output_crs!r}") from error

        point_start = 0
        rows: list[tuple[float, float, float]] = []
        maximum_column = max(self._indices)
        with self.path.open("r", encoding="utf-8", errors="strict") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if line_number <= self._header_line_number:
                    continue
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                tokens = line.split()
                if len(tokens) <= maximum_column:
                    raise ValueError(
                        f"point-table line {line_number} has {len(tokens)} columns; "
                        f"column {maximum_column} is required"
                    )
                try:
                    row = tuple(float(tokens[index]) for index in self._indices)
                except ValueError as error:
                    raise ValueError(
                        f"point-table line {line_number} contains a non-numeric required value"
                    ) from error
                if not np.isfinite(row[:2]).all():
                    raise ValueError(
                        f"point-table line {line_number} contains a non-finite coordinate"
                    )
                rows.append(row)
                if len(rows) == self.chunk_points:
                    yield self._make_block(rows, point_start, output_crs, transformer)
                    point_start += len(rows)
                    rows = []
        if rows:
            yield self._make_block(rows, point_start, output_crs, transformer)
        elif point_start == 0:
            raise ValueError(f"point table contains no data rows: {self.path}")

    def _make_block(
        self,
        rows: list[tuple[float, float, float]],
        point_start: int,
        output_crs: str,
        transformer: Transformer | None,
    ) -> PointValueBlock:
        """Convert one bounded row buffer into independent NumPy arrays."""
        values = np.asarray(rows, dtype=np.float64)
        x, y = values[:, 0], values[:, 1]
        if transformer is not None:
            x, y = transformer.transform(x, y)
            x = np.asarray(x, dtype=np.float64)
            y = np.asarray(y, dtype=np.float64)
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("point-table coordinate transformation produced non-finite values")
        return PointValueBlock(
            point_start=point_start,
            x=x.copy(),
            y=y.copy(),
            value=values[:, 2].copy(),
            x_name=self.x_column,
            y_name=self.y_column,
            value_name=self.value_column,
            crs=output_crs,
        )
