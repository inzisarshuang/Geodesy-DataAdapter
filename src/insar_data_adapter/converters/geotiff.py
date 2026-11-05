"""
geotiff
=======

功能概述:
    将单波段 GeoTIFF 按显式 CRS、重采样、nodata 和比例规则转换为原子输出的
    float32 GeoTIFF。GDAL 在内部按块重投影，随后按目标块缩放；不生成 GMT GRD。

函数说明:
    ``GeoTiffValueMetadata``:
        保存栅格数值不可从像元可靠推断的科学语义。
    ``GeoTiffConversionResult``:
        返回目标栅格几何和 nodata 摘要。
    ``convert_geotiff_raster``:
        校验并转换一幅单波段 GeoTIFF，成功后原子替换目标。
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

import numpy as np
from pyproj import CRS
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject


def _required_text(value: str, field: str) -> str:
    """Return one stripped required metadata value or reject an empty field."""
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"GeoTIFF metadata {field} must not be empty")
    return normalized


@dataclass(frozen=True)
class GeoTiffValueMetadata:
    """Describe the explicit scientific meaning of one converted raster value."""

    input_unit: str
    output_unit: str
    value_quantity: str
    los_positive: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str

    def __post_init__(self) -> None:
        """Require all non-inferable scientific metadata to be explicit."""
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, _required_text(getattr(self, field), field))


@dataclass(frozen=True)
class GeoTiffConversionResult:
    """Summarize the converted GeoTIFF geometry without reopening its pixels."""

    output_path: Path
    crs: str
    width: int
    height: int
    region: tuple[float, float, float, float]
    nodata: float


def convert_geotiff_raster(
    input_path: str | Path,
    output_path: str | Path,
    metadata: GeoTiffValueMetadata,
    *,
    target_crs: str | None = "EPSG:4326",
    source_crs_override: str | None = None,
    scale: float = 1.0,
    nan_to_zero: bool = True,
    resampling: str = "bilinear",
    overwrite: bool = True,
) -> GeoTiffConversionResult:
    """Reproject, scale, and atomically publish one float32 GeoTIFF band."""
    source = Path(input_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"input GeoTIFF not found: {source}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"output GeoTIFF already exists: {output}")
    if output.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("GeoTIFF output path must end in .tif or .tiff")
    if not np.isfinite(scale):
        raise ValueError("GeoTIFF scale must be finite")
    try:
        resampling_mode = Resampling[resampling.strip().lower()]
    except KeyError as error:
        raise ValueError(f"unsupported GeoTIFF resampling method: {resampling!r}") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".tif", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        with rasterio.open(source) as src:
            if src.count < 1:
                raise ValueError(f"input GeoTIFF has no raster bands: {source}")
            if src.crs is None and source_crs_override is None:
                raise ValueError(
                    "input GeoTIFF has no CRS; source_crs_override is required"
                )
            source_crs = CRS.from_user_input(source_crs_override or src.crs)
            destination_crs = (
                CRS.from_user_input(target_crs) if target_crs else source_crs
            )
            if source_crs != destination_crs:
                transform, width, height = calculate_default_transform(
                    source_crs, destination_crs, src.width, src.height, *src.bounds
                )
            else:
                transform, width, height = src.transform, src.width, src.height
            left, bottom, right, top = array_bounds(height, width, transform)
            destination_nodata = 0.0 if nan_to_zero else np.nan
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                count=1,
                width=width,
                height=height,
                transform=transform,
                crs=destination_crs,
                dtype=rasterio.float32,
                nodata=destination_nodata,
            )
            with rasterio.open(temporary, "w", **profile) as dst:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=source_crs,
                    src_nodata=src.nodata,
                    dst_transform=transform,
                    dst_crs=destination_crs,
                    dst_nodata=destination_nodata,
                    resampling=resampling_mode,
                )
                dst.update_tags(
                    input_unit=metadata.input_unit,
                    output_unit=metadata.output_unit,
                    value_quantity=metadata.value_quantity,
                    los_positive=metadata.los_positive,
                    nodata_policy=metadata.nodata_policy,
                    temporal_reference=metadata.temporal_reference,
                    spatial_reference=metadata.spatial_reference,
                    source_provenance=metadata.source_provenance,
                    scale_factor=str(scale),
                    resampling=resampling_mode.name,
                )
            with rasterio.open(temporary, "r+") as dst:
                for _, window in dst.block_windows(1):
                    data = dst.read(1, window=window, masked=True).astype("float32")
                    scaled = data.filled(np.nan) * np.float32(scale)
                    if nan_to_zero:
                        scaled = np.nan_to_num(scaled, nan=0.0)
                    dst.write(scaled.astype("float32", copy=False), 1, window=window)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return GeoTiffConversionResult(
        output_path=output,
        crs=destination_crs.to_string(),
        width=width,
        height=height,
        region=(float(left), float(right), float(bottom), float(top)),
        nodata=float(destination_nodata),
    )
