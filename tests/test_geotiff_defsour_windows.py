from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from insar_data_adapter.workflows.defsour.geotiff_series import (
    _native_windows,
    _prepare_epoch_grid,
    _prepare_static_grid,
    _profile_from_raster,
)


class GeoTIFFDefsourWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(
        self,
        name: str,
        values: np.ndarray,
        *,
        transform=None,
        nodata=None,
        crs: str = "EPSG:4326",
        driver: str = "GTiff",
        dtype: str = "float32",
        area_or_point: str | None = None,
    ) -> Path:
        path = self.root / name
        data = np.asarray(values, dtype=dtype)
        with rasterio.open(
            path,
            "w",
            driver=driver,
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=dtype,
            crs=crs,
            transform=transform or from_origin(0.0, float(data.shape[0]), 1.0, 1.0),
            nodata=nodata,
        ) as dataset:
            dataset.write(data, 1)
            if area_or_point is not None:
                dataset.update_tags(AREA_OR_POINT=area_or_point)
        return path

    def test_windows_are_factor_aligned_and_bounded(self) -> None:
        windows = tuple(_native_windows(11, 7, factor=2, chunk_rows=5))
        self.assertEqual(
            [(int(window.row_off), int(window.height), int(window.width)) for window in windows],
            [(0, 4, 6), (4, 4, 6), (8, 2, 6)],
        )
        self.assertTrue(all(window.height <= 5 for window in windows))

    def test_positive_mask_preserves_real_zero_and_drops_incomplete_edges(self) -> None:
        height = np.arange(25, dtype=np.float32).reshape(5, 5)
        deformation = height * 2.0
        deformation[0, 0] = 0.0
        mask = np.ones((5, 5), dtype=np.float32)
        mask[0, 1] = 0.0
        deformation_path = self.write("deformation.tif", deformation, nodata=0.0)
        height_path = self.write("height.tif", height, nodata=np.nan)
        mask_path = self.write("mask.tif", mask, nodata=0.0)
        profile = _profile_from_raster(deformation_path, "EPSG:4326")
        static = _prepare_static_grid(
            height_path,
            mask_path,
            profile,
            chunk_rows=2,
            mask_mode="positive",
        )

        prepared = _prepare_epoch_grid(
            deformation_path,
            static,
            factor=2,
            aggregation="mean",
            chunk_rows=2,
        )

        self.assertEqual(prepared.height.shape, (2, 2))
        self.assertEqual(prepared.deformation[0, 0], np.mean([0.0, 10.0, 12.0]))
        self.assertTrue(prepared.valid.all())
        self.assertEqual(prepared.x[0, 0], 1.0)
        self.assertEqual(prepared.y[0, 0], 4.0)

        median = _prepare_epoch_grid(
            deformation_path,
            static,
            factor=2,
            aggregation="median",
            chunk_rows=4,
        )
        self.assertEqual(median.deformation[0, 0], 10.0)

    def test_aligns_coarser_dem_and_mask_with_explicit_resampling(self) -> None:
        deformation_path = self.write("deformation.tif", np.ones((4, 4)))
        coarse_transform = from_origin(0.0, 4.0, 2.0, 2.0)
        height_path = self.write(
            "height.tif",
            np.array([[10.0, 20.0], [30.0, 40.0]]),
            transform=coarse_transform,
            nodata=np.nan,
        )
        mask_path = self.write(
            "mask.tif",
            np.ones((2, 2)),
            transform=coarse_transform,
            nodata=0.0,
        )
        profile = _profile_from_raster(deformation_path, "EPSG:4326")

        static = _prepare_static_grid(
            height_path,
            mask_path,
            profile,
            chunk_rows=2,
            mask_mode="positive",
        )
        prepared = _prepare_epoch_grid(
            deformation_path,
            static,
            factor=1,
            aggregation="mean",
            chunk_rows=2,
        )

        self.assertEqual(static.valid_count, 16)
        self.assertTrue(prepared.valid.all())
        self.assertTrue(np.isfinite(prepared.height).all())
        self.assertGreater(float(prepared.height.max()), float(prepared.height.min()))

    def test_rejects_positive_mask_cells_outside_dem_coverage(self) -> None:
        deformation_path = self.write("deformation.tif", np.ones((4, 4)))
        height_path = self.write(
            "height.tif",
            np.ones((2, 2)),
            transform=from_origin(0.0, 4.0, 1.0, 1.0),
            nodata=np.nan,
        )
        mask_path = self.write("mask.tif", np.ones((4, 4)), nodata=0.0)
        profile = _profile_from_raster(deformation_path, "EPSG:4326")

        with self.assertRaisesRegex(ValueError, "DEM coverage"):
            _prepare_static_grid(
                height_path,
                mask_path,
                profile,
                chunk_rows=2,
                mask_mode="positive",
            )

    def test_nan_dem_under_zero_mask_does_not_invalidate_adjacent_support(self) -> None:
        deformation_path = self.write("deformation.tif", np.ones((4, 4)))
        height_path = self.write(
            "height.tif",
            np.array([[np.nan, 10.0], [20.0, 30.0]]),
            transform=from_origin(0.0, 4.0, 2.0, 2.0),
            nodata=None,
        )
        mask = np.ones((4, 4), dtype=np.float32)
        mask[:2, :2] = 0.0
        mask_path = self.write("mask.tif", mask, nodata=0.0)
        profile = _profile_from_raster(deformation_path, "EPSG:4326")

        static = _prepare_static_grid(
            height_path,
            mask_path,
            profile,
            chunk_rows=2,
            mask_mode="positive",
        )

        self.assertEqual(static.valid_count, 12)

    def test_nonzero_deformation_nodata_is_excluded_but_zero_remains_valid(self) -> None:
        deformation = np.ones((3, 3), dtype=np.float32)
        deformation[0, 0] = -9999.0
        deformation[0, 1] = 0.0
        deformation_path = self.write(
            "deformation.tif", deformation, nodata=-9999.0
        )
        height_path = self.write("height.tif", np.ones((3, 3)), nodata=np.nan)
        mask_path = self.write("mask.tif", np.ones((3, 3)), nodata=0.0)
        profile = _profile_from_raster(deformation_path, "EPSG:4326")
        static = _prepare_static_grid(
            height_path,
            mask_path,
            profile,
            chunk_rows=3,
            mask_mode="positive",
        )

        prepared = _prepare_epoch_grid(
            deformation_path,
            static,
            factor=3,
            aggregation="mean",
            chunk_rows=3,
        )

        self.assertAlmostEqual(prepared.deformation[0, 0], 0.875)

    def test_rejects_non_geotiff_complex_and_point_registered_inputs(self) -> None:
        cases = (
            (
                self.write(
                    "not_tiff.asc",
                    np.ones((2, 2)),
                    driver="AAIGrid",
                ),
                "GeoTIFF",
            ),
            (
                self.write(
                    "complex.tif",
                    np.ones((2, 2), dtype=np.complex64) * (1 + 10j),
                    dtype="complex64",
                ),
                "real scalar",
            ),
            (
                self.write(
                    "point.tif",
                    np.ones((2, 2)),
                    area_or_point="Point",
                ),
                "pixel-area",
            ),
        )
        for path, message in cases:
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, message):
                _profile_from_raster(path, "EPSG:4326")


if __name__ == "__main__":
    unittest.main()
