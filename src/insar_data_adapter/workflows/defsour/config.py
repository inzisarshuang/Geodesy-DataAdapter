"""Strict source-specific configuration for direct Defsour workflows."""

from __future__ import annotations

import io
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from pyproj import CRS

from insar_data_adapter.config import (
    _parse_bool,
    _parse_integer,
    _parse_optional_number,
    _read_strict_config,
    _resolve_path,
)
from insar_data_adapter.project_layout import AdapterProjectLayout

_DATE = re.compile(r"\d{8}\Z")
_EPOCH_ID = re.compile(r"\d{8}T\d{6}\Z")
_BYTE_ORDERS = {"big", "little", "native"}
_SHARED_KEYS = {
    "output_dir",
    "project_root",
    "project",
    "processing_root",
    "dates",
    "prefix",
    "extension",
    "source_crs",
    "output_crs",
    "format",
    "deformation_scale",
    "output_unit",
    "deformation_quantity",
    "height_unit",
    "los_positive",
    "nodata_policy",
    "temporal_reference",
    "spatial_reference",
    "source_provenance",
    "downsample_mode",
    "factor",
    "target_points",
    "target_pixel_size",
    "aggregation",
    "chunk_rows",
    "write_tif",
    "overwrite",
}
_GAMMA_KEYS = _SHARED_KEYS | {
    "tab_file",
    "dates_file",
    "parameter_file",
    "height_file",
    "mask_file",
    "longitude_file",
    "latitude_file",
    "longitude_dtype",
    "longitude_byte_order",
    "latitude_dtype",
    "latitude_byte_order",
    "deformation_dtype",
    "deformation_byte_order",
    "height_dtype",
    "height_byte_order",
    "mask_dtype",
    "mask_byte_order",
    "deformation_nodata",
    "height_nodata",
    "grid_registration",
    "mode",
    "alignment_template",
    "export_invalid_points",
    "source_manifest",
    "source_width",
    "source_lines",
    "source_unit",
}
_MINTPY_KEYS = _SHARED_KEYS | {
    "timeseries_file",
    "geometry_file",
    "mask_file",
    "velocity_file",
    "timeseries_dataset",
    "date_dataset",
    "height_dataset",
    "mask_dataset",
    "velocity_dataset",
    "velocity_source_unit",
    "write_native_tif",
    "write_velocity_tif",
    "write_dem_tif",
    "native_only",
}
_LICSBAS_KEYS = _SHARED_KEYS | {
    "input_file",
    "source_unit",
    "deformation_dataset",
    "date_dataset",
    "height_dataset",
    "mask_dataset",
    "refarea_dataset",
}
_GEOTIFF_KEYS = (_SHARED_KEYS - {"dates"}) | {
    "epochs",
    "index_file",
    "height_file",
    "mask_file",
    "source_unit",
    "mask_mode",
}


@dataclass(frozen=True)
class DefsourWorkflowConfig:
    config_path: Path
    output_dir: Path
    dates: tuple[str, ...] | None
    prefix: str
    extension: str
    source_crs: str
    output_crs: str
    fmt: str
    deformation_scale: float
    output_unit: str
    deformation_quantity: str
    height_unit: str
    los_positive: str
    nodata_policy: str
    temporal_reference: str
    spatial_reference: str
    source_provenance: str
    downsample_mode: str
    factor: int | None
    target_points: int | None
    target_pixel_size: float | None
    aggregation: str
    chunk_rows: int
    write_tif: bool
    overwrite: bool


@dataclass(frozen=True)
class GammaDefsourConfig(DefsourWorkflowConfig):
    tab_file: Path
    dates_file: Path
    parameter_file: Path
    height_file: Path
    mask_file: Path
    longitude_file: Path | None
    latitude_file: Path | None
    longitude_dtype: str | None
    longitude_byte_order: str | None
    latitude_dtype: str | None
    latitude_byte_order: str | None
    deformation_dtype: str
    deformation_byte_order: str
    height_dtype: str
    height_byte_order: str
    mask_dtype: str
    mask_byte_order: str
    deformation_nodata: float | None
    height_nodata: float | None
    grid_registration: str
    mode: str
    alignment_template: Path | None
    export_invalid_points: bool
    source_manifest: Path | None
    source_manifest_digest: str | None
    source_width: int | None
    source_lines: int | None
    source_unit: str


@dataclass(frozen=True)
class MintPyDefsourConfig(DefsourWorkflowConfig):
    timeseries_file: Path
    geometry_file: Path
    mask_file: Path
    velocity_file: Path | None
    timeseries_dataset: str
    date_dataset: str
    height_dataset: str
    mask_dataset: str
    velocity_dataset: str
    velocity_source_unit: str | None
    write_native_tif: bool
    write_velocity_tif: bool
    write_dem_tif: bool
    native_only: bool


@dataclass(frozen=True)
class LiCSBASDefsourConfig(DefsourWorkflowConfig):
    input_file: Path
    source_unit: str
    deformation_dataset: str
    date_dataset: str
    height_dataset: str
    mask_dataset: str
    refarea_dataset: str


@dataclass(frozen=True)
class GeoTIFFDefsourConfig(DefsourWorkflowConfig):
    epoch_ids: tuple[str, ...] | None
    index_file: Path
    height_file: Path
    mask_file: Path
    source_unit: str
    mask_mode: str


def _required(values: dict[str, str], keys: set[str], source: str) -> None:
    missing = sorted(keys.difference(values))
    if missing:
        raise ValueError(f"required {source} Defsour cfg keys are missing: {missing}")


def _text(values: dict[str, str], key: str) -> str:
    value = values[key].strip()
    if not value:
        raise ValueError(f"{key} must not be blank")
    return value


def _dates(value: str) -> tuple[str, ...] | None:
    if value.strip().lower() == "all":
        return None
    items = tuple(item.strip() for item in value.split(","))
    if not items or any(_DATE.fullmatch(item) is None for item in items):
        raise ValueError("dates must be all or comma-separated YYYYMMDD values")
    for item in items:
        try:
            datetime.strptime(item, "%Y%m%d")
        except ValueError as error:
            raise ValueError(f"dates contains an invalid calendar date: {item}") from error
    if len(set(items)) != len(items):
        raise ValueError("dates contains duplicate values")
    return items


def _epoch_ids(value: str) -> tuple[str, ...] | None:
    if value.strip().lower() == "all":
        return None
    items = tuple(item.strip() for item in value.split(","))
    if not items or any(_EPOCH_ID.fullmatch(item) is None for item in items):
        raise ValueError(
            "epochs must be all or comma-separated YYYYMMDDTHHMMSS values"
        )
    for item in items:
        try:
            datetime.strptime(item, "%Y%m%dT%H%M%S")
        except ValueError as error:
            raise ValueError(f"epochs contains an invalid date or time: {item}") from error
    if len(set(items)) != len(items):
        raise ValueError("epochs contains duplicate values")
    return items


def _float(values: dict[str, str], key: str, *, positive: bool) -> float:
    try:
        value = float(values[key])
    except ValueError as error:
        raise ValueError(f"{key} must be a number") from error
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{key} must be finite{' and positive' if positive else ''}")
    return value


def _format(value: str) -> str:
    stream = io.StringIO()
    try:
        np.savetxt(stream, np.zeros((1, 4)), fmt=value)
    except (TypeError, ValueError) as error:
        raise ValueError("format must be a valid NumPy format for four columns") from error
    rows = stream.getvalue().splitlines()
    if len(rows) != 1 or len(rows[0].split()) != 4:
        raise ValueError("format must render exactly four columns")
    return value


def _output(values: dict[str, str], path: Path, source: str) -> Path:
    if "output_dir" in values:
        return _resolve_path(values["output_dir"], path)
    required = {"project_root", "project", "processing_root"}
    missing = sorted(required.difference(values))
    if missing:
        raise ValueError(
            "output_dir or complete method-root context is required; missing: "
            + ", ".join(missing)
        )
    layout = AdapterProjectLayout.bind(
        _resolve_path(values["project_root"], path),
        values["project"],
        values["processing_root"],
    )
    return layout.defsour(source)


def _expected_scaled_unit(source_unit: str, scale: float) -> str:
    normalized = _normalized_length_unit(source_unit)
    unit_to_metre = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
    }
    for output, metres in (("m", 1.0), ("cm", 0.01), ("mm", 0.001)):
        if np.isclose(scale, unit_to_metre[normalized] / metres):
            return output
    return f"scaled_from_{normalized}_by_{scale:g}"


def _normalized_length_unit(value: str) -> str:
    aliases = {
        "m": "m",
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
        "cm": "cm",
        "centimeter": "cm",
        "centimeters": "cm",
        "centimetre": "cm",
        "centimetres": "cm",
        "mm": "mm",
        "millimeter": "mm",
        "millimeters": "mm",
        "millimetre": "mm",
        "millimetres": "mm",
    }
    normalized = value.strip().lower()
    if normalized not in aliases:
        raise ValueError("source_unit must be a supported m, cm, or mm unit")
    return aliases[normalized]


def _normalized_velocity_unit(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "")
    for suffix in ("/year", "/yr"):
        if normalized.endswith(suffix):
            return f"{_normalized_length_unit(normalized[:-len(suffix)])}/year"
    raise ValueError("velocity_source_unit must be a supported length unit per year")


def _shared(
    values: dict[str, str],
    path: Path,
    source: str,
    *,
    source_unit: str = "m",
) -> dict[str, object]:
    _required(
        values,
        {
            "dates",
            "source_crs",
            "output_crs",
            "deformation_scale",
            "output_unit",
            "deformation_quantity",
            "height_unit",
            "los_positive",
            "nodata_policy",
            "temporal_reference",
            "spatial_reference",
            "source_provenance",
            "downsample_mode",
        },
        source,
    )
    dates = _dates(values["dates"])
    temporal = values["temporal_reference"].lower()
    if temporal not in {"preserve", "first"}:
        if _DATE.fullmatch(temporal) is None:
            raise ValueError("temporal_reference must be preserve, first, or YYYYMMDD date")
        try:
            datetime.strptime(temporal, "%Y%m%d")
        except ValueError as error:
            raise ValueError("temporal_reference date is invalid") from error
        if dates is not None and temporal not in dates:
            raise ValueError("temporal_reference date must be included in dates")
    try:
        source_crs = CRS.from_user_input(values["source_crs"]).to_string()
        output_crs = CRS.from_user_input(values["output_crs"]).to_string()
    except Exception as error:
        raise ValueError("source_crs and output_crs must be valid explicit CRS values") from error
    scale = _float(values, "deformation_scale", positive=True)
    expected_unit = _expected_scaled_unit(source_unit, scale)
    if values["output_unit"] != expected_unit:
        raise ValueError(
            f"output_unit must match deformation_scale ({expected_unit}), got {values['output_unit']}"
        )
    quantity = values["deformation_quantity"]
    if quantity not in {"cumulative_displacement", "velocity"}:
        raise ValueError("deformation_quantity must be cumulative_displacement or velocity")
    mode = values["downsample_mode"].lower()
    factor = target_points = None
    target_pixel_size = None
    if mode == "factor":
        if "factor" not in values:
            raise ValueError("factor is required for downsample_mode = factor")
        factor = _parse_integer(values["factor"], "factor", 1)
    elif mode == "target_points":
        if "target_points" not in values:
            raise ValueError("target_points is required for downsample_mode = target_points")
        target_points = _parse_integer(values["target_points"], "target_points", 1)
    elif mode == "target_pixel_size":
        if "target_pixel_size" not in values:
            raise ValueError(
                "target_pixel_size is required for downsample_mode = target_pixel_size"
            )
        target_pixel_size = _float(values, "target_pixel_size", positive=True)
    else:
        raise ValueError(
            "downsample_mode must be factor, target_points, or target_pixel_size"
        )
    aggregation = values.get("aggregation", "mean").lower()
    if aggregation not in {"mean", "median"}:
        raise ValueError("aggregation must be mean or median")
    prefix = values.get("prefix", "defsour_")
    extension = values.get("extension", ".txt")
    if not prefix or "/" in prefix or "\\" in prefix:
        raise ValueError("prefix must be one non-empty filename prefix")
    if not extension.startswith(".") or "/" in extension or "\\" in extension:
        raise ValueError("extension must be one filename suffix beginning with a dot")
    return {
        "config_path": path,
        "output_dir": _output(values, path, source),
        "dates": dates,
        "prefix": prefix,
        "extension": extension,
        "source_crs": source_crs,
        "output_crs": output_crs,
        "fmt": _format(values.get("format", "%.6f %.6f %.6f %.6f")),
        "deformation_scale": scale,
        "output_unit": values["output_unit"],
        "deformation_quantity": quantity,
        "height_unit": _text(values, "height_unit"),
        "los_positive": _text(values, "los_positive"),
        "nodata_policy": _text(values, "nodata_policy"),
        "temporal_reference": temporal,
        "spatial_reference": _text(values, "spatial_reference"),
        "source_provenance": _text(values, "source_provenance"),
        "downsample_mode": mode,
        "factor": factor,
        "target_points": target_points,
        "target_pixel_size": target_pixel_size,
        "aggregation": aggregation,
        "chunk_rows": _parse_integer(values.get("chunk_rows", "128"), "chunk_rows", 1),
        "write_tif": _parse_bool(values.get("write_tif", "false"), "write_tif"),
        "overwrite": _parse_bool(values.get("overwrite", "true"), "overwrite"),
    }


def _byte_order(values: dict[str, str], key: str) -> str:
    value = values[key].lower()
    if value not in _BYTE_ORDERS:
        raise ValueError(f"{key} must be big, little, or native")
    return value


def _safe_manifest_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Analysis source manifest {label} is invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Analysis source manifest {label} contains path traversal")
    return path


def _validate_manifest(
    source: Path,
    *,
    dates: tuple[str, ...] | None,
    width: int | None,
    lines: int | None,
    unit: str,
    tab_file: Path,
    dates_file: Path,
) -> str:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Analysis source manifest is unreadable: {source}") from error
    if not isinstance(payload, dict) or payload.get("status") != "complete":
        raise ValueError("Analysis source manifest must declare status=complete")
    if payload.get("schema_version") != 2 or payload.get("method") != "gamma_mb":
        raise ValueError("Analysis source manifest method/schema is not gamma_mb v2")
    manifest_dates = payload.get("epochs")
    if not isinstance(manifest_dates, list) or any(
        not isinstance(item, str) or _DATE.fullmatch(item) is None
        for item in manifest_dates
    ):
        raise ValueError("Analysis source manifest dates are invalid")
    manifest_dates_tuple = tuple(manifest_dates)
    if payload.get("epoch_count") != len(manifest_dates_tuple):
        raise ValueError("Analysis source manifest epoch_count disagrees with dates")
    try:
        file_dates = tuple(
            line.strip()
            for line in dates_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except (OSError, UnicodeError) as error:
        raise ValueError("GAMMA dates_file is unreadable for manifest validation") from error
    if file_dates != manifest_dates_tuple:
        raise ValueError("Analysis source manifest dates disagree with dates_file")
    if dates is not None and any(date not in manifest_dates_tuple for date in dates):
        raise ValueError("Analysis source manifest dates disagree with CFG selection")

    displacement = payload.get("displacement")
    if not isinstance(displacement, dict) or displacement.get("enabled") is not True:
        raise ValueError("Analysis source manifest displacement output is not enabled")
    if displacement.get("quantity") != "cumulative_los_displacement":
        raise ValueError("Analysis source manifest deformation quantity disagrees")
    declared_unit = displacement.get("units")
    if not isinstance(declared_unit, str) or _normalized_length_unit(
        declared_unit
    ) != _normalized_length_unit(unit):
        raise ValueError("Analysis source manifest source_unit disagrees with CFG")

    def product_paths(value: object, label: str) -> tuple[Path, ...]:
        if not isinstance(value, list):
            raise ValueError(f"Analysis source manifest {label} is invalid")
        paths: list[Path] = []
        manifest_root = source.parent.resolve()
        for index, item in enumerate(value):
            relative = _safe_manifest_path(item, f"{label}[{index}]")
            resolved = (source.parent / relative).resolve()
            if manifest_root != resolved and manifest_root not in resolved.parents:
                raise ValueError(
                    f"Analysis source manifest {label}[{index}] contains path traversal"
                )
            if not resolved.is_file():
                raise ValueError(
                    f"Analysis source manifest referenced file is missing: {relative}"
                )
            paths.append(resolved)
        return tuple(paths)

    radar_paths = product_paths(displacement.get("paths"), "displacement paths")
    geocoded_paths = product_paths(
        displacement.get("geocoded_paths"), "geocoded displacement paths"
    )
    if displacement.get("geocoded_enabled") is True and not geocoded_paths:
        raise ValueError("Analysis source manifest geocoded displacement paths are empty")
    try:
        tab_paths = tuple(
            (
                Path(line.split()[0]).expanduser()
                if Path(line.split()[0]).expanduser().is_absolute()
                else tab_file.parent / Path(line.split()[0]).expanduser()
            ).resolve()
            for line in tab_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except (OSError, UnicodeError, IndexError) as error:
        raise ValueError("GAMMA tab_file is unreadable for manifest validation") from error
    if tab_paths == radar_paths:
        selected_grid_name = "grid"
    elif tab_paths == geocoded_paths:
        selected_grid_name = "map_grid"
    else:
        raise ValueError(
            "Analysis source manifest displacement paths disagree with tab_file"
        )
    grid = payload.get(selected_grid_name)
    if not isinstance(grid, dict):
        raise ValueError(f"Analysis source manifest {selected_grid_name} is invalid")
    if width is not None and grid.get("width") != width:
        raise ValueError("Analysis source manifest grid width disagrees with CFG")
    if lines is not None and grid.get("lines") != lines:
        raise ValueError("Analysis source manifest grid lines disagree with CFG")

    products = payload.get("products", {})
    if not isinstance(products, dict):
        raise ValueError("Analysis source manifest products are invalid")
    for name, product in products.items():
        if isinstance(product, dict) and "path" in product:
            product_paths([product["path"]], f"product {name}")
    product_paths(payload.get("required_products"), "required_products")

    digest = payload.get("scientific_manifest_digest")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Analysis source manifest digest is invalid")
    scientific = {
        key: value
        for key, value in payload.items()
        if key not in {"scientific_manifest_digest", "required_products", "figures"}
    }
    expected_digest = hashlib.sha256(
        (json.dumps(scientific, sort_keys=True, indent=2) + "\n").encode()
    ).hexdigest()
    if digest != expected_digest:
        raise ValueError("Analysis source manifest digest does not match content")
    return digest


def load_gamma_defsour_config(config_file: str | Path) -> GammaDefsourConfig:
    path = Path(config_file).expanduser().resolve(strict=True)
    values = _read_strict_config(path, _GAMMA_KEYS)
    _required(
        values,
        {
            "tab_file",
            "dates_file",
            "parameter_file",
            "height_file",
            "mask_file",
            "deformation_dtype",
            "deformation_byte_order",
            "height_dtype",
            "height_byte_order",
            "mask_dtype",
            "mask_byte_order",
            "grid_registration",
            "mode",
            "source_unit",
        },
        "GAMMA",
    )
    source_unit = _text(values, "source_unit")
    _normalized_length_unit(source_unit)
    shared = _shared(values, path, "gamma", source_unit=source_unit)
    registration = values["grid_registration"].lower()
    if registration != "pixel_center":
        raise ValueError("grid_registration must be pixel_center")
    mode = values["mode"].lower()
    if mode not in {"native", "aligned"}:
        raise ValueError("mode must be native or aligned")
    template = (
        _resolve_path(values["alignment_template"], path)
        if "alignment_template" in values
        else None
    )
    if mode == "aligned" and template is None:
        raise ValueError("alignment_template is required for aligned mode")
    longitude = (
        _resolve_path(values["longitude_file"], path)
        if "longitude_file" in values
        else None
    )
    latitude = (
        _resolve_path(values["latitude_file"], path)
        if "latitude_file" in values
        else None
    )
    if (longitude is None) != (latitude is None):
        raise ValueError("longitude_file and latitude_file must be supplied together")
    coordinate_keys = {
        "longitude_dtype",
        "longitude_byte_order",
        "latitude_dtype",
        "latitude_byte_order",
    }
    if longitude is not None:
        _required(values, coordinate_keys, "GAMMA coordinate")
    elif coordinate_keys.intersection(values):
        raise ValueError(
            "longitude/latitude dtype and byte order require coordinate files"
        )
    source_manifest = (
        _resolve_path(values["source_manifest"], path)
        if "source_manifest" in values
        else None
    )
    width = (
        _parse_integer(values["source_width"], "source_width", 1)
        if "source_width" in values
        else None
    )
    lines = (
        _parse_integer(values["source_lines"], "source_lines", 1)
        if "source_lines" in values
        else None
    )
    if (width is None) != (lines is None):
        raise ValueError("source_width and source_lines must be supplied together")
    digest = None
    if source_manifest is not None:
        if not source_manifest.is_file():
            raise FileNotFoundError(f"Analysis source manifest not found: {source_manifest}")
        digest = _validate_manifest(
            source_manifest,
            dates=shared["dates"],
            width=width,
            lines=lines,
            unit=source_unit,
            tab_file=_resolve_path(values["tab_file"], path),
            dates_file=_resolve_path(values["dates_file"], path),
        )
    return GammaDefsourConfig(
        **shared,
        tab_file=_resolve_path(values["tab_file"], path),
        dates_file=_resolve_path(values["dates_file"], path),
        parameter_file=_resolve_path(values["parameter_file"], path),
        height_file=_resolve_path(values["height_file"], path),
        mask_file=_resolve_path(values["mask_file"], path),
        longitude_file=longitude,
        latitude_file=latitude,
        longitude_dtype=values.get("longitude_dtype"),
        longitude_byte_order=(
            _byte_order(values, "longitude_byte_order")
            if "longitude_byte_order" in values
            else None
        ),
        latitude_dtype=values.get("latitude_dtype"),
        latitude_byte_order=(
            _byte_order(values, "latitude_byte_order")
            if "latitude_byte_order" in values
            else None
        ),
        deformation_dtype=values["deformation_dtype"],
        deformation_byte_order=_byte_order(values, "deformation_byte_order"),
        height_dtype=values["height_dtype"],
        height_byte_order=_byte_order(values, "height_byte_order"),
        mask_dtype=values["mask_dtype"],
        mask_byte_order=_byte_order(values, "mask_byte_order"),
        deformation_nodata=_parse_optional_number(values, "deformation_nodata"),
        height_nodata=_parse_optional_number(values, "height_nodata"),
        grid_registration=registration,
        mode=mode,
        alignment_template=template,
        export_invalid_points=_parse_bool(
            values.get("export_invalid_points", "false"), "export_invalid_points"
        ),
        source_manifest=source_manifest,
        source_manifest_digest=digest,
        source_width=width,
        source_lines=lines,
        source_unit=source_unit,
    )


def load_mintpy_defsour_config(config_file: str | Path) -> MintPyDefsourConfig:
    path = Path(config_file).expanduser().resolve(strict=True)
    values = _read_strict_config(path, _MINTPY_KEYS)
    _required(values, {"timeseries_file", "geometry_file", "mask_file"}, "MintPy")
    shared = _shared(values, path, "mintpy")
    native_only = _parse_bool(values.get("native_only", "false"), "native_only")
    if native_only and shared["write_tif"]:
        raise ValueError("native_only is incompatible with downsampled write_tif")
    write_native = _parse_bool(
        values.get("write_native_tif", "false"), "write_native_tif"
    )
    if native_only and not write_native:
        raise ValueError("native_only requires write_native_tif = true")
    velocity = (
        _resolve_path(values["velocity_file"], path)
        if "velocity_file" in values
        else None
    )
    write_velocity = _parse_bool(
        values.get("write_velocity_tif", "false"), "write_velocity_tif"
    )
    if write_velocity and velocity is None:
        raise ValueError("velocity_file is required when write_velocity_tif is true")
    velocity_source_unit = values.get("velocity_source_unit")
    if write_velocity and velocity_source_unit is None:
        raise ValueError(
            "velocity_source_unit is required when write_velocity_tif is true"
        )
    if velocity_source_unit is not None:
        normalized_velocity = _normalized_velocity_unit(velocity_source_unit)
        source_length_unit = normalized_velocity.split("/", 1)[0]
        expected_velocity_output = _expected_scaled_unit(
            source_length_unit, shared["deformation_scale"]
        )
        if expected_velocity_output != shared["output_unit"]:
            raise ValueError(
                "velocity_source_unit, deformation_scale, and output_unit disagree"
            )
    return MintPyDefsourConfig(
        **shared,
        timeseries_file=_resolve_path(values["timeseries_file"], path),
        geometry_file=_resolve_path(values["geometry_file"], path),
        mask_file=_resolve_path(values["mask_file"], path),
        velocity_file=velocity,
        timeseries_dataset=values.get("timeseries_dataset", "timeseries"),
        date_dataset=values.get("date_dataset", "date"),
        height_dataset=values.get("height_dataset", "height"),
        mask_dataset=values.get("mask_dataset", "mask"),
        velocity_dataset=values.get("velocity_dataset", "velocity"),
        velocity_source_unit=velocity_source_unit,
        write_native_tif=write_native,
        write_velocity_tif=write_velocity,
        write_dem_tif=_parse_bool(values.get("write_dem_tif", "false"), "write_dem_tif"),
        native_only=native_only,
    )


def load_licsbas_defsour_config(config_file: str | Path) -> LiCSBASDefsourConfig:
    path = Path(config_file).expanduser().resolve(strict=True)
    values = _read_strict_config(path, _LICSBAS_KEYS)
    _required(values, {"input_file", "source_unit"}, "LiCSBAS")
    source_unit = _text(values, "source_unit")
    shared = _shared(values, path, "licsbas", source_unit=source_unit)
    return LiCSBASDefsourConfig(
        **shared,
        input_file=_resolve_path(values["input_file"], path),
        source_unit=source_unit,
        deformation_dataset=values.get("deformation_dataset", "cum"),
        date_dataset=values.get("date_dataset", "imdates"),
        height_dataset=values.get("height_dataset", "hgt"),
        mask_dataset=values.get("mask_dataset", "mask"),
        refarea_dataset=values.get("refarea_dataset", "refarea"),
    )


def load_geotiff_defsour_config(config_file: str | Path) -> GeoTIFFDefsourConfig:
    path = Path(config_file).expanduser().resolve(strict=True)
    values = _read_strict_config(path, _GEOTIFF_KEYS)
    _required(
        values,
        {
            "epochs",
            "index_file",
            "height_file",
            "mask_file",
            "source_unit",
            "mask_mode",
        },
        "GeoTIFF",
    )
    source_unit = _text(values, "source_unit")
    _normalized_length_unit(source_unit)
    shared_values = dict(values)
    shared_values["dates"] = "all"
    shared = _shared(shared_values, path, "geotiff", source_unit=source_unit)
    mask_mode = values["mask_mode"].strip().lower()
    if mask_mode != "positive":
        raise ValueError("mask_mode must be positive")
    inputs = {
        key: _resolve_path(values[key], path)
        for key in ("index_file", "height_file", "mask_file")
    }
    for key, input_path in inputs.items():
        if not input_path.is_file():
            raise FileNotFoundError(f"GeoTIFF Defsour {key} not found: {input_path}")
    return GeoTIFFDefsourConfig(
        **shared,
        epoch_ids=_epoch_ids(values["epochs"]),
        index_file=inputs["index_file"],
        height_file=inputs["height_file"],
        mask_file=inputs["mask_file"],
        source_unit=source_unit,
        mask_mode=mask_mode,
    )


__all__ = [
    "DefsourWorkflowConfig",
    "GammaDefsourConfig",
    "GeoTIFFDefsourConfig",
    "LiCSBASDefsourConfig",
    "MintPyDefsourConfig",
    "load_gamma_defsour_config",
    "load_geotiff_defsour_config",
    "load_licsbas_defsour_config",
    "load_mintpy_defsour_config",
]
