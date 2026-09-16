"""Focused tests for explicit, bounded, atomic Defsour text export."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from insar_data_adapter import (
    DefsourExportMetadata,
    DefsourPointBlock,
    infer_deformation_unit_label,
    write_defsour_blocks,
    write_defsour_grid,
)


class DefsourExportTests(unittest.TestCase):
    """Verify metadata, ordering, formatting, and interrupted publication."""

    def setUp(self) -> None:
        """Create complete explicit metadata shared by each test."""
        self.metadata = DefsourExportMetadata(
            crs="EPSG:32628",
            deformation_unit="cm",
            deformation_quantity="cumulative_displacement",
            height_unit="m",
            los_positive="toward_satellite",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="20240101",
            spatial_reference="radar row 2 column 3, zero-based",
            source_provenance="synthetic Defsour exporter test",
        )

    def test_deformation_unit_label_preserves_legacy_scale_mapping(self) -> None:
        """Map meter scale factors to the established human-readable labels."""
        cases = (
            (1.0, "m"),
            (100.0, "cm"),
            (1000.0, "mm"),
            (2.5, "scaled_from_m_by_2.5"),
        )
        for scale, expected in cases:
            with self.subTest(scale=scale):
                self.assertEqual(infer_deformation_unit_label(scale), expected)

    @staticmethod
    def block(
        start: int,
        values: list[list[float]],
        crs: str = "EPSG:32628",
    ) -> DefsourPointBlock:
        """Build one point block from rows ordered as X/Y/height/deformation."""
        matrix = np.asarray(values, dtype=np.float64)
        return DefsourPointBlock(
            point_start=start,
            x=matrix[:, 0],
            y=matrix[:, 1],
            height=matrix[:, 2],
            deformation=matrix[:, 3],
            crs=crs,
        )

    def test_writes_consecutive_blocks_with_exact_format_and_order(self) -> None:
        """Preserve block and point order without materializing a full point table."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "D20240101"
            blocks = (
                self.block(0, [[1, 2, 3, 4], [5, 6, np.nan, 8]]),
                self.block(2, [[9, 10, 11, 12]]),
            )
            result = write_defsour_blocks(
                iter(blocks),
                output,
                self.metadata,
                fmt="%.1f %.1f %.1f %.2f",
            )

            self.assertEqual(result.output_path, output.resolve())
            self.assertEqual(result.point_count, 3)
            self.assertIs(result.metadata, self.metadata)
            self.assertEqual(
                output.read_text(encoding="ascii"),
                "1.0 2.0 3.0 4.00\n"
                "5.0 6.0 nan 8.00\n"
                "9.0 10.0 11.0 12.00\n",
            )

    def test_failed_later_block_preserves_existing_output(self) -> None:
        """Discard the private temporary file when a later block is discontinuous."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "D20240101"
            output.write_text("existing\n", encoding="ascii")
            blocks = (
                self.block(0, [[1, 2, 3, 4]]),
                self.block(2, [[5, 6, 7, 8]]),
            )
            with self.assertRaisesRegex(ValueError, "expected 1"):
                write_defsour_blocks(
                    iter(blocks), output, self.metadata, overwrite=True
                )
            self.assertEqual(output.read_text(encoding="ascii"), "existing\n")
            self.assertEqual(list(output.parent.glob(f".{output.name}.*.tmp")), [])

    def test_rejects_existing_output_empty_input_and_invalid_blocks(self) -> None:
        """Reject ambiguous replacement, missing points, CRS conflicts, and infinity."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "D20240101"
            output.write_text("existing\n", encoding="ascii")
            with self.assertRaises(FileExistsError):
                write_defsour_blocks([], output, self.metadata)
            with self.assertRaisesRegex(ValueError, "at least one"):
                write_defsour_blocks([], output, self.metadata, overwrite=True)

            wrong_crs = self.block(0, [[1, 2, 3, 4]], crs="EPSG:4326")
            with self.assertRaisesRegex(ValueError, "does not match"):
                write_defsour_blocks(
                    [wrong_crs], output, self.metadata, overwrite=True
                )

            infinite = self.block(0, [[1, 2, np.inf, 4]])
            with self.assertRaisesRegex(ValueError, "must not contain infinity"):
                write_defsour_blocks(
                    [infinite], output, self.metadata, overwrite=True
                )

    def test_requires_complete_metadata_and_four_column_format(self) -> None:
        """Reject semantics or formatting that cannot define one Defsour product."""
        values = dict(self.metadata.__dict__)
        values["deformation_unit"] = " "
        with self.assertRaisesRegex(ValueError, "deformation_unit"):
            DefsourExportMetadata(**values)
        values["deformation_unit"] = "cm"
        values["crs"] = "not-a-crs"
        with self.assertRaisesRegex(ValueError, "export CRS"):
            DefsourExportMetadata(**values)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "exactly four columns"):
                write_defsour_blocks(
                    [self.block(0, [[1, 2, 3, 4]])],
                    Path(tmp) / "bad.txt",
                    self.metadata,
                    fmt="%.1f,%.1f,%.1f,%.1f",
                )

    def test_grid_export_matches_legacy_filter_and_row_order(self) -> None:
        """Filter grids by row blocks without changing legacy output ordering."""
        x = np.array([[1.0, 2.0], [3.0, 4.0]])
        y = x + 10.0
        height = np.array([[100.0, np.nan], [300.0, 400.0]])
        deformation = np.array([[0.1, 0.2], [np.nan, 0.4]])
        valid = np.array([[True, True], [True, False]])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "grid.txt"
            result = write_defsour_grid(
                x,
                y,
                height,
                deformation,
                valid,
                output,
                self.metadata,
                fmt="%.1f %.1f %.1f %.1f",
                block_rows=1,
            )
            self.assertEqual(result.point_count, 1)
            self.assertEqual(output.read_text(encoding="ascii"), "1.0 11.0 100.0 0.1\n")

    def test_grid_export_can_retain_nan_payloads(self) -> None:
        """Keep selected NaN payloads only when the caller explicitly requests it."""
        values = np.array([[1.0, 2.0]])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "grid.txt"
            result = write_defsour_grid(
                values,
                values,
                np.array([[np.nan, 3.0]]),
                np.array([[4.0, np.nan]]),
                np.ones((1, 2), dtype=bool),
                output,
                self.metadata,
                export_invalid_points=True,
            )
            self.assertEqual(result.point_count, 2)

    def test_grid_export_atomically_publishes_an_empty_epoch(self) -> None:
        """Preserve the legacy grid contract when an epoch has no selected cells."""
        values = np.ones((2, 2), dtype=float)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "empty.txt"
            output.write_text("old\n", encoding="ascii")
            result = write_defsour_grid(
                values,
                values,
                values,
                values,
                np.zeros((2, 2), dtype=bool),
                output,
                self.metadata,
                overwrite=True,
            )
            self.assertEqual(result.point_count, 0)
            self.assertEqual(output.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
