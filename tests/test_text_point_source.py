"""Focused tests for bounded headered point-value table ingestion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from insar_data_adapter import HeaderedPointTableSource, PointMetadata


class HeaderedPointTableSourceTests(unittest.TestCase):
    """Verify named columns, bounded blocks, metadata, and coordinate conversion."""

    def setUp(self) -> None:
        """Create an isolated directory and complete velocity metadata."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.metadata = PointMetadata(
            source_format="headered_text_points",
            deformation_unit="cm/yr",
            deformation_quantity="velocity",
            los_positive="toward_satellite",
            crs="EPSG:32631",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="velocity interval declared by source manifest",
            spatial_reference="none",
            source_provenance="synthetic headered point unit test",
            height_unit="not_applicable",
        )

    def test_reads_named_columns_in_bounded_transformed_blocks(self) -> None:
        """Use header roles rather than positions and preserve value NaN and zero."""
        path = self.root / "points.txt"
        path.write_text(
            "# documented point table\n"
            "id lon velocity lat quality\n"
            "1 166021.443 4.5 0.0 0.9\n"
            "2 277404.560 0.0 110597.973 0.8\n"
            "3 388736.188 nan 221094.867 0.7\n",
            encoding="utf-8",
        )
        with HeaderedPointTableSource(
            path,
            self.metadata,
            chunk_points=2,
            value_column="velocity",
        ) as source:
            self.assertEqual(source.headers, ("id", "lon", "velocity", "lat", "quality"))
            blocks = list(source.iter_blocks(target_crs="EPSG:4326"))

        self.assertEqual([block.size for block in blocks], [2, 1])
        self.assertEqual([block.point_start for block in blocks], [0, 2])
        self.assertEqual(blocks[0].value_name, "velocity")
        self.assertEqual(blocks[0].crs, "EPSG:4326")
        np.testing.assert_allclose(blocks[0].x, [0.0, 0.999697], atol=1e-5)
        np.testing.assert_allclose(blocks[0].y, [0.0, 1.0], atol=1e-5)
        np.testing.assert_allclose(blocks[0].value, [4.5, 0.0])
        self.assertTrue(np.isnan(blocks[1].value[0]))

    def test_defaults_to_third_header_and_defers_later_row_validation(self) -> None:
        """Match the legacy third-column contract without scanning past a full block."""
        path = self.root / "legacy.txt"
        path.write_text(
            "lon lat deformation_cm_per_year extra\n"
            "1 2 3 9\n"
            "4 5 6 8\n"
            "invalid later row\n",
            encoding="utf-8",
        )
        geographic = PointMetadata(**{**self.metadata.__dict__, "crs": "EPSG:4326"})
        with HeaderedPointTableSource(
            path, geographic, chunk_points=2
        ) as source:
            blocks = source.iter_blocks()
            first = next(blocks)
            self.assertEqual(first.value_name, "deformation_cm_per_year")
            np.testing.assert_array_equal(first.value, [3.0, 6.0])
            with self.assertRaisesRegex(ValueError, "line 4"):
                next(blocks)

    def test_rejects_invalid_headers_rows_and_empty_tables(self) -> None:
        """Reject ambiguous headers, missing roles, invalid coordinates, and no data."""
        cases = (
            ("lon lat lon\n1 2 3\n", "duplicate column"),
            ("x lat value\n1 2 3\n", "missing required column: lon"),
            ("lon lat value\nnan 2 3\n", "non-finite coordinate"),
            ("lon lat value\n", "contains no data rows"),
        )
        geographic = PointMetadata(**{**self.metadata.__dict__, "crs": "EPSG:4326"})
        for index, (contents, message) in enumerate(cases):
            with self.subTest(message=message):
                path = self.root / f"invalid_{index}.txt"
                path.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    with HeaderedPointTableSource(path, geographic) as source:
                        list(source.iter_blocks())

    def test_requires_valid_metadata_and_active_scope(self) -> None:
        """Validate science metadata and forbid reads outside a managed scope."""
        path = self.root / "scope.txt"
        path.write_text("lon lat value\n1 2 3\n", encoding="utf-8")
        invalid = PointMetadata(**{**self.metadata.__dict__, "crs": "not-a-crs"})
        with self.assertRaisesRegex(ValueError, "metadata CRS"):
            with HeaderedPointTableSource(path, invalid):
                pass

        source = HeaderedPointTableSource(path, self.metadata)
        with self.assertRaisesRegex(RuntimeError, "not active"):
            next(source.iter_blocks())


if __name__ == "__main__":
    unittest.main()
