"""
licsbas
=======

功能概述:
    将 LiCSBAS 累积形变、内嵌 DEM 和质量掩膜按行分块复制到标准规则栅格
    HDF5；可显式保留时间参考或按指定日期重新参考，不执行单位缩放、重投影
    或重采样。

函数说明:
    ``convert_licsbas_grid``:
        校验显式科学元数据并原子生成标准 HDF5。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import CanonicalGridWriter, GridMetadata
from ..sources import LiCSBASGridSource


def _normalize_crs(value: str) -> str:
    """Normalize an explicitly configured numeric EPSG code."""
    normalized = str(value).strip()
    if normalized.isdigit():
        return f"EPSG:{normalized}"
    if normalized.upper().startswith("EPSG:"):
        return normalized.upper()
    return normalized


def convert_licsbas_grid(config: dict[str, Any]) -> Path:
    """Convert one LiCSBAS grid in bounded row blocks without scientific transforms."""
    input_path = Path(config["input_file"]).resolve()
    configured_unit = str(config["deformation_unit"]).strip()
    configured_crs = _normalize_crs(str(config["crs"]))
    if configured_crs.upper() != "EPSG:4326":
        raise ValueError("native LiCSBAS longitude/latitude grids require crs = EPSG:4326")
    with LiCSBASGridSource(
        input_path,
        deformation_dataset=str(config["deformation_dataset"]),
        date_dataset=str(config["date_dataset"]),
        height_dataset=str(config["height_dataset"]),
        mask_dataset=str(config["mask_dataset"]),
    ) as source:
        if source.declared_unit is not None and source.declared_unit != configured_unit:
            raise ValueError(
                "configured deformation_unit conflicts with the LiCSBAS HDF5 unit"
            )
        if source.declared_crs is not None and source.declared_crs != configured_crs:
            raise ValueError("configured crs conflicts with the LiCSBAS HDF5 CRS")
        temporal_mode = str(config["temporal_reference"])
        reference_epoch: int | None = None
        if temporal_mode == "date":
            applied_temporal_reference = str(config["temporal_reference_date"])
            if applied_temporal_reference not in source.dates:
                raise ValueError(
                    "temporal_reference_date is not present in LiCSBAS imdates"
                )
            reference_epoch = source.dates.index(applied_temporal_reference)
            temporal_transform = f"subtract_epoch={applied_temporal_reference}"
        else:
            applied_temporal_reference = str(config["source_temporal_reference"])
            temporal_transform = "preserve_source_temporal_reference"
        mask_dataset = str(config["mask_dataset"]).strip("/")
        nodata_policy = (
            f"LiCSBAS /{mask_dataset}: finite and >0 is valid; "
            f"{str(config['nodata_policy']).strip()}"
        )
        provenance = (
            f"input={input_path};deformation=/{str(config['deformation_dataset']).strip('/')};"
            f"dates=/{str(config['date_dataset']).strip('/')};"
            f"height=/{str(config['height_dataset']).strip('/')};mask=/{mask_dataset};"
            f"temporal_transform={temporal_transform}"
        )
        metadata = GridMetadata(
            source_format="licsbas",
            deformation_unit=configured_unit,
            deformation_quantity="cumulative_displacement",
            los_positive=str(config["los_positive"]),
            crs=configured_crs,
            nodata_policy=nodata_policy,
            temporal_reference=applied_temporal_reference,
            spatial_reference=source.spatial_reference,
            source_provenance=provenance,
            height_unit=str(config["height_unit"]),
            grid_registration=str(config["grid_registration"]),
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
            overwrite=True,
        ) as writer:
            for row_start in range(0, source.rows, chunk_rows):
                row_stop = min(row_start + chunk_rows, source.rows)
                writer.write_geometry_rows(
                    row_start,
                    source.read_height_rows(row_start, row_stop),
                    source.read_mask_rows(row_start, row_stop),
                )
                reference_block = (
                    source.read_deformation_rows(reference_epoch, row_start, row_stop)
                    if reference_epoch is not None
                    else None
                )
                for epoch_index in range(len(source.dates)):
                    deformation = source.read_deformation_rows(
                        epoch_index, row_start, row_stop
                    )
                    if reference_block is not None:
                        deformation -= reference_block
                    writer.write_deformation_rows(
                        epoch_index,
                        row_start,
                        deformation,
                    )
    return Path(config["output_file"]).resolve()
