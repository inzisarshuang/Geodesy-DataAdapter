"""Source-neutral Defsour grid profiles and preparation."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from pyproj import CRS

from insar_data_adapter.grid import build_defsour_valid_mask, downsample_data_grid
from insar_data_adapter.raster import reproject_downsampled_grid_to_profile


@dataclass(frozen=True)
class GridProfile:
    """Explicit shape, CRS, affine transform, and coordinate registration."""

    height: int
    width: int
    crs: str
    transform: Affine
    registration: str

    def __post_init__(self) -> None:
        if isinstance(self.height, bool) or isinstance(self.width, bool):
            raise ValueError("grid profile dimensions must be positive integers")
        if int(self.height) != self.height or int(self.width) != self.width:
            raise ValueError("grid profile dimensions must be positive integers")
        if self.height <= 0 or self.width <= 0:
            raise ValueError("grid profile dimensions must be positive integers")
        try:
            normalized_crs = CRS.from_user_input(self.crs).to_string()
        except Exception as error:
            raise ValueError(f"invalid grid profile CRS: {self.crs!r}") from error
        try:
            transform = Affine(*tuple(self.transform)[:6])
        except Exception as error:
            raise ValueError("grid profile transform must be affine") from error
        if not np.isfinite(tuple(transform)[:6]).all() or transform.is_degenerate:
            raise ValueError("grid profile transform must be finite and non-degenerate")
        if self.registration != "pixel_center":
            raise ValueError("grid profile registration must be pixel_center")
        object.__setattr__(self, "height", int(self.height))
        object.__setattr__(self, "width", int(self.width))
        object.__setattr__(self, "crs", normalized_crs)
        object.__setattr__(self, "transform", transform)

    def rasterio_profile(self) -> dict[str, object]:
        return {
            "height": self.height,
            "width": self.width,
            "crs": self.crs,
            "transform": self.transform,
        }

    def downsampled(self, factor: int) -> GridProfile:
        if factor < 1 or self.height // factor < 1 or self.width // factor < 1:
            raise ValueError("downsample factor is larger than the grid")
        return GridProfile(
            self.height // factor,
            self.width // factor,
            self.crs,
            self.transform * Affine.scale(factor, factor),
            self.registration,
        )


@dataclass(frozen=True)
class PreparedDefsourGrid:
    x: np.ndarray
    y: np.ndarray
    height: np.ndarray
    deformation: np.ndarray
    valid: np.ndarray
    profile: GridProfile


def coordinate_arrays(profile: GridProfile) -> tuple[np.ndarray, np.ndarray]:
    """Return two row-major arrays of pixel-centre coordinates."""

    rows, columns = np.indices((profile.height, profile.width), dtype=np.float64)
    x = (
        profile.transform.a * (columns + 0.5)
        + profile.transform.b * (rows + 0.5)
        + profile.transform.c
    )
    y = (
        profile.transform.d * (columns + 0.5)
        + profile.transform.e * (rows + 0.5)
        + profile.transform.f
    )
    return x, y


def select_downsample_factor(
    mode: str,
    *,
    source_profile: GridProfile,
    valid_count: int,
    factor: int | None = None,
    target_points: int | None = None,
    target_pixel_size: float | None = None,
) -> int:
    """Resolve one positive integer factor from one explicit selection mode."""

    if isinstance(valid_count, bool) or valid_count < 0:
        raise ValueError("valid_count must be non-negative")
    if mode == "factor":
        if isinstance(factor, bool) or factor is None or int(factor) != factor or factor < 1:
            raise ValueError("factor mode requires a positive integer factor")
        selected = int(factor)
    elif mode == "target_points":
        if (
            isinstance(target_points, bool)
            or target_points is None
            or int(target_points) != target_points
            or target_points < 1
        ):
            raise ValueError("target_points mode requires a positive target_points")
        selected = max(1, math.ceil(math.sqrt(valid_count / int(target_points))))
    elif mode == "target_pixel_size":
        if target_pixel_size is None or not math.isfinite(float(target_pixel_size)) or target_pixel_size <= 0:
            raise ValueError("target_pixel_size mode requires a positive finite size")
        x_size = math.hypot(source_profile.transform.a, source_profile.transform.d)
        y_size = math.hypot(source_profile.transform.b, source_profile.transform.e)
        selected = max(
            1,
            math.ceil(float(target_pixel_size) / x_size),
            math.ceil(float(target_pixel_size) / y_size),
        )
    else:
        raise ValueError("downsample mode must be factor, target_points, or target_pixel_size")
    if source_profile.height // selected < 1 or source_profile.width // selected < 1:
        raise ValueError("selected downsample factor is larger than the grid")
    return selected


def prepare_defsour_epoch(
    height: np.ndarray,
    deformation: np.ndarray,
    valid: np.ndarray,
    source_profile: GridProfile,
    *,
    factor: int,
    aggregation: str,
    destination_profile: GridProfile | None = None,
) -> PreparedDefsourGrid:
    """Aggregate and optionally reproject one epoch with one shared valid mask."""

    height_values = np.asarray(height)
    deformation_values = np.asarray(deformation)
    valid_values = np.asarray(valid, dtype=bool)
    expected = (source_profile.height, source_profile.width)
    if (
        height_values.shape != expected
        or deformation_values.shape != expected
        or valid_values.shape != expected
    ):
        raise ValueError("height, deformation, valid, and source profile shape must match")
    source_x, source_y = coordinate_arrays(source_profile)
    combined_valid = build_defsour_valid_mask(
        source_x,
        source_y,
        height_values,
        deformation_values,
        valid_mask=valid_values,
    )
    down_height, down_deformation, down_valid = downsample_data_grid(
        height_values,
        deformation_values,
        combined_valid,
        factor,
        aggregation,
    )
    down_profile = source_profile.downsampled(int(factor))
    output_profile = down_profile
    if destination_profile is not None:
        down_height, down_deformation, down_valid = (
            reproject_downsampled_grid_to_profile(
                down_height,
                down_deformation,
                down_valid,
                down_profile.rasterio_profile(),
                destination_profile.rasterio_profile(),
            )
        )
        output_profile = destination_profile
    x, y = coordinate_arrays(output_profile)
    return PreparedDefsourGrid(
        x=x,
        y=y,
        height=down_height,
        deformation=down_deformation,
        valid=down_valid,
        profile=output_profile,
    )


__all__ = [
    "GridProfile",
    "PreparedDefsourGrid",
    "coordinate_arrays",
    "prepare_defsour_epoch",
    "select_downsample_factor",
]
