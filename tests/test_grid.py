"""Tests for source-neutral bounded grid transformations."""

from __future__ import annotations

import unittest

import numpy as np

from insar_data_adapter import (
    aggregate_grid_array,
    build_defsour_valid_mask,
    downsample_data_grid,
)


class DefsourValidityTests(unittest.TestCase):
    """Preserve finite-value, sentinel, mask, and zero-value behavior."""

    def test_combines_every_explicit_invalidity_source(self) -> None:
        """Exclude non-finite values, configured sentinels, and false mask cells."""
        x = np.array([[0.0, 1.0, np.nan], [3.0, 4.0, 5.0]])
        y = np.array([[0.0, 1.0, 2.0], [np.inf, 4.0, 5.0]])
        dem = np.array([[0.0, -9999.0, 2.0], [3.0, 4.0, 5.0]])
        deform = np.array([[0.0, 1.0, 2.0], [3.0, -8888.0, 5.0]])
        external = np.array([[True, True, True], [True, True, False]])
        actual = build_defsour_valid_mask(
            x,
            y,
            dem,
            deform,
            nodata_dem=-9999.0,
            nodata_deform=-8888.0,
            valid_mask=external,
        )
        np.testing.assert_array_equal(
            actual,
            [[True, False, False], [False, False, False]],
        )

    def test_zero_is_valid_without_an_explicit_zero_sentinel(self) -> None:
        """Never reinterpret finite zero coordinates or measurements as nodata."""
        zeros = np.zeros((2, 2), dtype=np.float32)
        np.testing.assert_array_equal(
            build_defsour_valid_mask(zeros, zeros, zeros, zeros),
            np.ones((2, 2), dtype=bool),
        )


class GridAggregationTests(unittest.TestCase):
    """Preserve aggregation values, edge policy, and validation."""

    def test_downsample_data_grid_uses_one_mask_for_all_outputs(self) -> None:
        """Aggregate DEM/deformation together and derive the finite output mask."""
        dem = np.array(
            [[1.0, 2.0, 10.0, 14.0], [3.0, 100.0, 18.0, 22.0]]
        )
        deform = np.array(
            [[2.0, 4.0, 20.0, 28.0], [6.0, 200.0, 36.0, 44.0]]
        )
        valid = np.array(
            [[True, True, False, False], [True, False, False, False]]
        )

        dem_out, deform_out, valid_out = downsample_data_grid(
            dem, deform, valid, factor=2, method="mean"
        )

        np.testing.assert_allclose(dem_out, [[2.0, np.nan]], equal_nan=True)
        np.testing.assert_allclose(deform_out, [[4.0, np.nan]], equal_nan=True)
        np.testing.assert_array_equal(valid_out, [[True, False]])

    def test_mean_and_median_match_full_window_reference(self) -> None:
        """Match NumPy references across multiple bounded output blocks."""
        values = np.arange(72, dtype=np.float32).reshape(8, 9)
        valid = (values % 5) != 0
        trimmed = values[:, :8].reshape(4, 2, 4, 2)
        selected = np.where(valid[:, :8].reshape(4, 2, 4, 2), trimmed, np.nan)
        with np.errstate(invalid="ignore"):
            expected_mean = np.nanmean(selected, axis=(1, 3))
            expected_median = np.nanmedian(selected, axis=(1, 3))

        np.testing.assert_allclose(
            aggregate_grid_array(values, valid, 2, "mean", block_output_rows=1),
            expected_mean,
            equal_nan=True,
        )
        np.testing.assert_allclose(
            aggregate_grid_array(values, valid, 2, "median", block_output_rows=1),
            expected_median,
            equal_nan=True,
        )

    def test_empty_windows_are_nan_and_incomplete_edges_are_dropped(self) -> None:
        """Make nodata and bottom/right edge behavior explicit."""
        values = np.arange(35, dtype=np.float64).reshape(5, 7)
        valid = np.ones_like(values, dtype=bool)
        valid[:2, :2] = False
        output = aggregate_grid_array(values, valid, 2, "mean")
        self.assertEqual(output.shape, (2, 3))
        self.assertTrue(np.isnan(output[0, 0]))
        self.assertEqual(output[1, 2], np.mean(values[2:4, 4:6]))

    def test_rejects_ambiguous_shapes_factors_blocks_and_methods(self) -> None:
        """Reject settings that do not define one valid aggregation."""
        values = np.ones((2, 3), dtype=float)
        with self.assertRaisesRegex(ValueError, "arr and valid"):
            aggregate_grid_array(values, np.ones((2, 2), dtype=bool), 1, "mean")
        with self.assertRaisesRegex(ValueError, "grid_downsample_factor"):
            aggregate_grid_array(values, np.ones_like(values), 0, "mean")
        with self.assertRaisesRegex(ValueError, "block_output_rows"):
            aggregate_grid_array(values, np.ones_like(values), 1, "mean", 0)
        with self.assertRaisesRegex(ValueError, "grid_aggregation"):
            aggregate_grid_array(values, np.ones_like(values), 1, "maximum")
        with self.assertRaisesRegex(ValueError, "larger"):
            aggregate_grid_array(values, np.ones_like(values), 4, "mean")


if __name__ == "__main__":
    unittest.main()
