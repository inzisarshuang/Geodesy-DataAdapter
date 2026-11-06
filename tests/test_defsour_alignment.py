from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

from insar_data_adapter.workflows.defsour.alignment import (
    DefsourAlignmentTemplate,
    load_alignment_template,
    save_alignment_template,
)
from insar_data_adapter.workflows.defsour.grid import GridProfile, coordinate_arrays


class DefsourAlignmentTests(unittest.TestCase):
    def template(self) -> DefsourAlignmentTemplate:
        profile = GridProfile(
            2,
            3,
            "EPSG:32647",
            from_origin(100.0, 500.0, 20.0, 20.0),
            "pixel_center",
        )
        x, y = coordinate_arrays(profile)
        return DefsourAlignmentTemplate(profile, 2, x, y)

    def test_safe_npz_round_trip_and_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "template.npz"
            expected = self.template()
            save_alignment_template(path, expected)
            actual = load_alignment_template(path)
            self.assertEqual(actual.profile, expected.profile)
            self.assertEqual(actual.factor, 2)
            np.testing.assert_array_equal(actual.x, expected.x)
            np.testing.assert_array_equal(actual.y, expected.y)
            actual.validate(expected.profile, factor=2, x=expected.x, y=expected.y)

    def test_rejects_profile_factor_and_coordinate_order_conflicts(self) -> None:
        template = self.template()
        conflicts = (
            (replace(template.profile, width=4), 2, template.x, template.y, "profile"),
            (replace(template.profile, crs="EPSG:4326"), 2, template.x, template.y, "profile"),
            (
                replace(template.profile, transform=from_origin(101.0, 500.0, 20.0, 20.0)),
                2,
                template.x,
                template.y,
                "profile",
            ),
            (template.profile, 3, template.x, template.y, "factor"),
            (template.profile, 2, template.x[:, ::-1], template.y[:, ::-1], "coordinate"),
        )
        for profile, factor, x, y, message in conflicts:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                template.validate(profile, factor=factor, x=x, y=y)

    def test_rejects_nonfinite_shape_missing_and_pickle_object_arrays(self) -> None:
        template = self.template()
        with self.assertRaisesRegex(ValueError, "coordinate.*profile"):
            DefsourAlignmentTemplate(
                template.profile,
                template.factor,
                template.x[:, ::-1],
                template.y[:, ::-1],
            )
        with self.assertRaisesRegex(ValueError, "shape"):
            DefsourAlignmentTemplate(template.profile, 2, template.x[:, :2], template.y)
        bad_x = template.x.copy()
        bad_x[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            DefsourAlignmentTemplate(template.profile, 2, bad_x, template.y)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.npz"
            np.savez(missing, x=template.x, y=template.y)
            with self.assertRaisesRegex(ValueError, "fields"):
                load_alignment_template(missing)
            objects = root / "objects.npz"
            np.savez(
                objects,
                metadata=np.array([{"unsafe": True}], dtype=object),
                x=template.x,
                y=template.y,
            )
            with self.assertRaisesRegex(ValueError, "safe numeric"):
                load_alignment_template(objects)


if __name__ == "__main__":
    unittest.main()
