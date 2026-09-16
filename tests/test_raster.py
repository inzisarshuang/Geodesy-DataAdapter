"""Tests for source-neutral profile-aware raster transformations."""

from __future__ import annotations

import unittest

import numpy as np
from rasterio.transform import from_origin

from insar_data_adapter import reproject_static_grid_to_profile


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


if __name__ == "__main__":
    unittest.main()
