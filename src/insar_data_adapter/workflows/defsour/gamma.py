"""Bounded, transactional GAMMA-to-Defsour workflow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from affine import Affine

from insar_data_adapter.exporters.defsour import (
    DefsourExportMetadata,
    write_defsour_grid,
)
from insar_data_adapter.exporters.geotiff import write_geotiff
from insar_data_adapter.sources.gamma import GammaGeoGridSource

from .alignment import (
    DefsourAlignmentTemplate,
    load_alignment_template,
    save_alignment_template,
)
from .config import GammaDefsourConfig
from .grid import GridProfile, prepare_defsour_epoch, select_downsample_factor
from .models import DefsourEpochResult, DefsourSnapshotMetadata
from .publication import publish_defsour_snapshot


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


def _source_profile(source: GammaGeoGridSource, config: GammaDefsourConfig) -> GridProfile:
    if source.x.ndim != 1 or source.y.ndim != 1:
        raise ValueError("irregular GAMMA coordinates require explicit radar-grid support")
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
        deformation_dtype=config.deformation_dtype,
        deformation_byte_order=config.deformation_byte_order,
        height_dtype=config.height_dtype,
        height_byte_order=config.height_byte_order,
        mask_dtype=config.mask_dtype,
        mask_byte_order=config.mask_byte_order,
    ) as source:
        indices = _selected(source, config)
        source_profile = _source_profile(source, config)
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
            source_profile=source_profile,
            valid_count=int(np.count_nonzero(mask)),
            factor=config.factor,
            target_points=config.target_points,
            target_pixel_size=config.target_pixel_size,
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
                prepared = prepare_defsour_epoch(
                    height,
                    deformation,
                    valid,
                    source_profile,
                    factor=factor,
                    aggregation=config.aggregation,
                    destination_profile=(None if template is None else template.profile),
                )
                if config.mode == "aligned" and template is None:
                    template = DefsourAlignmentTemplate(
                        prepared.profile, factor, prepared.x, prepared.y
                    )
                relative = Path("epochs") / f"{config.prefix}{source.dates[index]}{config.extension}"
                exported = write_defsour_grid(
                    prepared.x,
                    prepared.y,
                    prepared.height,
                    prepared.deformation,
                    (
                        np.ones_like(prepared.valid)
                        if config.export_invalid_points
                        else prepared.valid
                    ),
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
