"""Bounded, transactional MintPy-to-Defsour workflow."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from affine import Affine
from pyproj import CRS
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform

from insar_data_adapter.exporters.defsour import DefsourExportMetadata, write_defsour_grid
from insar_data_adapter.exporters.geotiff import write_geotiff
from insar_data_adapter.sources.mintpy import MintPyGridSource

from .config import MintPyDefsourConfig
from .grid import GridProfile, prepare_defsour_epoch, select_downsample_factor
from .models import DefsourEpochResult, DefsourSnapshotMetadata
from .publication import publish_defsour_snapshot


def _read_epoch(source: MintPyGridSource, index: int, chunk_rows: int) -> np.ndarray:
    output = np.empty((source.rows, source.columns), dtype=np.float32)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = source.read_deformation_rows(index, start, stop)
    return output


def _read_static(source: MintPyGridSource, method: str, chunk_rows: int) -> np.ndarray:
    dtype = bool if method == "read_mask_rows" else np.float32
    output = np.empty((source.rows, source.columns), dtype=dtype)
    reader = getattr(source, method)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = reader(start, stop)
    return output


def _profile(source: MintPyGridSource, configured_crs: str) -> GridProfile:
    source_crs = CRS.from_user_input(source.crs)
    if source_crs != CRS.from_user_input(configured_crs):
        raise ValueError("configured source_crs conflicts with MintPy EPSG")
    if source.rows < 2 or source.columns < 2:
        raise ValueError("MintPy Defsour grid requires at least two rows and columns")
    x_step = float(source.x[1] - source.x[0])
    y_step = float(source.y[1] - source.y[0])
    return GridProfile(
        source.rows,
        source.columns,
        source_crs.to_string(),
        Affine(
            x_step,
            0.0,
            float(source.x[0]) - x_step / 2.0,
            0.0,
            y_step,
            float(source.y[0]) - y_step / 2.0,
        ),
        "pixel_center",
    )


def _output_profile(profile: GridProfile, output_crs: str) -> GridProfile:
    target = CRS.from_user_input(output_crs)
    if CRS.from_user_input(profile.crs) == target:
        return profile
    left, bottom, right, top = array_bounds(profile.height, profile.width, profile.transform)
    transform, width, height = calculate_default_transform(
        profile.crs,
        target,
        profile.width,
        profile.height,
        left,
        bottom,
        right,
        top,
    )
    return GridProfile(height, width, target.to_string(), transform, profile.registration)


def _selected(source: MintPyGridSource, config: MintPyDefsourConfig) -> tuple[int, ...]:
    if config.dates is None:
        return tuple(range(len(source.dates)))
    by_date = {date: index for index, date in enumerate(source.dates)}
    missing = [date for date in config.dates if date not in by_date]
    if missing:
        raise ValueError(f"selected MintPy dates are missing: {missing}")
    return tuple(by_date[date] for date in config.dates)


def _read_hdf5_static(
    path: Path,
    dataset_name: str,
    shape: tuple[int, int],
    chunk_rows: int,
) -> np.ndarray:
    with h5py.File(path, "r") as handle:
        if dataset_name not in handle:
            raise ValueError(f"static dataset /{dataset_name} is missing: {path}")
        dataset = handle[dataset_name]
        if dataset.shape != shape:
            raise ValueError(f"static dataset /{dataset_name} shape does not match MintPy grid")
        output = np.empty(shape, dtype=np.float32)
        for start in range(0, shape[0], chunk_rows):
            stop = min(start + chunk_rows, shape[0])
            output[start:stop] = dataset[start:stop, :]
        return output


def export_mintpy_defsour(config: MintPyDefsourConfig) -> DefsourSnapshotMetadata:
    """Export selected MintPy epochs without reading the full time cube."""

    if not isinstance(config, MintPyDefsourConfig):
        raise TypeError("config must be MintPyDefsourConfig")
    with MintPyGridSource(
        config.timeseries_file,
        config.geometry_file,
        config.mask_file,
        timeseries_dataset=config.timeseries_dataset,
        date_dataset=config.date_dataset,
        height_dataset=config.height_dataset,
        mask_dataset=config.mask_dataset,
    ) as source:
        if source.deformation_unit.lower() not in {"m", "meter", "meters", "metre", "metres"}:
            raise ValueError("MintPy source deformation unit must be metres for deformation_scale")
        indices = _selected(source, config)
        source_profile = _profile(source, config.source_crs)
        destination_profile = _output_profile(source_profile, config.output_crs)
        height = _read_static(source, "read_height_rows", config.chunk_rows)
        mask = _read_static(source, "read_mask_rows", config.chunk_rows)
        valid_count = int(np.count_nonzero(mask & np.isfinite(height)))
        factor = select_downsample_factor(
            config.downsample_mode,
            source_profile=source_profile,
            valid_count=valid_count,
            factor=config.factor,
            target_points=config.target_points,
            target_pixel_size=config.target_pixel_size,
        )

        reference_index: int | None
        if config.temporal_reference == "preserve":
            reference_index = None
            temporal_label = source.temporal_reference
        elif config.temporal_reference == "first":
            reference_index = indices[0]
            temporal_label = source.dates[reference_index]
        else:
            if config.temporal_reference not in source.dates:
                raise ValueError("temporal reference date is absent from MintPy dates")
            reference_index = source.dates.index(config.temporal_reference)
            if reference_index not in indices:
                raise ValueError("temporal reference date is outside selected dates")
            temporal_label = source.dates[reference_index]
        reference = (
            None
            if reference_index is None
            else _read_epoch(source, reference_index, config.chunk_rows)
        )
        spatial_label = (
            source.spatial_reference
            if config.spatial_reference.lower() == "preserve"
            else config.spatial_reference
        )
        metadata = DefsourExportMetadata(
            crs=config.output_crs,
            deformation_unit=config.output_unit,
            deformation_quantity=config.deformation_quantity,
            height_unit=config.height_unit,
            los_positive=config.los_positive,
            nodata_policy=config.nodata_policy,
            temporal_reference=temporal_label,
            spatial_reference=spatial_label,
            source_provenance=config.source_provenance,
        )

        def build(staging: Path) -> DefsourSnapshotMetadata:
            epochs: list[DefsourEpochResult] = []
            additional: list[Path] = []
            if config.write_dem_tif:
                relative = Path("native/dem.tif")
                write_geotiff(
                    staging / relative,
                    height,
                    mask & np.isfinite(height),
                    source_profile,
                    unit=config.height_unit,
                    quantity="height",
                )
                additional.append(relative)
            if config.write_velocity_tif:
                assert config.velocity_file is not None
                velocity = _read_hdf5_static(
                    config.velocity_file,
                    config.velocity_dataset,
                    (source.rows, source.columns),
                    config.chunk_rows,
                ) * config.deformation_scale
                relative = Path("native/velocity.tif")
                write_geotiff(
                    staging / relative,
                    velocity,
                    mask & np.isfinite(velocity),
                    source_profile,
                    unit=f"{config.output_unit}/year",
                    quantity="velocity",
                )
                additional.append(relative)
            for index in indices:
                deformation = _read_epoch(source, index, config.chunk_rows)
                valid = mask & np.isfinite(deformation) & np.isfinite(height)
                if reference is not None:
                    valid &= np.isfinite(reference)
                    deformation = deformation - reference
                deformation = deformation * config.deformation_scale
                native_relative: Path | None = None
                if config.write_native_tif:
                    native_relative = Path("native") / f"{config.prefix}{source.dates[index]}.tif"
                    write_geotiff(
                        staging / native_relative,
                        deformation,
                        valid,
                        source_profile,
                        unit=config.output_unit,
                        quantity=config.deformation_quantity,
                    )
                if config.native_only:
                    assert native_relative is not None
                    epochs.append(
                        DefsourEpochResult(source.dates[index], None, 0, native_relative)
                    )
                    continue
                prepared = prepare_defsour_epoch(
                    height,
                    deformation,
                    valid,
                    source_profile,
                    factor=factor,
                    aggregation=config.aggregation,
                    destination_profile=destination_profile,
                )
                relative = Path("epochs") / f"{config.prefix}{source.dates[index]}{config.extension}"
                exported = write_defsour_grid(
                    prepared.x,
                    prepared.y,
                    prepared.height,
                    prepared.deformation,
                    prepared.valid,
                    staging / relative,
                    metadata,
                    fmt=config.fmt,
                    block_rows=config.chunk_rows,
                    overwrite=False,
                )
                tif_relative = None
                if config.write_tif:
                    tif_relative = Path("geotiff") / f"{config.prefix}{source.dates[index]}.tif"
                    write_geotiff(
                        staging / tif_relative,
                        prepared.deformation,
                        prepared.valid,
                        prepared.profile,
                        unit=config.output_unit,
                        quantity=config.deformation_quantity,
                    )
                if native_relative is not None:
                    additional.append(native_relative)
                epochs.append(
                    DefsourEpochResult(
                        source.dates[index], relative, exported.point_count, tif_relative
                    )
                )
            return DefsourSnapshotMetadata(
                source="mintpy",
                epochs=tuple(epochs),
                metadata=metadata,
                transformations={
                    "aggregation": config.aggregation,
                    "deformation_scale": config.deformation_scale,
                    "downsample_factor": factor,
                    "native_only": config.native_only,
                    "source_temporal_reference": source.temporal_reference,
                    "source_spatial_reference": source.spatial_reference,
                },
                additional_products=tuple(additional),
            )

        return publish_defsour_snapshot(config.output_dir, build, overwrite=config.overwrite)


__all__ = ["export_mintpy_defsour"]
