from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from insar_data_adapter.workflows.defsour.config import load_geotiff_defsour_config
from insar_data_adapter.workflows.defsour.geotiff_series import (
    export_geotiff_defsour,
)


class GeoTIFFDefsourWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.transform = from_origin(-156.0, 20.0, 0.001, 0.001)

    def write_raster(
        self,
        path: Path,
        values: np.ndarray,
        *,
        transform=None,
        crs: str = "EPSG:4326",
        nodata=None,
    ) -> None:
        data = np.asarray(values, dtype=np.float32)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform or self.transform,
            nodata=nodata,
        ) as dataset:
            dataset.write(data, 1)

    def config(self, *, write_tif: bool = True) -> Path:
        index = self.root / "series.txt"
        index.write_text(
            "20240101T123456 zero.tif\n"
            "20240113T234501 one.tif\n",
            encoding="utf-8",
        )
        self.write_raster(self.root / "zero.tif", np.zeros((6, 6)), nodata=0.0)
        self.write_raster(self.root / "one.tif", np.ones((6, 6)), nodata=0.0)
        self.write_raster(self.root / "dem.tif", np.full((6, 6), 100.0), nodata=np.nan)
        self.write_raster(self.root / "mask.tif", np.ones((6, 6)), nodata=0.0)
        config = self.root / "geotiff.cfg"
        config.write_text(
            f"""output_dir = output
epochs = all
prefix = D
extension = .txt
source_crs = EPSG:4326
output_crs = EPSG:4326
format = %.6f %.6f %.3f %.3f
source_unit = m
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = source_values_preserved_direction_unknown
nodata_policy = finite deformation and DEM plus positive mask; zero is valid
temporal_reference = preserve
spatial_reference = preserve upstream spatial reference
source_provenance = synthetic indexed GeoTIFF series
downsample_mode = target_points
target_points = 4
aggregation = mean
chunk_rows = 3
write_tif = {str(write_tif).lower()}
overwrite = true
index_file = series.txt
height_file = dem.tif
mask_file = mask.tif
mask_mode = positive
""",
            encoding="utf-8",
        )
        return config

    def test_exports_ordered_exact_epochs_with_one_scale_and_real_zeros(self) -> None:
        config = load_geotiff_defsour_config(self.config())
        config.output_dir.mkdir()
        (config.output_dir / "old.txt").write_text("old", encoding="utf-8")

        result = export_geotiff_defsour(config)

        self.assertEqual(
            tuple(epoch.epoch_id for epoch in result.epochs),
            ("20240101T123456", "20240113T234501"),
        )
        self.assertEqual(tuple(epoch.date for epoch in result.epochs), ("20240101", "20240113"))
        self.assertEqual(tuple(epoch.point_count for epoch in result.epochs), (4, 4))
        self.assertFalse((config.output_dir / "old.txt").exists())
        zero = np.loadtxt(config.output_dir / "epochs/D20240101T123456.txt")
        one = np.loadtxt(config.output_dir / "epochs/D20240113T234501.txt")
        np.testing.assert_array_equal(zero[:, 3], np.zeros(4))
        np.testing.assert_array_equal(one[:, 3], np.full(4, 1000.0))
        self.assertTrue((config.output_dir / "geotiff/D20240101T123456.tif").is_file())
        manifest = json.loads((config.output_dir / "defsour_manifest.json").read_text())
        self.assertEqual(
            [epoch["epoch_id"] for epoch in manifest["epochs"]],
            ["20240101T123456", "20240113T234501"],
        )
        self.assertEqual(manifest["metadata"]["crs"], "EPSG:4326")
        self.assertEqual(manifest["metadata"]["deformation_unit"], "mm")
        self.assertEqual(manifest["transformations"]["downsample_factor"], 3)
        self.assertEqual(manifest["transformations"]["source_unit"], "m")

    def test_selected_epochs_preserve_requested_index_order(self) -> None:
        config_path = self.config(write_tif=False)
        config_path.write_text(
            config_path.read_text().replace(
                "epochs = all",
                "epochs = 20240113T234501, 20240101T123456",
            )
        )
        config = load_geotiff_defsour_config(config_path)

        result = export_geotiff_defsour(config)

        self.assertEqual(
            tuple(epoch.epoch_id for epoch in result.epochs),
            ("20240113T234501", "20240101T123456"),
        )
        self.assertTrue(all(epoch.geotiff_path is None for epoch in result.epochs))

    def test_late_raster_failures_preserve_existing_snapshot(self) -> None:
        cases = ("shape", "transform", "crs", "unreadable")
        for mode in cases:
            with self.subTest(mode=mode):
                config = load_geotiff_defsour_config(self.config())
                config.output_dir.mkdir(exist_ok=True)
                old = config.output_dir / "old.txt"
                old.write_text("old", encoding="utf-8")
                second = self.root / "one.tif"
                if mode == "unreadable":
                    second.write_bytes(b"not a TIFF")
                else:
                    values = np.ones((5, 6) if mode == "shape" else (6, 6))
                    transform = (
                        from_origin(-156.0, 20.0, 0.002, 0.001)
                        if mode == "transform"
                        else self.transform
                    )
                    crs = "EPSG:3857" if mode == "crs" else "EPSG:4326"
                    self.write_raster(second, values, transform=transform, crs=crs)

                with self.assertRaises(Exception):
                    export_geotiff_defsour(config)

                self.assertEqual(old.read_text(), "old")
                self.assertEqual({path.name for path in config.output_dir.iterdir()}, {"old.txt"})


if __name__ == "__main__":
    unittest.main()
