"""Whole-directory transactional publication for Defsour snapshots."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .models import DefsourSnapshotMetadata


def _required_products(metadata: DefsourSnapshotMetadata) -> tuple[Path, ...]:
    products: list[Path] = []
    for epoch in metadata.epochs:
        products.append(epoch.defsour_path)
        if epoch.geotiff_path is not None:
            products.append(epoch.geotiff_path)
    products.extend(metadata.additional_products)
    if len(set(products)) != len(products):
        raise ValueError("Defsour snapshot contains duplicate product paths")
    return tuple(products)


def _validate_products(staging: Path, metadata: DefsourSnapshotMetadata) -> tuple[Path, ...]:
    try:
        json.dumps(dict(metadata.transformations), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Defsour transformations must be finite JSON metadata") from error
    products = _required_products(metadata)
    for relative in products:
        product = staging / relative
        if product.is_symlink() or not product.is_file() or product.stat().st_size < 1:
            raise ValueError(f"Defsour required product is missing or empty: {relative}")
    return products


def _readme(metadata: DefsourSnapshotMetadata) -> str:
    values = asdict(metadata.metadata)
    lines = [
        "Defsour transactional snapshot",
        f"source: {metadata.source}",
        f"dates: {', '.join(epoch.date for epoch in metadata.epochs)}",
        f"point_counts: {', '.join(str(epoch.point_count) for epoch in metadata.epochs)}",
    ]
    lines.extend(f"{key}: {value}" for key, value in values.items())
    lines.append(
        "transformations: "
        + json.dumps(dict(metadata.transformations), sort_keys=True, allow_nan=False)
    )
    return "\n".join(lines) + "\n"


def _write_completion_files(
    staging: Path,
    metadata: DefsourSnapshotMetadata,
    products: tuple[Path, ...],
) -> None:
    readme = staging / "README_DEFSOUR.txt"
    readme.write_text(_readme(metadata), encoding="utf-8")
    required = [path.as_posix() for path in products]
    required.append(readme.name)
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "source": metadata.source,
        "dates": [epoch.date for epoch in metadata.epochs],
        "point_counts": [epoch.point_count for epoch in metadata.epochs],
        "epochs": [
            {
                "date": epoch.date,
                "defsour_path": epoch.defsour_path.as_posix(),
                "point_count": epoch.point_count,
                "geotiff_path": (
                    None
                    if epoch.geotiff_path is None
                    else epoch.geotiff_path.as_posix()
                ),
            }
            for epoch in metadata.epochs
        ],
        "metadata": asdict(metadata.metadata),
        "transformations": dict(metadata.transformations),
        "required_products": required,
    }
    (staging / "defsour_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def publish_defsour_snapshot(
    output_dir: Path,
    build: Callable[[Path], DefsourSnapshotMetadata],
    *,
    overwrite: bool = True,
) -> DefsourSnapshotMetadata:
    """Build and atomically replace one complete Defsour export directory."""

    raw = Path(output_dir).expanduser()
    parent = raw.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / raw.name
    if output.is_symlink():
        raise ValueError(f"Defsour output directory must not be a symlink: {output}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Defsour snapshot already exists: {output}")
    if output.exists() and not output.is_dir():
        raise ValueError(f"Defsour output exists and is not a directory: {output}")

    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=parent)
    )
    backup: Path | None = None
    try:
        metadata = build(staging)
        if not isinstance(metadata, DefsourSnapshotMetadata):
            raise TypeError("Defsour snapshot builder must return DefsourSnapshotMetadata")
        products = _validate_products(staging, metadata)
        _write_completion_files(staging, metadata, products)
        if output.exists():
            backup = parent / f".{output.name}.backup-{uuid.uuid4().hex}"
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except BaseException:
            if backup is not None and backup.exists():
                os.replace(backup, output)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return metadata
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and output.exists():
            shutil.rmtree(backup)


__all__ = ["publish_defsour_snapshot"]
