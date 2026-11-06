"""Safe reusable alignment templates for multi-track Defsour exports."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine

from .grid import GridProfile


@dataclass(frozen=True)
class DefsourAlignmentTemplate:
    profile: GridProfile
    factor: int
    x: np.ndarray
    y: np.ndarray

    def __post_init__(self) -> None:
        if isinstance(self.factor, bool) or int(self.factor) != self.factor or self.factor < 1:
            raise ValueError("alignment template factor must be a positive integer")
        x = np.asarray(self.x, dtype=np.float64)
        y = np.asarray(self.y, dtype=np.float64)
        expected = (self.profile.height, self.profile.width)
        if x.shape != expected or y.shape != expected:
            raise ValueError("alignment template coordinate shape must match profile")
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("alignment template coordinates must be finite")
        x = x.copy()
        y = y.copy()
        x.setflags(write=False)
        y.setflags(write=False)
        object.__setattr__(self, "factor", int(self.factor))
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)

    def validate(
        self,
        profile: GridProfile,
        *,
        factor: int,
        x: np.ndarray,
        y: np.ndarray,
    ) -> None:
        if profile != self.profile:
            raise ValueError("alignment template profile conflict")
        if factor != self.factor:
            raise ValueError("alignment template factor conflict")
        x_values = np.asarray(x)
        y_values = np.asarray(y)
        if (
            x_values.shape != self.x.shape
            or y_values.shape != self.y.shape
            or not np.array_equal(x_values, self.x)
            or not np.array_equal(y_values, self.y)
        ):
            raise ValueError("alignment template coordinate order conflict")


def _metadata(template: DefsourAlignmentTemplate) -> np.ndarray:
    payload = {
        "schema_version": 1,
        "height": template.profile.height,
        "width": template.profile.width,
        "crs": template.profile.crs,
        "transform": list(tuple(template.profile.transform)[:6]),
        "registration": template.profile.registration,
        "factor": template.factor,
    }
    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
    return np.frombuffer(raw, dtype=np.uint8).copy()


def save_alignment_template(
    path: Path, template: DefsourAlignmentTemplate
) -> Path:
    """Atomically save numeric arrays and UTF-8 JSON metadata without pickle."""

    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            np.savez(
                stream,
                metadata=_metadata(template),
                x=template.x,
                y=template.y,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return output


def load_alignment_template(path: Path) -> DefsourAlignmentTemplate:
    """Load and strictly validate a non-pickle alignment template."""

    source = Path(path).expanduser().resolve(strict=True)
    try:
        with np.load(source, allow_pickle=False) as archive:
            if set(archive.files) != {"metadata", "x", "y"}:
                raise ValueError("alignment template fields are incomplete")
            metadata_values = archive["metadata"]
            x = archive["x"]
            y = archive["y"]
    except ValueError as error:
        if "fields" in str(error):
            raise
        raise ValueError("alignment template must contain safe numeric arrays") from error
    if metadata_values.dtype != np.uint8 or metadata_values.ndim != 1:
        raise ValueError("alignment template metadata must be safe numeric UTF-8 bytes")
    try:
        payload = json.loads(metadata_values.tobytes().decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("alignment template metadata is invalid JSON") from error
    expected = {
        "schema_version",
        "height",
        "width",
        "crs",
        "transform",
        "registration",
        "factor",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("alignment template metadata fields are invalid")
    if payload["schema_version"] != 1:
        raise ValueError("alignment template schema version is unsupported")
    try:
        profile = GridProfile(
            payload["height"],
            payload["width"],
            payload["crs"],
            Affine(*payload["transform"]),
            payload["registration"],
        )
        return DefsourAlignmentTemplate(profile, payload["factor"], x, y)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid alignment template: {error}") from error


__all__ = [
    "DefsourAlignmentTemplate",
    "load_alignment_template",
    "save_alignment_template",
]
