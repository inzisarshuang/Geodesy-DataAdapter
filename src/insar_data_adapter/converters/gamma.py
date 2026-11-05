"""
gamma
=====

功能概述:
    将地理编码 GAMMA 二进制时序、真实 DEM 和显式 mask 通过 memmap 行块写入
    标准 HDF5；支持保留来源时间参考或按指定日期重新参考，不重投影或重采样。

函数说明:
    ``convert_gamma_grid``:
        校验显式二进制与科学约定，处理显式 nodata，并原子生成标准 HDF5。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..canonical import CanonicalGridWriter, GridMetadata
from ..sources import GammaGeoGridSource


def _normalize_crs(value: str) -> str:
    """Normalize an explicit numeric or EPSG-prefixed CRS value."""
    normalized = str(value).strip()
    if normalized.isdigit():
        return f"EPSG:{normalized}"
    if normalized.upper().startswith("EPSG:"):
        return normalized.upper()
    return normalized


def _replace_nodata(values: np.ndarray, nodata: float | None) -> np.ndarray:
    """Replace only an explicitly configured finite nodata sentinel with NaN."""
    if nodata is None:
        return values
    output = values.copy()
    output[output == nodata] = np.nan
    return output


def convert_gamma_grid(config: dict[str, Any]) -> Path:
    """Convert one regular geocoded GAMMA stack using bounded memmap row slices."""
    configured_crs = _normalize_crs(str(config["crs"]))
    if configured_crs.upper() != "EPSG:4326":
        raise ValueError("GAMMA corner_lon/corner_lat grids require crs = EPSG:4326")
    source_arguments = {
        key: config[key]
        for key in (
            "tab_file",
            "dates_file",
            "parameter_file",
            "height_file",
            "mask_file",
            "deformation_dtype",
            "deformation_byte_order",
            "height_dtype",
            "height_byte_order",
            "mask_dtype",
            "mask_byte_order",
        )
    }
    with GammaGeoGridSource(**source_arguments) as source:
        if source.declared_crs is not None and source.declared_crs != configured_crs:
            raise ValueError("configured crs conflicts with the GAMMA parameter EPSG")
        temporal_mode = str(config["temporal_reference"])
        reference_epoch: int | None = None
        if temporal_mode == "date":
            applied_temporal_reference = str(config["temporal_reference_date"])
            if applied_temporal_reference not in source.dates:
                raise ValueError(
                    "temporal_reference_date is not present in GAMMA dates_file"
                )
            reference_epoch = source.dates.index(applied_temporal_reference)
            temporal_transform = f"subtract_epoch={applied_temporal_reference}"
        else:
            applied_temporal_reference = str(config["source_temporal_reference"])
            temporal_transform = "preserve_source_temporal_reference"

        deformation_nodata = config["deformation_nodata"]
        height_nodata = config["height_nodata"]
        nodata_actions = ["mask: finite and >0 is valid"]
        if deformation_nodata is not None:
            nodata_actions.append(f"deformation {deformation_nodata:g} converted to NaN")
        if height_nodata is not None:
            nodata_actions.append(f"height {height_nodata:g} converted to NaN and invalid")
        nodata_policy = "; ".join(nodata_actions + [str(config["nodata_policy"]).strip()])
        provenance = (
            f"tab={source.tab_path};dates={source.dates_path};par={source.parameter_path};"
            f"height={source.height_path};mask={source.mask_path};"
            f"deformation_binary={source.deformation_dtype.str};"
            f"height_binary={source.height_dtype.str};mask_binary={source.mask_dtype.str};"
            f"temporal_transform={temporal_transform}"
        )
        metadata = GridMetadata(
            source_format="gamma",
            deformation_unit=str(config["deformation_unit"]),
            deformation_quantity="cumulative_displacement",
            los_positive=str(config["los_positive"]),
            crs=configured_crs,
            nodata_policy=nodata_policy,
            temporal_reference=applied_temporal_reference,
            spatial_reference=str(config["spatial_reference"]),
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
                height = source.read_height_rows(row_start, row_stop)
                valid_mask = source.read_mask_rows(row_start, row_stop)
                if height_nodata is not None:
                    height_is_nodata = height == height_nodata
                    height = _replace_nodata(height, height_nodata)
                    valid_mask &= ~height_is_nodata
                writer.write_geometry_rows(row_start, height, valid_mask)
                reference_block = (
                    _replace_nodata(
                        source.read_deformation_rows(
                            reference_epoch, row_start, row_stop
                        ),
                        deformation_nodata,
                    )
                    if reference_epoch is not None
                    else None
                )
                for epoch_index in range(len(source.dates)):
                    deformation = _replace_nodata(
                        source.read_deformation_rows(
                            epoch_index, row_start, row_stop
                        ),
                        deformation_nodata,
                    )
                    if reference_block is not None:
                        deformation -= reference_block
                    writer.write_deformation_rows(epoch_index, row_start, deformation)
    return Path(config["output_file"]).resolve()
