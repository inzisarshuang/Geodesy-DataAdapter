"""
raster
======

功能概述:
    提供来源中立、由显式 Rasterio profile 驱动的栅格重投影；不读取或写入文件，
    不推断 CRS、nodata、单位或网格注册方式。

函数说明:
    ``reproject_static_grid_to_profile``:
        使用双线性数值重采样和最近邻有效掩膜，将一个静态栅格投影到目标 profile。
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
from rasterio.enums import Resampling
from rasterio.warp import reproject


def reproject_static_grid_to_profile(
    values: np.ndarray,
    valid: np.ndarray,
    source_profile: Mapping[str, object],
    destination_profile: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray]:
    """Reproject one static float grid and its explicit validity mask."""
    destination_shape = (
        int(destination_profile["height"]),
        int(destination_profile["width"]),
    )
    source_values = np.where(valid, values, np.nan).astype(np.float32)
    source_valid = np.asarray(valid, dtype=np.float32)
    destination = np.full(destination_shape, np.nan, dtype=np.float32)
    destination_valid = np.zeros(destination_shape, dtype=np.float32)
    reproject(
        source=source_values,
        destination=destination,
        src_transform=source_profile["transform"],
        src_crs=source_profile["crs"],
        src_nodata=np.nan,
        dst_transform=destination_profile["transform"],
        dst_crs=destination_profile["crs"],
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    reproject(
        source=source_valid,
        destination=destination_valid,
        src_transform=source_profile["transform"],
        src_crs=source_profile["crs"],
        src_nodata=0.0,
        dst_transform=destination_profile["transform"],
        dst_crs=destination_profile["crs"],
        dst_nodata=0.0,
        resampling=Resampling.nearest,
    )
    valid_output = (destination_valid > 0.5) & np.isfinite(destination)
    destination[~valid_output] = np.nan
    return destination, valid_output
