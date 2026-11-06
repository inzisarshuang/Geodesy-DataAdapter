from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import rasterio

from insar_data_adapter.workflows.defsour.config import load_mintpy_defsour_config
from insar_data_adapter.workflows.defsour.mintpy import export_mintpy_defsour
from insar_data_adapter.sources.mintpy import MintPyGridSource


class MintPyDefsourWorkflowTests(unittest.TestCase):
    def fixture(
        self,
        root: Path,
        *,
        output: str = "export",
        native_only: bool = False,
    ) -> Path:
        values = np.array(
            [
                [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]],
                [[0, 2, 4, 6], [8, 10, np.nan, 14], [16, 18, 20, 22]],
            ],
            dtype=np.float32,
        )
        with h5py.File(root / "timeseries.h5", "w") as handle:
            dataset = handle.create_dataset("custom_timeseries", data=values)
            dataset.attrs["UNIT"] = "m"
            handle.create_dataset("custom_date", data=np.array([b"20240101", b"20240113"]))
            handle.attrs.update(
                {
                    "LENGTH": 3,
                    "WIDTH": 4,
                    "X_FIRST": 100.0,
                    "X_STEP": 0.01,
                    "Y_FIRST": 35.0,
                    "Y_STEP": -0.01,
                    "EPSG": 4326,
                    "REF_DATE": "20240101",
                    "REF_X": 1,
                    "REF_Y": 1,
                }
            )
        height = np.arange(12, dtype=np.float32).reshape(3, 4)
        with h5py.File(root / "geometry.h5", "w") as handle:
            handle.create_dataset("custom_height", data=height)
            handle.attrs.update(
                {
                    "X_FIRST": 100.0,
                    "X_STEP": 0.01,
                    "Y_FIRST": 35.0,
                    "Y_STEP": -0.01,
                    "EPSG": 4326,
                }
            )
        mask = np.ones((3, 4), dtype=np.uint8)
        mask[1, 2] = 0
        with h5py.File(root / "mask.h5", "w") as handle:
            handle.create_dataset("custom_mask", data=mask)
        with h5py.File(root / "velocity.h5", "w") as handle:
            handle.create_dataset("custom_velocity", data=np.ones((3, 4), dtype=np.float32))

        cfg = root / f"{output}.cfg"
        cfg.write_text(
            f"""output_dir = {output}
dates = all
prefix = mintpy_
extension = .txt
source_crs = EPSG:4326
output_crs = EPSG:32647
format = %.3f %.3f %.3f %.3f
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = finite values and explicit mask
temporal_reference = first
spatial_reference = preserve
source_provenance = synthetic MintPy
downsample_mode = factor
factor = 1
aggregation = mean
chunk_rows = 1
write_tif = true
overwrite = true
timeseries_file = timeseries.h5
geometry_file = geometry.h5
mask_file = mask.h5
velocity_file = velocity.h5
timeseries_dataset = custom_timeseries
date_dataset = custom_date
height_dataset = custom_height
mask_dataset = custom_mask
velocity_dataset = custom_velocity
write_native_tif = true
write_velocity_tif = true
write_dem_tif = true
native_only = {str(native_only).lower()}
"""
        )
        return cfg

    def test_exports_selected_epochs_native_static_and_downsampled_products(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = export_mintpy_defsour(
                load_mintpy_defsour_config(self.fixture(root))
            )

            self.assertEqual([epoch.date for epoch in result.epochs], ["20240101", "20240113"])
            first = np.loadtxt(root / "export/epochs/mintpy_20240101.txt")
            second = np.loadtxt(root / "export/epochs/mintpy_20240113.txt")
            self.assertTrue(np.all(first[:, 3] == 0.0))
            self.assertNotEqual(len(second), 12)
            self.assertTrue((root / "export/native/mintpy_20240113.tif").is_file())
            self.assertTrue((root / "export/native/velocity.tif").is_file())
            self.assertTrue((root / "export/native/dem.tif").is_file())
            manifest = json.loads((root / "export/defsour_manifest.json").read_text())
            self.assertEqual(manifest["metadata"]["temporal_reference"], "20240101")
            self.assertEqual(
                manifest["metadata"]["spatial_reference"],
                "mintpy_REF_Y=1,REF_X=1",
            )
            with rasterio.open(root / "export/native/mintpy_20240113.tif") as dataset:
                self.assertEqual(dataset.crs.to_string(), "EPSG:4326")
                self.assertEqual(dataset.tags()["unit"], "mm")
            with rasterio.open(root / "export/native/dem.tif") as dataset:
                self.assertEqual(float(dataset.read(1)[0, 0]), 0.0)

    def test_native_only_publishes_tifs_without_defsour_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root, output="native", native_only=True)
            cfg.write_text(cfg.read_text().replace("write_tif = true", "write_tif = false"))
            result = export_mintpy_defsour(load_mintpy_defsour_config(cfg))
            self.assertTrue(all(epoch.defsour_path is None for epoch in result.epochs))
            self.assertFalse((root / "native/epochs").exists())
            self.assertTrue((root / "native/native/mintpy_20240113.tif").is_file())

    def test_reads_epochs_in_configured_row_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_mintpy_defsour_config(self.fixture(root))
            original = MintPyGridSource.read_deformation_rows
            spans: list[int] = []

            def tracked(source, epoch_index, row_start, row_stop):
                spans.append(row_stop - row_start)
                return original(source, epoch_index, row_start, row_stop)

            with patch.object(MintPyGridSource, "read_deformation_rows", tracked):
                export_mintpy_defsour(config)
            self.assertTrue(spans)
            self.assertLessEqual(max(spans), config.chunk_rows)

    def test_late_epoch_failure_preserves_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_mintpy_defsour_config(self.fixture(root))
            export_mintpy_defsour(config)
            manifest = root / "export/defsour_manifest.json"
            before = manifest.read_bytes()
            original = MintPyGridSource.read_deformation_rows

            def fail_second(source, epoch_index, row_start, row_stop):
                if epoch_index == 1:
                    raise OSError("forced second-epoch read failure")
                return original(source, epoch_index, row_start, row_stop)

            with patch.object(MintPyGridSource, "read_deformation_rows", fail_second):
                with self.assertRaisesRegex(OSError, "second-epoch"):
                    export_mintpy_defsour(config)
            self.assertEqual(manifest.read_bytes(), before)

    def test_reference_outside_selected_dates_and_geometry_conflict_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            cfg.write_text(
                cfg.read_text()
                .replace("dates = all", "dates = 20240113")
                .replace("temporal_reference = first", "temporal_reference = 20240101")
            )
            with self.assertRaisesRegex(ValueError, "included in dates"):
                load_mintpy_defsour_config(cfg)

            cfg = self.fixture(root, output="conflict")
            with h5py.File(root / "geometry.h5", "r+") as handle:
                handle.attrs["EPSG"] = 32647
            with self.assertRaisesRegex(ValueError, "EPSG"):
                export_mintpy_defsour(load_mintpy_defsour_config(cfg))
            self.assertFalse((root / "conflict").exists())


if __name__ == "__main__":
    unittest.main()
