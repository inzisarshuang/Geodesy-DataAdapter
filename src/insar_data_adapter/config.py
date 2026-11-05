"""
config
======

功能概述:
    严格解析检查、MintPy、LiCSBAS 及 GAMMA 转换 cfg，并按 cfg 目录解析路径。

函数说明:
    ``load_inspect_config``:
        读取并校验 input_file、input_type 和 require_unit。
    ``load_mintpy_conversion_config``:
        读取 MintPy 到标准栅格 HDF5 的显式转换参数。
    ``load_licsbas_conversion_config``:
        读取 LiCSBAS 到标准栅格 HDF5 的显式转换参数。
    ``load_gamma_conversion_config``:
        读取地理编码 GAMMA 二进制时序到标准栅格 HDF5 的显式转换参数。
"""

from __future__ import annotations

import math
from pathlib import Path

from .project_layout import AdapterProjectLayout


_INSPECT_KEYS = {"input_file", "input_type", "require_unit"}
_INPUT_TYPES = {"auto", "mintpy", "licsbas", "standard"}
_LAYOUT_KEYS = {"project_root", "project", "processing_root", "output_name"}

_MINTPY_CONVERSION_KEYS = {
    "timeseries_file",
    "geometry_file",
    "mask_file",
    "output_file",
    "height_dataset",
    "mask_dataset",
    "los_positive",
    "nodata_policy",
    "height_unit",
    "chunk_rows",
    "compression",
    "compression_level",
    "overwrite",
} | _LAYOUT_KEYS

_LICSBAS_CONVERSION_KEYS = {
    "input_file",
    "output_file",
    "deformation_dataset",
    "date_dataset",
    "height_dataset",
    "mask_dataset",
    "deformation_unit",
    "height_unit",
    "crs",
    "los_positive",
    "nodata_policy",
    "temporal_reference",
    "temporal_reference_date",
    "source_temporal_reference",
    "grid_registration",
    "chunk_rows",
    "compression",
    "compression_level",
    "overwrite",
} | _LAYOUT_KEYS

_GAMMA_CONVERSION_KEYS = {
    "tab_file",
    "dates_file",
    "parameter_file",
    "height_file",
    "mask_file",
    "output_file",
    "deformation_dtype",
    "deformation_byte_order",
    "height_dtype",
    "height_byte_order",
    "mask_dtype",
    "mask_byte_order",
    "deformation_unit",
    "height_unit",
    "crs",
    "los_positive",
    "nodata_policy",
    "deformation_nodata",
    "height_nodata",
    "spatial_reference",
    "temporal_reference",
    "temporal_reference_date",
    "source_temporal_reference",
    "grid_registration",
    "chunk_rows",
    "compression",
    "compression_level",
    "overwrite",
} | _LAYOUT_KEYS


def _parse_bool(value: str, key: str) -> bool:
    """Parse one strict human-readable Boolean value."""
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"{key} must be true or false, got {value!r}")


def _read_strict_config(path: Path, allowed_keys: set[str]) -> dict[str, str]:
    """Read key/value text while rejecting malformed, duplicate, and unknown keys."""
    if not path.is_file():
        raise FileNotFoundError(f"cfg file not found: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"expected key = value at {path}:{line_number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in allowed_keys:
            raise ValueError(f"unknown cfg key {key!r} at {path}:{line_number}")
        if key in values:
            raise ValueError(f"duplicate cfg key {key!r} at {path}:{line_number}")
        if not value:
            raise ValueError(f"cfg value {key!r} must not be blank at {path}:{line_number}")
        values[key] = value
    return values


def _resolve_path(value: str, config_path: Path) -> Path:
    """Resolve one cfg path relative to the configuration file directory."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def _parse_integer(
    value: str, key: str, minimum: int, maximum: int | None = None
) -> int:
    """Parse one bounded integer option with a cfg-specific error."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{key} must be an integer, got {value!r}") from error
    if parsed < minimum or (maximum is not None and parsed > maximum):
        limit = (
            f" between {minimum} and {maximum}"
            if maximum is not None
            else f" >= {minimum}"
        )
        raise ValueError(f"{key} must be{limit}, got {parsed}")
    return parsed


def _parse_optional_number(values: dict[str, str], key: str) -> float | None:
    """Parse one optional finite floating-point cfg value."""
    if key not in values:
        return None
    try:
        parsed = float(values[key])
    except ValueError as error:
        raise ValueError(f"{key} must be a number, got {values[key]!r}") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    return parsed


def _conversion_output(
    values: dict[str, str], config_path: Path, default_name: str
) -> Path:
    """Resolve an explicit target or derive one below method-root CANONICAL."""

    if "output_file" in values:
        return _resolve_path(values["output_file"], config_path)
    required = ("project_root", "project", "processing_root")
    missing = [key for key in required if key not in values]
    if missing:
        raise ValueError(
            "output_file or complete method-root context is required; missing: "
            + ", ".join(missing)
        )
    layout = AdapterProjectLayout.bind(
        _resolve_path(values["project_root"], config_path),
        values["project"],
        values["processing_root"],
    )
    return layout.canonical(values.get("output_name", default_name))


def load_inspect_config(config_file: str | Path) -> dict[str, object]:
    """Load a strict Phase 1 inspection configuration."""
    path = Path(config_file).expanduser().resolve()
    values = _read_strict_config(path, _INSPECT_KEYS)
    if not values.get("input_file"):
        raise ValueError(f"input_file is required in {path}")
    input_type = values.get("input_type", "auto").lower()
    if input_type not in _INPUT_TYPES:
        raise ValueError(f"input_type must be one of {sorted(_INPUT_TYPES)}")
    return {
        "input_file": _resolve_path(values["input_file"], path),
        "input_type": input_type,
        "require_unit": _parse_bool(values.get("require_unit", "true"), "require_unit"),
    }


def load_mintpy_conversion_config(config_file: str | Path) -> dict[str, object]:
    """Load strict, scientifically explicit MintPy grid conversion settings."""
    path = Path(config_file).expanduser().resolve()
    values = _read_strict_config(path, _MINTPY_CONVERSION_KEYS)
    required = {
        "timeseries_file",
        "geometry_file",
        "mask_file",
        "los_positive",
        "nodata_policy",
        "height_unit",
    }
    missing = sorted(required.difference(values))
    if missing:
        raise ValueError(f"required MintPy conversion cfg keys are missing: {missing}")
    compression = values.get("compression", "gzip").lower()
    if compression not in {"none", "gzip", "lzf"}:
        raise ValueError("compression must be none, gzip, or lzf")
    return {
        "timeseries_file": _resolve_path(values["timeseries_file"], path),
        "geometry_file": _resolve_path(values["geometry_file"], path),
        "mask_file": _resolve_path(values["mask_file"], path),
        "output_file": _conversion_output(values, path, "mintpy.h5"),
        "height_dataset": values.get("height_dataset", "height"),
        "mask_dataset": values.get("mask_dataset", "mask"),
        "los_positive": values["los_positive"],
        "nodata_policy": values["nodata_policy"],
        "height_unit": values["height_unit"],
        "chunk_rows": _parse_integer(values.get("chunk_rows", "256"), "chunk_rows", 1),
        "compression": None if compression == "none" else compression,
        "compression_level": _parse_integer(
            values.get("compression_level", "4"), "compression_level", 0, 9
        ),
    }


def load_licsbas_conversion_config(config_file: str | Path) -> dict[str, object]:
    """Load strict LiCSBAS grid conversion settings without inferring science metadata."""
    path = Path(config_file).expanduser().resolve()
    values = _read_strict_config(path, _LICSBAS_CONVERSION_KEYS)
    required = {
        "input_file",
        "deformation_unit",
        "height_unit",
        "crs",
        "los_positive",
        "nodata_policy",
        "temporal_reference",
        "grid_registration",
    }
    missing = sorted(required.difference(values))
    if missing:
        raise ValueError(f"required LiCSBAS conversion cfg keys are missing: {missing}")
    registration = values["grid_registration"].lower()
    if registration != "pixel":
        raise ValueError("LiCSBAS corner coordinates require grid_registration = pixel")
    temporal_reference = values["temporal_reference"].lower()
    if temporal_reference not in {"preserve", "date"}:
        raise ValueError("temporal_reference must be preserve or date")
    if temporal_reference == "preserve" and "source_temporal_reference" not in values:
        raise ValueError(
            "source_temporal_reference is required when temporal_reference = preserve"
        )
    if temporal_reference == "date" and "temporal_reference_date" not in values:
        raise ValueError(
            "temporal_reference_date is required when temporal_reference = date"
        )
    compression = values.get("compression", "gzip").lower()
    if compression not in {"none", "gzip", "lzf"}:
        raise ValueError("compression must be none, gzip, or lzf")
    return {
        "input_file": _resolve_path(values["input_file"], path),
        "output_file": _conversion_output(values, path, "licsbas.h5"),
        "deformation_dataset": values.get("deformation_dataset", "cum"),
        "date_dataset": values.get("date_dataset", "imdates"),
        "height_dataset": values.get("height_dataset", "hgt"),
        "mask_dataset": values.get("mask_dataset", "mask"),
        "deformation_unit": values["deformation_unit"],
        "height_unit": values["height_unit"],
        "crs": values["crs"],
        "los_positive": values["los_positive"],
        "nodata_policy": values["nodata_policy"],
        "temporal_reference": temporal_reference,
        "temporal_reference_date": values.get("temporal_reference_date"),
        "source_temporal_reference": values.get("source_temporal_reference"),
        "grid_registration": registration,
        "chunk_rows": _parse_integer(values.get("chunk_rows", "256"), "chunk_rows", 1),
        "compression": None if compression == "none" else compression,
        "compression_level": _parse_integer(
            values.get("compression_level", "4"), "compression_level", 0, 9
        ),
    }


def load_gamma_conversion_config(config_file: str | Path) -> dict[str, object]:
    """Load strict geocoded GAMMA binary-grid conversion settings."""
    path = Path(config_file).expanduser().resolve()
    values = _read_strict_config(path, _GAMMA_CONVERSION_KEYS)
    required = {
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
        "deformation_unit",
        "height_unit",
        "crs",
        "los_positive",
        "nodata_policy",
        "spatial_reference",
        "temporal_reference",
        "grid_registration",
    }
    missing = sorted(required.difference(values))
    if missing:
        raise ValueError(f"required GAMMA conversion cfg keys are missing: {missing}")
    registration = values["grid_registration"].lower()
    if registration != "pixel":
        raise ValueError("GAMMA corner coordinates require grid_registration = pixel")
    temporal_reference = values["temporal_reference"].lower()
    if temporal_reference not in {"preserve", "date"}:
        raise ValueError("temporal_reference must be preserve or date")
    if temporal_reference == "preserve" and "source_temporal_reference" not in values:
        raise ValueError(
            "source_temporal_reference is required when temporal_reference = preserve"
        )
    if temporal_reference == "date" and "temporal_reference_date" not in values:
        raise ValueError(
            "temporal_reference_date is required when temporal_reference = date"
        )
    compression = values.get("compression", "gzip").lower()
    if compression not in {"none", "gzip", "lzf"}:
        raise ValueError("compression must be none, gzip, or lzf")
    return {
        "tab_file": _resolve_path(values["tab_file"], path),
        "dates_file": _resolve_path(values["dates_file"], path),
        "parameter_file": _resolve_path(values["parameter_file"], path),
        "height_file": _resolve_path(values["height_file"], path),
        "mask_file": _resolve_path(values["mask_file"], path),
        "output_file": _conversion_output(values, path, "gamma.h5"),
        "deformation_dtype": values["deformation_dtype"],
        "deformation_byte_order": values["deformation_byte_order"].lower(),
        "height_dtype": values["height_dtype"],
        "height_byte_order": values["height_byte_order"].lower(),
        "mask_dtype": values["mask_dtype"],
        "mask_byte_order": values["mask_byte_order"].lower(),
        "deformation_unit": values["deformation_unit"],
        "height_unit": values["height_unit"],
        "crs": values["crs"],
        "los_positive": values["los_positive"],
        "nodata_policy": values["nodata_policy"],
        "deformation_nodata": _parse_optional_number(values, "deformation_nodata"),
        "height_nodata": _parse_optional_number(values, "height_nodata"),
        "spatial_reference": values["spatial_reference"],
        "temporal_reference": temporal_reference,
        "temporal_reference_date": values.get("temporal_reference_date"),
        "source_temporal_reference": values.get("source_temporal_reference"),
        "grid_registration": registration,
        "chunk_rows": _parse_integer(values.get("chunk_rows", "256"), "chunk_rows", 1),
        "compression": None if compression == "none" else compression,
        "compression_level": _parse_integer(
            values.get("compression_level", "4"), "compression_level", 0, 9
        ),
    }
