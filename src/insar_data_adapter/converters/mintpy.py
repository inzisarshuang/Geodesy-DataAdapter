"""
mintpy
======

功能概述:
    将地理编码 MintPy 时序按行分块复制到标准规则栅格 HDF5；保留源单位、
    时间参考、空间参考与零值，不执行重投影、重采样或参考变换。

函数说明:
    ``convert_mintpy_grid``:
        使用显式 geometry/mask 和科学元数据，原子生成标准 HDF5。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import CanonicalGridWriter, GridMetadata
from ..sources import MintPyGridSource


def convert_mintpy_grid(config: dict[str, Any]) -> Path:
    """Convert one MintPy grid using bounded row blocks and no scientific transforms."""
    timeseries_path = Path(config["timeseries_file"]).resolve()
    geometry_path = Path(config["geometry_file"]).resolve()
    mask_path = Path(config["mask_file"]).resolve()
    provenance = (
        f"timeseries={timeseries_path};geometry={geometry_path};mask={mask_path}"
    )
    with MintPyGridSource(
        timeseries_path,
        geometry_path,
        mask_path,
        height_dataset=str(config["height_dataset"]),
        mask_dataset=str(config["mask_dataset"]),
    ) as source:
        metadata = GridMetadata(
            source_format="mintpy",
            deformation_unit=source.deformation_unit,
            deformation_quantity="cumulative_displacement",
            los_positive=str(config["los_positive"]),
            crs=source.crs,
            nodata_policy=str(config["nodata_policy"]),
            temporal_reference=source.temporal_reference,
            spatial_reference=source.spatial_reference,
            source_provenance=provenance,
            height_unit=str(config["height_unit"]),
            grid_registration="pixel",
        )
        chunk_rows = int(config["chunk_rows"])
        with CanonicalGridWriter(
            config["output_file"],
            source.dates,
            source.rows,
            source.columns,
            source.x,
            source.y,
            metadata,
            chunk_rows=chunk_rows,
            compression=config["compression"],
            compression_level=int(config["compression_level"]),
            overwrite=bool(config["overwrite"]),
        ) as writer:
            for row_start in range(0, source.rows, chunk_rows):
                row_stop = min(row_start + chunk_rows, source.rows)
                height = source.read_height_rows(row_start, row_stop)
                valid_mask = source.read_mask_rows(row_start, row_stop)
                writer.write_geometry_rows(row_start, height, valid_mask)
            for epoch_index in range(len(source.dates)):
                for row_start in range(0, source.rows, chunk_rows):
                    row_stop = min(row_start + chunk_rows, source.rows)
                    writer.write_deformation_rows(
                        epoch_index,
                        row_start,
                        source.read_deformation_rows(epoch_index, row_start, row_stop),
                    )
    return Path(config["output_file"]).resolve()
