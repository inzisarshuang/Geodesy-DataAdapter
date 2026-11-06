"""Bounded, transactional GAMMA-to-Defsour workflow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform

from insar_data_adapter.exporters.defsour import (
    DefsourExportMetadata,
    write_defsour_grid,
)
from insar_data_adapter.exporters.geotiff import write_geotiff
from insar_data_adapter.grid import (
    aggregate_grid_array,
    build_defsour_valid_mask,
    downsample_data_grid,
)
from insar_data_adapter.raster import reproject_geolocated_grid_to_profile
from insar_data_adapter.sources.gamma import GammaGeoGridSource

from .alignment import (
    DefsourAlignmentTemplate,
    load_alignment_template,
    save_alignment_template,
)
from .config import GammaDefsourConfig
from .grid import (
    GridProfile,
    PreparedDefsourGrid,
    coordinate_arrays,
    prepare_defsour_epoch,
    select_downsample_factor,
)
from .models import DefsourEpochResult, DefsourSnapshotMetadata
from .publication import publish_defsour_snapshot, validate_output_separation


def _read_epoch(source: GammaGeoGridSource, index: int, chunk_rows: int) -> np.ndarray:
    output = np.empty((source.rows, source.columns), dtype=np.float32)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = source.read_deformation_rows(index, start, stop)
    return output


def _read_static(source: GammaGeoGridSource, method: str, chunk_rows: int) -> np.ndarray:
    dtype = bool if method == "read_mask_rows" else np.float32
    output = np.empty((source.rows, source.columns), dtype=dtype)
    reader = getattr(source, method)
    for start in range(0, source.rows, chunk_rows):
        stop = min(start + chunk_rows, source.rows)
        output[start:stop] = reader(start, stop)
    return output


def _read_coordinates(
    source: GammaGeoGridSource, config: GammaDefsourConfig
) -> tuple[np.ndarray, np.ndarray] | None:
    if config.longitude_file is None:
        return None
    longitude = np.empty((source.rows, source.columns), dtype=np.float64)
    latitude = np.empty((source.rows, source.columns), dtype=np.float64)
    for start in range(0, source.rows, config.chunk_rows):
        stop = min(start + config.chunk_rows, source.rows)
        longitude[start:stop] = source.read_longitude_rows(start, stop)
        latitude[start:stop] = source.read_latitude_rows(start, stop)
    transformer = Transformer.from_crs(
        config.source_crs, config.output_crs, always_xy=True
    )
    x, y = transformer.transform(longitude, latitude)
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _source_profile(
    source: GammaGeoGridSource, config: GammaDefsourConfig
) -> GridProfile | None:
    if source.x.ndim != 1 or source.y.ndim != 1:
        return None
    if source.columns < 2 or source.rows < 2:
        raise ValueError("GAMMA Defsour grid requires at least two rows and columns")
    x_step = float(source.x[1] - source.x[0])
    y_step = float(source.y[1] - source.y[0])
    if source.declared_crs is not None:
        declared = GridProfile(
            source.rows,
            source.columns,
            source.declared_crs,
            Affine(x_step, 0, source.x[0] - x_step / 2, 0, y_step, source.y[0] - y_step / 2),
            "pixel_center",
        ).crs
        if declared != GridProfile(
            source.rows,
            source.columns,
            config.source_crs,
            Affine(x_step, 0, source.x[0] - x_step / 2, 0, y_step, source.y[0] - y_step / 2),
            "pixel_center",
        ).crs:
            raise ValueError("configured source_crs conflicts with GAMMA parameter EPSG")
    return GridProfile(
        source.rows,
        source.columns,
        config.source_crs,
        Affine(
            x_step,
            0.0,
            float(source.x[0]) - x_step / 2.0,
            0.0,
            y_step,
            float(source.y[0]) - y_step / 2.0,
        ),
        config.grid_registration,
    )


def _irregular_profile(
    x: np.ndarray, y: np.ndarray, config: GammaDefsourConfig
) -> GridProfile:
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        raise ValueError("explicit GAMMA coordinates contain no finite points")
    horizontal = np.hypot(np.diff(x, axis=1), np.diff(y, axis=1))
    vertical = np.hypot(np.diff(x, axis=0), np.diff(y, axis=0))
    sizes = np.concatenate((horizontal[np.isfinite(horizontal)], vertical[np.isfinite(vertical)]))
    sizes = sizes[sizes > 0]
    if sizes.size == 0:
        raise ValueError("explicit GAMMA coordinates do not define pixel spacing")
    pixel_size = float(np.median(sizes))
    return GridProfile(
        x.shape[0],
        x.shape[1],
        config.output_crs,
        Affine(
            pixel_size,
            0.0,
            float(np.nanmin(x[finite])) - pixel_size / 2.0,
            0.0,
            -pixel_size,
            float(np.nanmax(y[finite])) + pixel_size / 2.0,
        ),
        config.grid_registration,
    )


def _output_profile(profile: GridProfile, output_crs: str) -> GridProfile:
    if profile.crs == GridProfile(
        profile.height,
        profile.width,
        output_crs,
        profile.transform,
        profile.registration,
    ).crs:
        return profile
    left, bottom, right, top = array_bounds(
        profile.height, profile.width, profile.transform
    )
    transform, width, height = calculate_default_transform(
        profile.crs,
        output_crs,
        profile.width,
        profile.height,
        left,
        bottom,
        right,
        top,
    )
    return GridProfile(height, width, output_crs, transform, profile.registration)


def _prepare_irregular_native(
    x: np.ndarray,
    y: np.ndarray,
    height: np.ndarray,
    deformation: np.ndarray,
    valid: np.ndarray,
    profile: GridProfile,
    *,
    factor: int,
    aggregation: str,
) -> PreparedDefsourGrid:
    combined = build_defsour_valid_mask(
        x, y, height, deformation, valid_mask=valid
    )
    down_height, down_deformation, down_valid = downsample_data_grid(
        height, deformation, combined, factor, aggregation
    )
    if factor == 1:
        down_x = np.asarray(x)
        down_y = np.asarray(y)
    else:
        down_x = aggregate_grid_array(x, combined, factor, aggregation)
        down_y = aggregate_grid_array(y, combined, factor, aggregation)
    down_valid &= np.isfinite(down_x) & np.isfinite(down_y)
    return PreparedDefsourGrid(
        x=down_x,
        y=down_y,
        height=down_height,
        deformation=down_deformation,
        valid=down_valid,
        profile=profile.downsampled(factor),
    )


def _prepare_irregular_aligned(
    x: np.ndarray,
    y: np.ndarray,
    height: np.ndarray,
    deformation: np.ndarray,
    valid: np.ndarray,
    profile: GridProfile,
    *,
    factor: int,
    aggregation: str,
    destination_profile: GridProfile,
) -> PreparedDefsourGrid:
    native = _prepare_irregular_native(
        x,
        y,
        height,
        deformation,
        valid,
        profile,
        factor=factor,
        aggregation=aggregation,
    )
    out_height, out_deformation, out_valid = reproject_geolocated_grid_to_profile(
        native.height,
        native.deformation,
        native.valid,
        native.x,
        native.y,
        profile.crs,
        destination_profile.rasterio_profile(),
    )
    out_x, out_y = coordinate_arrays(destination_profile)
    return PreparedDefsourGrid(
        out_x,
        out_y,
        out_height,
        out_deformation,
        out_valid,
        destination_profile,
    )


def _selected(source: GammaGeoGridSource, config: GammaDefsourConfig) -> tuple[int, ...]:
    if config.dates is None:
        return tuple(range(len(source.dates)))
    by_date = {date: index for index, date in enumerate(source.dates)}
    missing = [date for date in config.dates if date not in by_date]
    if missing:
        raise ValueError(f"selected GAMMA dates are missing: {missing}")
    return tuple(by_date[date] for date in config.dates)


def export_gamma_defsour(config: GammaDefsourConfig) -> DefsourSnapshotMetadata:
    """Export selected GAMMA epochs without materializing a time cube."""

    if not isinstance(config, GammaDefsourConfig):
        raise TypeError("config must be GammaDefsourConfig")
    with GammaGeoGridSource(
        config.tab_file,
        config.dates_file,
        config.parameter_file,
        config.height_file,
        config.mask_file,
        longitude_file=config.longitude_file,
        latitude_file=config.latitude_file,
        longitude_dtype=config.longitude_dtype,
        longitude_byte_order=config.longitude_byte_order,
        latitude_dtype=config.latitude_dtype,
        latitude_byte_order=config.latitude_byte_order,
        deformation_dtype=config.deformation_dtype,
        deformation_byte_order=config.deformation_byte_order,
        height_dtype=config.height_dtype,
        height_byte_order=config.height_byte_order,
        mask_dtype=config.mask_dtype,
        mask_byte_order=config.mask_byte_order,
    ) as source:
        owned_paths = (
            (config.output_dir / "alignment_template.npz",)
            if config.alignment_template == config.output_dir / "alignment_template.npz"
            else ()
        )
        validate_output_separation(
            config.output_dir,
            (
                config.config_path,
                config.tab_file,
                config.dates_file,
                config.parameter_file,
                config.height_file,
                config.mask_file,
                config.longitude_file,
                config.latitude_file,
                config.source_manifest,
                config.alignment_template,
                *source.deformation_paths,
            ),
            owned_output_paths=owned_paths,
        )
        indices = _selected(source, config)
        source_profile = _source_profile(source, config)
        coordinates = _read_coordinates(source, config)
        if coordinates is not None and config.mode == "native" and config.write_tif:
            raise ValueError(
                "irregular GAMMA coordinates require mode=aligned before writing GeoTIFF"
            )
        factor_profile = (
            source_profile
            if source_profile is not None
            else _irregular_profile(*coordinates, config)  # type: ignore[arg-type]
        )
        height = _read_static(source, "read_height_rows", config.chunk_rows)
        mask = _read_static(source, "read_mask_rows", config.chunk_rows)
        if config.height_nodata is not None:
            mask &= height != config.height_nodata
        reference: np.ndarray | None = None
        if config.temporal_reference == "first":
            reference_index = indices[0]
        elif config.temporal_reference == "preserve":
            reference_index = None
        else:
            if config.temporal_reference not in source.dates:
                raise ValueError("temporal reference date is absent from GAMMA dates")
            reference_index = source.dates.index(config.temporal_reference)
            if reference_index not in indices:
                raise ValueError("temporal reference date is outside selected dates")
        if reference_index is not None:
            reference = _read_epoch(source, reference_index, config.chunk_rows)
        factor = select_downsample_factor(
            config.downsample_mode,
            source_profile=factor_profile,
            valid_count=int(np.count_nonzero(mask)),
            factor=config.factor,
            target_points=config.target_points,
            target_pixel_size=config.target_pixel_size,
        )
        regular_output_profile = (
            _output_profile(source_profile.downsampled(factor), config.output_crs)
            if source_profile is not None
            else None
        )
        template: DefsourAlignmentTemplate | None = None
        template_exists = False
        if config.mode == "aligned":
            assert config.alignment_template is not None
            template_exists = config.alignment_template.is_file()
            if template_exists:
                template = load_alignment_template(config.alignment_template)
                if template.factor != factor:
                    raise ValueError("alignment template factor conflicts with CFG")
                if CRS.from_user_input(template.profile.crs) != CRS.from_user_input(
                    config.output_crs
                ):
                    raise ValueError("alignment template CRS conflicts with output_crs")
                if template.profile.registration != config.grid_registration:
                    raise ValueError(
                        "alignment template registration conflicts with CFG"
                    )
            else:
                expected_template = config.output_dir / "alignment_template.npz"
                if config.alignment_template != expected_template:
                    raise ValueError(
                        "a new alignment_template must be output_dir/alignment_template.npz"
                    )

        metadata = DefsourExportMetadata(
            crs=config.output_crs,
            deformation_unit=config.output_unit,
            deformation_quantity=config.deformation_quantity,
            height_unit=config.height_unit,
            los_positive=config.los_positive,
            nodata_policy=config.nodata_policy,
            temporal_reference=(
                "preserve" if reference_index is None else source.dates[reference_index]
            ),
            spatial_reference=config.spatial_reference,
            source_provenance=config.source_provenance,
        )

        def build(staging: Path) -> DefsourSnapshotMetadata:
            nonlocal template
            epoch_results: list[DefsourEpochResult] = []
            staged_template = Path("alignment_template.npz")
            for index in indices:
                deformation = _read_epoch(source, index, config.chunk_rows)
                valid = mask.copy()
                if config.deformation_nodata is not None:
                    valid &= deformation != config.deformation_nodata
                if reference is not None:
                    valid &= np.isfinite(reference)
                    if config.deformation_nodata is not None:
                        valid &= reference != config.deformation_nodata
                    deformation = deformation - reference
                deformation = deformation * config.deformation_scale
                if coordinates is None:
                    assert source_profile is not None
                    destination = (
                        template.profile
                        if template is not None
                        else (
                            regular_output_profile
                            if config.mode == "aligned"
                            or regular_output_profile != source_profile
                            else None
                        )
                    )
                    prepared = prepare_defsour_epoch(
                        height,
                        deformation,
                        valid,
                        source_profile,
                        factor=factor,
                        aggregation=config.aggregation,
                        destination_profile=destination,
                    )
                else:
                    if config.mode == "aligned":
                        prepared = _prepare_irregular_aligned(
                            *coordinates,
                            height,
                            deformation,
                            valid,
                            factor_profile,
                            factor=factor,
                            aggregation=config.aggregation,
                            destination_profile=(
                                template.profile
                                if template is not None
                                else factor_profile.downsampled(factor)
                            ),
                        )
                    else:
                        prepared = _prepare_irregular_native(
                            *coordinates,
                            height,
                            deformation,
                            valid,
                            factor_profile,
                            factor=factor,
                            aggregation=config.aggregation,
                        )
                if config.mode == "aligned" and template is None:
                    template = DefsourAlignmentTemplate(
                        prepared.profile, factor, prepared.x, prepared.y
                    )
                export_height = prepared.height
                export_deformation = prepared.deformation
                export_mask = prepared.valid
                if config.export_invalid_points:
                    export_height = np.asarray(prepared.height, dtype=np.float64).copy()
                    export_deformation = np.asarray(
                        prepared.deformation, dtype=np.float64
                    ).copy()
                    export_height[~prepared.valid] = np.nan
                    export_deformation[~prepared.valid] = np.nan
                    export_mask = np.ones_like(prepared.valid)
                relative = Path("epochs") / f"{config.prefix}{source.dates[index]}{config.extension}"
                exported = write_defsour_grid(
                    prepared.x,
                    prepared.y,
                    export_height,
                    export_deformation,
                    export_mask,
                    staging / relative,
                    metadata,
                    fmt=config.fmt,
                    export_invalid_points=config.export_invalid_points,
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
                epoch_results.append(
                    DefsourEpochResult(
                        source.dates[index], relative, exported.point_count, tif_relative
                    )
                )
            additional: tuple[Path, ...] = ()
            if config.mode == "aligned":
                assert template is not None
                save_alignment_template(staging / staged_template, template)
                additional = (staged_template,)
            return DefsourSnapshotMetadata(
                source="gamma",
                epochs=tuple(epoch_results),
                metadata=metadata,
                transformations={
                    "aggregation": config.aggregation,
                    "deformation_scale": config.deformation_scale,
                    "downsample_factor": factor,
                    "mode": config.mode,
                    "source_manifest_digest": config.source_manifest_digest,
                    "template_reused": template_exists,
                },
                additional_products=additional,
            )

        return publish_defsour_snapshot(
            config.output_dir, build, overwrite=config.overwrite
        )


__all__ = ["export_gamma_defsour"]
