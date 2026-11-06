from __future__ import annotations

import unittest

import numpy as np
from rasterio.transform import from_origin

from insar_data_adapter.workflows.defsour.grid import (
    GridProfile,
    coordinate_arrays,
    prepare_defsour_epoch,
    select_downsample_factor,
)


class DefsourGridWorkflowTests(unittest.TestCase):
    def profile(self, height=5, width=7, pixel=10.0) -> GridProfile:
        return GridProfile(
            height=height,
            width=width,
            crs="EPSG:32647",
            transform=from_origin(100.0, 500.0, pixel, pixel),
            registration="pixel_center",
        )

    def test_coordinate_arrays_are_row_major_pixel_centres(self) -> None:
        x, y = coordinate_arrays(self.profile(height=2, width=3))
        np.testing.assert_array_equal(x, [[105.0, 115.0, 125.0], [105.0, 115.0, 125.0]])
        np.testing.assert_array_equal(y, [[495.0, 495.0, 495.0], [485.0, 485.0, 485.0]])

    def test_factor_target_points_and_target_pixel_size_are_explicit(self) -> None:
        profile = self.profile()
        self.assertEqual(
            select_downsample_factor("factor", source_profile=profile, valid_count=35, factor=3),
            3,
        )
        self.assertEqual(
            select_downsample_factor(
                "target_points", source_profile=profile, valid_count=35, target_points=8
            ),
            3,
        )
        self.assertEqual(
            select_downsample_factor(
                "target_pixel_size",
                source_profile=profile,
                valid_count=35,
                target_pixel_size=24,
            ),
            3,
        )
        for mode, kwargs in (
            ("factor", {"factor": 0}),
            ("target_points", {"target_points": 0}),
            ("target_pixel_size", {"target_pixel_size": 0}),
            ("unknown", {}),
        ):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                select_downsample_factor(
                    mode, source_profile=profile, valid_count=35, **kwargs
                )

    def test_preparation_composes_mask_aggregation_and_drops_edges(self) -> None:
        profile = self.profile(height=5, width=5)
        height = np.arange(25, dtype=float).reshape(5, 5)
        deformation = height * 2
        height[0, 0] = 0.0
        deformation[0, 0] = 0.0
        valid = np.ones((5, 5), dtype=bool)
        valid[0, 1] = False
        prepared = prepare_defsour_epoch(
            height,
            deformation,
            valid,
            profile,
            factor=2,
            aggregation="mean",
        )
        self.assertEqual(prepared.height.shape, (2, 2))
        self.assertEqual((prepared.profile.height, prepared.profile.width), (2, 2))
        self.assertEqual(prepared.height[0, 0], np.mean([0.0, 5.0, 6.0]))
        self.assertEqual(prepared.deformation[0, 0], np.mean([0.0, 10.0, 12.0]))
        self.assertTrue(prepared.valid.all())
        self.assertEqual(prepared.x[0, 0], 110.0)
        self.assertEqual(prepared.y[0, 0], 490.0)

    def test_median_and_destination_reprojection_require_explicit_profiles(self) -> None:
        source = self.profile(height=2, width=2)
        values = np.array([[0.0, 100.0], [2.0, 4.0]])
        valid = np.array([[True, False], [True, True]])
        native = prepare_defsour_epoch(
            values, values, valid, source, factor=2, aggregation="median"
        )
        self.assertEqual(native.deformation[0, 0], 2.0)
        destination = GridProfile(
            1,
            1,
            "EPSG:32647",
            from_origin(100.0, 500.0, 20.0, 20.0),
            "pixel_center",
        )
        aligned = prepare_defsour_epoch(
            values,
            values,
            valid,
            source,
            factor=1,
            aggregation="mean",
            destination_profile=destination,
        )
        self.assertEqual(aligned.deformation.shape, (1, 1))
        self.assertEqual(aligned.profile, destination)
        with self.assertRaisesRegex(ValueError, "shape"):
            prepare_defsour_epoch(
                values,
                values,
                np.ones((1, 2), dtype=bool),
                source,
                factor=1,
                aggregation="mean",
            )


if __name__ == "__main__":
    unittest.main()
