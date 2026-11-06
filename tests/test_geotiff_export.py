from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

from insar_data_adapter.exporters.geotiff import write_geotiff
from insar_data_adapter.workflows.defsour.grid import GridProfile


class GeoTiffExportTests(unittest.TestCase):
    def profile(self) -> GridProfile:
        return GridProfile(
            2,
            3,
            "EPSG:32647",
            from_origin(100.0, 500.0, 10.0, 10.0),
            "pixel_center",
        )

    def test_writes_profile_mask_nodata_and_scientific_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "epoch.tif"
            values = np.array([[0.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
            valid = np.array([[True, False, True], [True, True, False]])
            self.assertEqual(
                write_geotiff(
                    output,
                    values,
                    valid,
                    self.profile(),
                    unit="m",
                    quantity="cumulative_displacement",
                ),
                output,
            )
            with rasterio.open(output) as dataset:
                self.assertEqual((dataset.height, dataset.width, dataset.count), (2, 3, 1))
                self.assertEqual(dataset.crs.to_string(), "EPSG:32647")
                self.assertTrue(np.isnan(dataset.nodata))
                data = dataset.read(1)
                self.assertEqual(data[0, 0], 0.0)
                self.assertTrue(np.isnan(data[0, 1]))
                self.assertTrue(np.isnan(data[1, 2]))
                self.assertEqual(dataset.tags()["unit"], "m")
                self.assertEqual(
                    dataset.tags()["quantity"], "cumulative_displacement"
                )
                self.assertEqual(dataset.tags()["pixel_registration"], "pixel_center")

    def test_overwrites_atomically_and_failure_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "epoch.tif"
            profile = self.profile()
            valid = np.ones((2, 3), dtype=bool)
            write_geotiff(output, np.ones((2, 3)), valid, profile, unit="m", quantity="height")
            before = output.read_bytes()
            with patch(
                "insar_data_adapter.exporters.geotiff.rasterio.open",
                side_effect=RuntimeError("synthetic writer failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    write_geotiff(
                        output,
                        np.full((2, 3), 2.0),
                        valid,
                        profile,
                        unit="m",
                        quantity="height",
                    )
            self.assertEqual(output.read_bytes(), before)
            write_geotiff(
                output,
                np.full((2, 3), 2.0),
                valid,
                profile,
                unit="m",
                quantity="height",
            )
            with rasterio.open(output) as dataset:
                np.testing.assert_array_equal(dataset.read(1), np.full((2, 3), 2.0))

    def test_rejects_shape_nonfinite_nodata_and_blank_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "epoch.tif"
            profile = self.profile()
            values = np.ones((2, 3))
            valid = np.ones((2, 3), dtype=bool)
            for candidate, mask, unit, quantity, nodata in (
                (values[:, :2], valid, "m", "height", np.nan),
                (values, valid[:, :2], "m", "height", np.nan),
                (values, valid, "", "height", np.nan),
                (values, valid, "m", "", np.nan),
                (values, valid, "m", "height", np.inf),
            ):
                with self.subTest(unit=unit, quantity=quantity, nodata=nodata), self.assertRaises(ValueError):
                    write_geotiff(
                        output,
                        candidate,
                        mask,
                        profile,
                        unit=unit,
                        quantity=quantity,
                        nodata=nodata,
                    )


if __name__ == "__main__":
    unittest.main()
