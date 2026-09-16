"""
raster
======

功能概述:
    提供来源中立、由显式 Rasterio profile 驱动的栅格重投影；不读取或写入文件，
    不推断 CRS、nodata、单位或网格注册方式。

函数说明:
    ``reproject_static_grid_to_profile``:
        使用双线性数值重采样和最近邻有效掩膜，将一个静态栅格投影到目标 profile。
    ``reproject_downsampled_grid_to_profile``:
        使用同一显式有效掩膜，将高程和形变网格投影到目标 profile。
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
from rasterio.enums import Resampling
from rasterio.warp import reproject


def reproject_downsampled_grid_to_profile(
    dem: np.ndarray,
    deform: np.ndarray,
    valid: np.ndarray,
    source_profile: Mapping[str, object],
    destination_profile: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reproject DEM, deformation, and their shared explicit validity mask."""
    destination_shape = (
        int(destination_profile["height"]),
        int(destination_profile["width"]),
    )
    source_transform = source_profile.get("transform")
    destination_transform = destination_profile.get("transform")
    source_crs = source_profile.get("crs")
    destination_crs = destination_profile.get("crs")
    if (
        source_transform is None
        or destination_transform is None
        or source_crs is None
        or destination_crs is None
    ):
        if dem.shape != destination_shape:
            raise ValueError(
                "aligned mode requires georeferenced reference grids "
                "when input and template shapes differ"
            )
        return dem.copy(), deform.copy(), valid.copy()

    dem_source = np.where(valid, dem, np.nan).astype(np.float32)
    deform_source = np.where(valid, deform, np.nan).astype(np.float32)
    valid_source = valid.astype(np.float32)
    dem_destination = np.full(destination_shape, np.nan, dtype=np.float32)
    deform_destination = np.full(destination_shape, np.nan, dtype=np.float32)
    valid_destination = np.zeros(destination_shape, dtype=np.float32)
    reproject(
        source=dem_source,
        destination=dem_destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    reproject(
        source=deform_source,
        destination=deform_destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    reproject(
        source=valid_source,
        destination=valid_destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=0.0,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=0.0,
        resampling=Resampling.nearest,
    )
    valid_output = (
        (valid_destination > 0.5)
        & np.isfinite(dem_destination)
        & np.isfinite(deform_destination)
    )
    return dem_destination, deform_destination, valid_output


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
