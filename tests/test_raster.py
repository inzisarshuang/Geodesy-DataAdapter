"""Tests for source-neutral profile-aware raster transformations."""

from __future__ import annotations

import unittest

import numpy as np
from rasterio.transform import from_origin

from insar_data_adapter import (
    reproject_downsampled_grid_to_profile,
    reproject_static_grid_to_profile,
)


class StaticGridReprojectionTests(unittest.TestCase):
    """Preserve values, explicit validity, dtype, and destination shape."""

    def test_identity_grid_keeps_only_explicitly_valid_values(self) -> None:
        """Do not let a finite value marked invalid re-enter the output."""
        profile = {
            "height": 2,
            "width": 2,
            "transform": from_origin(0.0, 2.0, 1.0, 1.0),
            "crs": "EPSG:4326",
        }
        values = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        valid = np.array([[True, False], [True, True]])

        output, output_valid = reproject_static_grid_to_profile(
            values,
            valid,
            source_profile=profile,
            destination_profile=profile,
        )

        np.testing.assert_allclose(
            output,
            np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32),
            equal_nan=True,
        )
        np.testing.assert_array_equal(output_valid, valid)
        self.assertEqual(output.dtype, np.dtype("float32"))


class DownsampledGridReprojectionTests(unittest.TestCase):
    """Preserve two-grid fallback and georeferenced reprojection behavior."""

    def test_unreferenced_equal_grid_returns_independent_copies(self) -> None:
        """Keep the legacy no-georeference fallback without aliasing inputs."""
        dem = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        deform = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        valid = np.array([[True, False], [True, True]])

        dem_out, deform_out, valid_out = reproject_downsampled_grid_to_profile(
            dem,
            deform,
            valid,
            source_profile={},
            destination_profile={"height": 2, "width": 2},
        )

        np.testing.assert_array_equal(dem_out, dem)
        np.testing.assert_array_equal(deform_out, deform)
        np.testing.assert_array_equal(valid_out, valid)
        self.assertIsNot(dem_out, dem)
        self.assertIsNot(deform_out, deform)
        self.assertIsNot(valid_out, valid)

    def test_identity_grid_keeps_shared_explicit_validity(self) -> None:
        """Mask both numeric grids before reprojection and return float32 grids."""
        profile = {
            "height": 2,
            "width": 2,
            "transform": from_origin(0.0, 2.0, 1.0, 1.0),
            "crs": "EPSG:4326",
        }
        dem = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float64)
        deform = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        valid = np.array([[True, False], [True, True]])

        dem_out, deform_out, valid_out = (
            reproject_downsampled_grid_to_profile(
                dem,
                deform,
                valid,
                source_profile=profile,
                destination_profile=profile,
            )
        )

        np.testing.assert_allclose(
            dem_out,
            np.array([[10.0, np.nan], [30.0, 40.0]], dtype=np.float32),
            equal_nan=True,
        )
        np.testing.assert_allclose(
            deform_out,
            np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32),
            equal_nan=True,
        )
        np.testing.assert_array_equal(valid_out, valid)
        self.assertEqual(dem_out.dtype, np.dtype("float32"))
        self.assertEqual(deform_out.dtype, np.dtype("float32"))

    def test_unreferenced_shape_change_raises_legacy_error(self) -> None:
        """Reject shape changes when either profile lacks georeferencing."""
        with self.assertRaisesRegex(
            ValueError,
            "aligned mode requires georeferenced reference grids "
            "when input and template shapes differ",
        ):
            reproject_downsampled_grid_to_profile(
                np.ones((2, 2)),
                np.ones((2, 2)),
                np.ones((2, 2), dtype=bool),
                source_profile={},
                destination_profile={"height": 3, "width": 2},
            )


if __name__ == "__main__":
    unittest.main()
