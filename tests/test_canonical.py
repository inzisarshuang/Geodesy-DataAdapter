"""Regression tests for canonical grid HDF5 bounded-memory I/O."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from insar_data_adapter import CanonicalGridReader, CanonicalGridWriter, GridMetadata


class CanonicalGridIOTests(unittest.TestCase):
    """Verify block writes, slice reads, and atomic failure behavior."""

    def setUp(self) -> None:
        """Create common dimensions and explicit scientific metadata."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.metadata = GridMetadata(
            source_format="synthetic",
            deformation_unit="mm",
            deformation_quantity="cumulative_displacement",
            los_positive="toward_satellite",
            crs="EPSG:4326",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="20200101",
            spatial_reference="none",
            source_provenance="synthetic unit test",
        )
        self.dates = ["20200101", "20200113"]
        self.x = np.arange(4, dtype=float) + 10.0
        self.y = np.arange(3, dtype=float)[::-1] + 20.0

    def _complete_product(self, output: Path, overwrite: bool = False) -> None:
        """Write one small product in multiple row blocks."""
        with CanonicalGridWriter(
            output,
            self.dates,
            rows=3,
            columns=4,
            x=self.x,
            y=self.y,
            metadata=self.metadata,
            chunk_rows=2,
            overwrite=overwrite,
        ) as writer:
            writer.write_geometry_rows(0, np.ones((2, 4)), np.ones((2, 4), bool))
            writer.write_geometry_rows(2, np.ones((1, 4)) * 2, np.ones((1, 4), bool))
            for epoch in range(2):
                values = np.arange(12, dtype=np.float32).reshape(3, 4) + epoch * 100
                writer.write_deformation_rows(epoch, 0, values[:2])
                writer.write_deformation_rows(epoch, 2, values[2:])

    def test_writes_blocks_and_reads_selected_rows(self) -> None:
        """Publish a complete product and read only the requested epoch rows."""
        output = self.root / "complete.h5"
        self._complete_product(output)
        with h5py.File(output, "r") as handle:
            self.assertTrue(handle.attrs["write_complete"])
            self.assertEqual(handle["data/displacement"].chunks[0], 1)
        with CanonicalGridReader(output) as reader:
            selected = reader.read_epoch(1, row_start=1, row_stop=3)
            np.testing.assert_allclose(selected, np.arange(12).reshape(3, 4)[1:] + 100)
            np.testing.assert_allclose(
                reader.read_geometry_rows("height", 2, 3), np.full((1, 4), 2.0)
            )

    def test_incomplete_write_preserves_existing_target(self) -> None:
        """Remove an incomplete temporary file without replacing an old target."""
        output = self.root / "existing.h5"
        output.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "deformation.*missing"):
            with CanonicalGridWriter(
                output,
                self.dates,
                rows=3,
                columns=4,
                x=self.x,
                y=self.y,
                metadata=self.metadata,
                overwrite=True,
            ) as writer:
                writer.write_geometry_rows(0, np.ones((3, 4)), np.ones((3, 4), bool))
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".existing.h5.*.tmp")), [])

    def test_rejects_existing_output_and_overlapping_rows(self) -> None:
        """Require explicit overwrite and reject accidental duplicate block writes."""
        output = self.root / "product.h5"
        self._complete_product(output)
        with self.assertRaises(FileExistsError):
            with CanonicalGridWriter(
                output,
                self.dates,
                rows=3,
                columns=4,
                x=self.x,
                y=self.y,
                metadata=self.metadata,
            ):
                pass
        replacement = self.root / "replacement.h5"
        with self.assertRaisesRegex(ValueError, "overlap"):
            with CanonicalGridWriter(
                replacement,
                self.dates,
                rows=3,
                columns=4,
                x=self.x,
                y=self.y,
                metadata=self.metadata,
            ) as writer:
                writer.write_geometry_rows(0, np.ones((2, 4)), np.ones((2, 4), bool))
                writer.write_geometry_rows(1, np.ones((2, 4)), np.ones((2, 4), bool))
        self.assertFalse(replacement.exists())


if __name__ == "__main__":
    unittest.main()
