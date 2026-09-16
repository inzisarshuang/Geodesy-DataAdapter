"""
grid
====

功能概述:
    提供来源中立、受控内存的二维网格数值变换；不读写文件，
    不缩放单位，不改变 CRS 或网格注册方式。

函数说明:
    ``build_defsour_valid_mask``:
        组合坐标、高程、形变、显式 nodata 哨兵值和外部掩膜。
    ``aggregate_grid_array``:
        使用显式有效掩膜，按固定方形窗口计算均值或中位数。
    ``downsample_data_grid``:
        使用同一有效掩膜聚合高程与形变，并生成低分辨率有效掩膜。
"""

from __future__ import annotations

import warnings

import numpy as np


def build_defsour_valid_mask(
    x: np.ndarray,
    y: np.ndarray,
    dem: np.ndarray,
    deform: np.ndarray,
    nodata_dem: float | None = None,
    nodata_deform: float | None = None,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Combine finite values, explicit sentinels, and an optional external mask."""
    valid = np.isfinite(dem) & np.isfinite(deform)
    valid &= np.isfinite(x) & np.isfinite(y)
    if nodata_dem is not None:
        valid &= dem != nodata_dem
    if nodata_deform is not None:
        valid &= deform != nodata_deform
    if valid_mask is not None:
        valid &= valid_mask
    return valid


def aggregate_grid_array(
    arr: np.ndarray,
    valid: np.ndarray,
    factor: int,
    method: str,
    block_output_rows: int = 128,
) -> np.ndarray:
    """Aggregate complete square windows of one 2-D grid in bounded row blocks."""
    values = np.asarray(arr)
    valid_values = np.asarray(valid, dtype=bool)
    if values.ndim != 2 or valid_values.shape != values.shape:
        raise ValueError("arr and valid must be equally shaped two-dimensional arrays")
    factor = int(factor)
    if factor < 1:
        raise ValueError("grid_downsample_factor must be >= 1")
    if block_output_rows < 1:
        raise ValueError("block_output_rows must be positive")
    if method not in {"mean", "median"}:
        raise ValueError("grid_aggregation must be 'mean' or 'median'")

    rows, columns = values.shape
    output_rows = rows // factor
    output_columns = columns // factor
    if output_rows == 0 or output_columns == 0:
        raise ValueError("grid_downsample_factor is larger than the raster size")

    # Only complete windows participate; incomplete bottom/right edges are dropped.
    trimmed_columns = output_columns * factor
    output = np.full((output_rows, output_columns), np.nan, dtype=np.float64)
    for output_start in range(0, output_rows, block_output_rows):
        output_stop = min(output_start + block_output_rows, output_rows)
        source_start = output_start * factor
        source_stop = output_stop * factor
        block_shape = (
            output_stop - output_start,
            factor,
            output_columns,
            factor,
        )
        value_block = values[
            source_start:source_stop, :trimmed_columns
        ].reshape(block_shape)
        valid_block = valid_values[
            source_start:source_stop, :trimmed_columns
        ].reshape(block_shape)

        if method == "mean":
            counts = np.sum(valid_block, axis=(1, 3), dtype=np.int64)
            sums = np.sum(
                value_block,
                axis=(1, 3),
                dtype=np.float64,
                where=valid_block,
            )
            np.divide(
                sums,
                counts,
                out=output[output_start:output_stop],
                where=counts > 0,
            )
        else:
            median_values = np.where(valid_block, value_block, np.nan)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                output[output_start:output_stop] = np.nanmedian(
                    median_values, axis=(1, 3)
                )
    return output


def downsample_data_grid(
    dem: np.ndarray,
    deform: np.ndarray,
    valid: np.ndarray,
    factor: int,
    method: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aggregate DEM and deformation with one explicit validity mask."""
    factor = int(factor)
    if factor < 1:
        raise ValueError("grid_downsample_factor must be >= 1")
    if factor == 1:
        return dem, deform, valid
    dem_out = aggregate_grid_array(dem, valid, factor, method)
    deform_out = aggregate_grid_array(deform, valid, factor, method)
    valid_out = np.isfinite(dem_out) & np.isfinite(deform_out)
    return dem_out, deform_out, valid_out
