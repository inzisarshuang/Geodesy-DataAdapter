"""Focused tests for bounded Defsour point-table ingestion and CRS conversion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from insar_data_adapter import DefsourMetadata, DefsourPointSource


class DefsourPointSourceTests(unittest.TestCase):
    """Verify explicit semantics, bounded iteration, columns, and coordinates."""

    def setUp(self) -> None:
        """Create one isolated directory and complete source metadata."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.metadata = DefsourMetadata(
            input_crs="EPSG:32605",
            deformation_unit="cm",
            deformation_quantity="cumulative_displacement",
            height_unit="m",
            los_positive="toward_satellite",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="20160512",
            spatial_reference="none",
            source_provenance="synthetic Defsour unit test",
        )

    def test_reads_bounded_blocks_and_transforms_coordinates(self) -> None:
        """Skip comments and blanks while preserving values and block identities."""
        source_path = self.root / "defsour.txt"
        source_path.write_text(
            "# X Y elevation deformation\n"
            "500000 2100000 12.5 -1.25\n"
            "\n"
            "500100 2100100 nan 0\n"
            "500200 2100200 15.0 nan\n",
            encoding="utf-8",
        )
        with DefsourPointSource(
            source_path, self.metadata, chunk_points=2
        ) as source:
            blocks = list(source.iter_blocks(target_crs="EPSG:4326"))

        self.assertEqual([block.size for block in blocks], [2, 1])
        self.assertEqual([block.point_start for block in blocks], [0, 2])
        self.assertEqual([block.point_stop for block in blocks], [2, 3])
        self.assertTrue(all(block.crs == "EPSG:4326" for block in blocks))
        np.testing.assert_allclose(blocks[0].x, [-153.0, -152.999050], atol=1e-6)
        np.testing.assert_allclose(blocks[0].y, [18.992522, 18.993426], atol=1e-6)
        np.testing.assert_allclose(blocks[0].deformation, [-1.25, 0.0])
        self.assertTrue(np.isnan(blocks[0].height[1]))
        self.assertTrue(np.isnan(blocks[1].deformation[0]))

    def test_first_block_does_not_scan_the_remaining_file(self) -> None:
        """Return a full first block before a malformed later line is inspected."""
        source_path = self.root / "lazy.txt"
        source_path.write_text(
            "1 2 3 4\n5 6 7 8\nthis later line is invalid\n",
            encoding="utf-8",
        )
        with DefsourPointSource(
            source_path, self.metadata, chunk_points=2
        ) as source:
            blocks = source.iter_blocks()
            first = next(blocks)
            self.assertEqual(first.point_stop, 2)
            self.assertEqual(first.crs, "EPSG:32605")
            with self.assertRaisesRegex(ValueError, "line 3"):
                next(blocks)

    def test_supports_explicit_nonstandard_column_assignments(self) -> None:
        """Read required roles from caller-declared zero-based columns."""
        source_path = self.root / "columns.txt"
        source_path.write_text("99 -2 30 20 10\n", encoding="utf-8")
        with DefsourPointSource(
            source_path,
            self.metadata,
            x_column=4,
            y_column=3,
            height_column=2,
            deformation_column=1,
        ) as source:
            block = next(source.iter_blocks())
        np.testing.assert_array_equal(block.x, [10.0])
        np.testing.assert_array_equal(block.y, [20.0])
        np.testing.assert_array_equal(block.height, [30.0])
        np.testing.assert_array_equal(block.deformation, [-2.0])

    def test_rejects_ambiguous_configuration_and_invalid_rows(self) -> None:
        """Reject duplicate roles, missing values, and non-finite coordinates."""
        valid = self.root / "valid.txt"
        valid.write_text("1 2 3 4\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            with DefsourPointSource(valid, self.metadata, y_column=0):
                pass

        missing = self.root / "missing.txt"
        missing.write_text("1 2 3\n", encoding="utf-8")
        with DefsourPointSource(missing, self.metadata) as source:
            with self.assertRaisesRegex(ValueError, "line 1 has 3 columns"):
                next(source.iter_blocks())

        nonfinite = self.root / "nonfinite.txt"
        nonfinite.write_text("nan 2 3 4\n", encoding="utf-8")
        with DefsourPointSource(nonfinite, self.metadata) as source:
            with self.assertRaisesRegex(ValueError, "non-finite coordinate"):
                next(source.iter_blocks())

    def test_metadata_and_active_scope_are_mandatory(self) -> None:
        """Reject missing semantics and iteration outside a managed source scope."""
        values = dict(self.metadata.__dict__)
        values["deformation_unit"] = " "
        with self.assertRaisesRegex(ValueError, "deformation_unit"):
            DefsourMetadata(**values)

        source_path = self.root / "scope.txt"
        source_path.write_text("1 2 3 4\n", encoding="utf-8")
        source = DefsourPointSource(source_path, self.metadata)
        with self.assertRaisesRegex(RuntimeError, "not active"):
            next(source.iter_blocks())

        empty_path = self.root / "empty.txt"
        empty_path.write_text("# X Y height deformation\n\n", encoding="utf-8")
        with DefsourPointSource(empty_path, self.metadata) as empty_source:
            with self.assertRaisesRegex(ValueError, "contains no data rows"):
                next(empty_source.iter_blocks())


if __name__ == "__main__":
    unittest.main()
