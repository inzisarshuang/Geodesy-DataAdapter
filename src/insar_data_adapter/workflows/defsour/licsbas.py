"""Bounded, transactional LiCSBAS-to-Defsour workflow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import CRS
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform

from insar_data_adapter.exporters.defsour import DefsourExportMetadata, write_defsour_grid
from insar_data_adapter.exporters.geotiff import write_geotiff
from insar_data_adapter.sources.licsbas import LiCSBASGridSource

from .config import LiCSBASDefsourConfig
from .grid import GridProfile, prepare_defsour_epoch, select_downsample_factor
from .models import DefsourEpochResult, DefsourSnapshotMetadata
from .publication import publish_defsour_snapshot


def _read_epoch(source: LiCSBASGridSource, index: int, chunk_rows: int) -> np.ndarray:
    output = np.empty((source.rows, source.columns), dtype=np.float32)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = source.read_deformation_rows(index, start, stop)
    return output


def _read_static(source: LiCSBASGridSource, method: str, chunk_rows: int) -> np.ndarray:
    dtype = bool if method == "read_mask_rows" else np.float32
    output = np.empty((source.rows, source.columns), dtype=dtype)
    reader = getattr(source, method)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = reader(start, stop)
    return output


def _profile(source: LiCSBASGridSource, configured_crs: str) -> GridProfile:
    source_crs = CRS.from_user_input(configured_crs)
    if source.declared_crs is not None and CRS.from_user_input(source.declared_crs) != source_crs:
        raise ValueError("configured source_crs conflicts with LiCSBAS declared CRS")
    if source.rows < 2 or source.columns < 2:
        raise ValueError("LiCSBAS Defsour grid requires at least two rows and columns")
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


def _selected(source: LiCSBASGridSource, config: LiCSBASDefsourConfig) -> tuple[int, ...]:
    if config.dates is None:
        return tuple(range(len(source.dates)))
    by_date = {date: index for index, date in enumerate(source.dates)}
    missing = [date for date in config.dates if date not in by_date]
    if missing:
        raise ValueError(f"selected LiCSBAS dates are missing: {missing}")
    return tuple(by_date[date] for date in config.dates)


def _normalized_unit(value: str) -> str:
    aliases = {
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
    }
    normalized = value.strip().lower()
    return aliases.get(normalized, normalized)


def export_licsbas_defsour(config: LiCSBASDefsourConfig) -> DefsourSnapshotMetadata:
    """Export selected LiCSBAS epochs without materializing the input cube."""

    if not isinstance(config, LiCSBASDefsourConfig):
        raise TypeError("config must be LiCSBASDefsourConfig")
    with LiCSBASGridSource(
        config.input_file,
        deformation_dataset=config.deformation_dataset,
        date_dataset=config.date_dataset,
        height_dataset=config.height_dataset,
        mask_dataset=config.mask_dataset,
        refarea_dataset=config.refarea_dataset,
    ) as source:
        if source.declared_unit is not None and _normalized_unit(source.declared_unit) != _normalized_unit(config.source_unit):
            raise ValueError("configured source_unit conflicts with LiCSBAS declared unit")
        indices = _selected(source, config)
        source_profile = _profile(source, config.source_crs)
        destination_profile = _output_profile(source_profile, config.output_crs)
        height = _read_static(source, "read_height_rows", config.chunk_rows)
        mask = _read_static(source, "read_mask_rows", config.chunk_rows)
        factor = select_downsample_factor(
            config.downsample_mode,
            source_profile=source_profile,
            valid_count=int(np.count_nonzero(mask & np.isfinite(height))),
            factor=config.factor,
            target_points=config.target_points,
            target_pixel_size=config.target_pixel_size,
        )
        if config.temporal_reference == "preserve":
            reference_index = None
            temporal_label = "preserve"
        elif config.temporal_reference == "first":
            reference_index = indices[0]
            temporal_label = source.dates[reference_index]
        else:
            if config.temporal_reference not in source.dates:
                raise ValueError("temporal reference date is absent from LiCSBAS dates")
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
            for index in indices:
                deformation = _read_epoch(source, index, config.chunk_rows)
                valid = mask & np.isfinite(height) & np.isfinite(deformation)
                if reference is not None:
                    valid &= np.isfinite(reference)
                    deformation = deformation - reference
                deformation = deformation * config.deformation_scale
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
                epochs.append(
                    DefsourEpochResult(
                        source.dates[index], relative, exported.point_count, tif_relative
                    )
                )
            return DefsourSnapshotMetadata(
                source="licsbas",
                epochs=tuple(epochs),
                metadata=metadata,
                transformations={
                    "aggregation": config.aggregation,
                    "deformation_scale": config.deformation_scale,
                    "downsample_factor": factor,
                    "source_unit": config.source_unit,
                },
            )

        return publish_defsour_snapshot(config.output_dir, build, overwrite=config.overwrite)


__all__ = ["export_licsbas_defsour"]
