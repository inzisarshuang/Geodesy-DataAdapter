"""Tests for source-neutral bounded grid transformations."""

from __future__ import annotations

import unittest

import numpy as np

from insar_data_adapter import aggregate_grid_array


class GridAggregationTests(unittest.TestCase):
    """Preserve aggregation values, edge policy, and validation."""

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
