"""
model
=====

功能概述:
    定义与源软件无关的只读 InSAR 数据摘要；不负责文件访问或数值转换。

函数说明:
    ``DatasetSummary``:
        保存格式、布局、维度、日期及关键科学元数据，并提供 JSON 兼容字典。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DatasetSummary:
    """Describe one InSAR product without materializing its deformation array."""

    path: str
    source_format: str
    layout: str
    deformation_dataset: str
    deformation_shape: tuple[int, ...]
    dates: tuple[str, ...]
    deformation_unit: str | None
    crs: str | None
    temporal_reference: str | None
    schema: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible summary mapping."""
        result = asdict(self)
        result["deformation_shape"] = list(self.deformation_shape)
        result["dates"] = list(self.dates)
        result["epoch_count"] = len(self.dates)
        return result
