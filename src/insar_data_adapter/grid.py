"""
grid
====

功能概述:
    提供来源中立、受控内存的二维网格数值变换；不读写文件，
    不缩放单位，不改变 CRS 或网格注册方式。

函数说明:
    ``aggregate_grid_array``:
        使用显式有效掩膜，按固定方形窗口计算均值或中位数。
"""

from __future__ import annotations

import warnings

import numpy as np


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
