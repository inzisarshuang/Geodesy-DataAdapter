from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import rasterio

from insar_data_adapter.sources.licsbas import LiCSBASGridSource
from insar_data_adapter.workflows.defsour.config import load_licsbas_defsour_config
from insar_data_adapter.workflows.defsour.licsbas import export_licsbas_defsour


class LiCSBASDefsourWorkflowTests(unittest.TestCase):
    def fixture(self, root: Path, output: str = "export") -> Path:
        values = np.array(
            [
                [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]],
                [[0, 2, 4, 6], [8, 10, np.nan, 14], [16, 18, 20, 22]],
            ],
            dtype=np.float32,
        )
        with h5py.File(root / "licsbas.h5", "w") as handle:
            dataset = handle.create_dataset("custom_cum", data=values)
            dataset.attrs["UNIT"] = "mm"
            handle.create_dataset("custom_dates", data=np.array([20240101, 20240113]))
            handle.create_dataset(
                "custom_height", data=np.arange(12, dtype=np.float32).reshape(3, 4)
            )
            mask = np.ones((3, 4), dtype=np.uint8)
            mask[1, 2] = 0
            handle.create_dataset("custom_mask", data=mask)
            handle.create_dataset("corner_lon", data=100.0)
            handle.create_dataset("corner_lat", data=35.0)
            handle.create_dataset("post_lon", data=0.01)
            handle.create_dataset("post_lat", data=-0.01)
            handle.create_dataset("custom_refarea", data=np.bytes_("1:3/0:2"))
            handle.attrs["CRS"] = "EPSG:4326"
        cfg = root / f"{output}.cfg"
        cfg.write_text(
            f"""output_dir = {output}
dates = all
prefix = licsbas_
extension = .txt
source_crs = EPSG:4326
output_crs = EPSG:32647
format = %.3f %.3f %.3f %.3f
deformation_scale = 1
source_unit = mm
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = finite values and LiCSBAS mask
temporal_reference = first
spatial_reference = preserve
source_provenance = synthetic LiCSBAS
downsample_mode = factor
factor = 1
aggregation = mean
chunk_rows = 1
write_tif = true
overwrite = true
input_file = licsbas.h5
deformation_dataset = custom_cum
date_dataset = custom_dates
height_dataset = custom_height
mask_dataset = custom_mask
refarea_dataset = custom_refarea
"""
        )
        return cfg

    def test_exports_scaled_selected_epochs_refarea_and_geotiff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = export_licsbas_defsour(
                load_licsbas_defsour_config(self.fixture(root))
            )
            self.assertEqual([epoch.date for epoch in result.epochs], ["20240101", "20240113"])
            first = np.loadtxt(root / "export/epochs/licsbas_20240101.txt")
            second = np.loadtxt(root / "export/epochs/licsbas_20240113.txt")
            self.assertTrue(np.all(first[:, 3] == 0.0))
            self.assertLess(len(second), 12)
            self.assertTrue((root / "export/geotiff/licsbas_20240113.tif").is_file())
            manifest = json.loads((root / "export/defsour_manifest.json").read_text())
            self.assertEqual(manifest["metadata"]["deformation_unit"], "mm")
            self.assertEqual(
                manifest["metadata"]["spatial_reference"],
                "licsbas_refarea=1:3/0:2",
            )

    def test_late_epoch_failure_preserves_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_licsbas_defsour_config(self.fixture(root))
            export_licsbas_defsour(config)
            manifest = root / "export/defsour_manifest.json"
            before = manifest.read_bytes()
            original = LiCSBASGridSource.read_deformation_rows

            def fail_second(source, epoch_index, row_start, row_stop):
                if epoch_index == 1:
                    raise OSError("forced second-epoch read failure")
                return original(source, epoch_index, row_start, row_stop)

            with patch.object(LiCSBASGridSource, "read_deformation_rows", fail_second):
                with self.assertRaisesRegex(OSError, "second-epoch"):
                    export_licsbas_defsour(config)
            self.assertEqual(manifest.read_bytes(), before)

    def test_output_projection_preserves_downsampled_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            cfg.write_text(cfg.read_text().replace("factor = 1", "factor = 2"))

            result = export_licsbas_defsour(load_licsbas_defsour_config(cfg))

            self.assertEqual([epoch.point_count for epoch in result.epochs], [2, 2])
            with rasterio.open(root / "export/geotiff/licsbas_20240101.tif") as dataset:
                self.assertEqual(dataset.shape, (1, 2))

    def test_refarea_and_declared_unit_conflicts_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            with h5py.File(root / "licsbas.h5", "r+") as handle:
                handle["custom_refarea"][...] = np.bytes_("bad")
            with self.assertRaisesRegex(ValueError, "refarea"):
                export_licsbas_defsour(load_licsbas_defsour_config(cfg))
            self.assertFalse((root / "export").exists())

            cfg = self.fixture(root, "unit-conflict")
            cfg.write_text(cfg.read_text().replace("source_unit = mm", "source_unit = m"))
            with self.assertRaisesRegex(ValueError, "unit"):
                export_licsbas_defsour(load_licsbas_defsour_config(cfg))

    def test_duplicate_source_dates_are_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            with h5py.File(root / "licsbas.h5", "r+") as handle:
                handle["custom_dates"][...] = np.array([20240101, 20240101])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                export_licsbas_defsour(load_licsbas_defsour_config(cfg))
            self.assertFalse((root / "export").exists())


if __name__ == "__main__":
    unittest.main()
