"""Regression tests for canonical sparse PS/DS point HDF5 I/O."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from insar_data_adapter import (
    CanonicalPointReader,
    CanonicalPointWriter,
    PointMetadata,
    PointQualitySpec,
    inspect_hdf5,
)


class CanonicalPointIOTests(unittest.TestCase):
    """Verify bounded point blocks, strict identities, metadata, and atomic output."""

    def setUp(self) -> None:
        """Create an isolated directory and fully explicit point metadata."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.dates = ["20200101", "20200113"]
        self.metadata = PointMetadata(
            source_format="synthetic_psds",
            deformation_unit="mm",
            deformation_quantity="cumulative_displacement",
            los_positive="toward_satellite",
            crs="EPSG:32628",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="20200101",
            spatial_reference="point_id=10",
            source_provenance="synthetic unit test",
            height_unit="m",
        )
        self.quality_specs = (
            PointQualitySpec(
                name="temporal_coherence",
                temporal=False,
                dtype="float32",
                unit="1",
                description="Temporal coherence per point",
                nodata_policy="NaN is nodata",
            ),
            PointQualitySpec(
                name="residual",
                temporal=True,
                dtype="float32",
                unit="mm",
                description="Per-epoch inversion residual",
                nodata_policy="NaN is nodata",
            ),
        )

    def _complete_product(self, output: Path, overwrite: bool = False) -> None:
        """Write five points and two epochs through unequal contiguous blocks."""
        point_id = np.array([10, 12, 15, 20, 21], dtype=np.int64)
        x = np.arange(5, dtype=float) + 500000.0
        y = np.arange(5, dtype=float) + 3100000.0
        height = np.arange(5, dtype=np.float32) + 1000.0
        row = np.array([0, 0, 1, 1, 2], dtype=np.int64)
        column = np.array([0, 2, 1, 4, 3], dtype=np.int64)
        velocity = np.linspace(-2.0, 2.0, 5, dtype=np.float32)
        coherence = np.linspace(0.5, 0.9, 5, dtype=np.float32)
        with CanonicalPointWriter(
            output,
            self.dates,
            point_count=5,
            metadata=self.metadata,
            chunk_points=3,
            include_row_column=True,
            include_velocity=True,
            velocity_unit="mm/yr",
            velocity_description="Linear LOS velocity per point",
            velocity_nodata_policy="NaN is nodata",
            quality_specs=self.quality_specs,
            overwrite=overwrite,
        ) as writer:
            for start, stop in ((0, 3), (3, 5)):
                writer.write_points(
                    start,
                    point_id[start:stop],
                    x[start:stop],
                    y[start:stop],
                    height[start:stop],
                    row=row[start:stop],
                    column=column[start:stop],
                    velocity=velocity[start:stop],
                    quality={"temporal_coherence": coherence[start:stop]},
                )
            for epoch in range(2):
                values = np.arange(5, dtype=np.float32) + epoch * 10
                residual = values / 10
                for start, stop in ((0, 2), (2, 5)):
                    writer.write_deformation_points(
                        epoch,
                        start,
                        values[start:stop],
                        quality={"residual": residual[start:stop]},
                    )

    def test_writes_and_reads_explicit_point_ranges(self) -> None:
        """Publish all optional roles and read only caller-selected point slices."""
        output = self.root / "points.h5"
        self._complete_product(output)
        summary = inspect_hdf5(output, expected_format="standard")
        self.assertEqual(summary.layout, "points")
        self.assertEqual(summary.deformation_shape, (2, 5))
        with h5py.File(output, "r") as handle:
            self.assertEqual(handle["data/displacement"].chunks[0], 1)
            self.assertEqual(handle["points/row"].attrs["index_origin"], "zero_based")
            self.assertEqual(handle["points/velocity"].attrs["unit"], "mm/yr")
            self.assertEqual(handle["quality/residual"].attrs["dimensions"], "time,point")
            self.assertEqual(handle["quality/temporal_coherence"].attrs["dimensions"], "point")
        with CanonicalPointReader(output) as reader:
            np.testing.assert_allclose(reader.read_epoch(1, 1, 4), [11, 12, 13])
            fields = reader.read_point_fields(("point_id", "row", "velocity"), 2, 5)
            np.testing.assert_array_equal(fields["point_id"], [15, 20, 21])
            np.testing.assert_array_equal(fields["row"], [1, 1, 2])
            np.testing.assert_allclose(
                reader.read_quality("temporal_coherence", 1, 3), [0.6, 0.7]
            )
            np.testing.assert_allclose(
                reader.read_quality("residual", 1, 4, epoch_index=1),
                [1.1, 1.2, 1.3],
            )

    def test_incomplete_write_preserves_existing_target(self) -> None:
        """Discard an incomplete temporary point product and retain the old target."""
        output = self.root / "existing.h5"
        output.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "deformation is incomplete"):
            with CanonicalPointWriter(
                output,
                self.dates,
                point_count=2,
                metadata=self.metadata,
                overwrite=True,
            ) as writer:
                writer.write_points(
                    0,
                    np.array([1, 2]),
                    np.array([0.0, 1.0]),
                    np.array([2.0, 3.0]),
                    np.array([4.0, 5.0]),
                )
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".existing.h5.*.tmp")), [])

    def test_rejects_invalid_point_identity_before_publish(self) -> None:
        """Reject negative, repeated, and uint64 identities that cannot fit int64."""
        cases = (
            np.array([-1, 2], dtype=np.int64),
            np.array([1, 1], dtype=np.int64),
            np.array([1, 2**63], dtype=np.uint64),
        )
        for index, point_ids in enumerate(cases):
            with self.subTest(point_ids=point_ids):
                output = self.root / f"invalid_{index}.h5"
                with self.assertRaisesRegex(ValueError, "point_id"):
                    with CanonicalPointWriter(
                        output,
                        self.dates,
                        point_count=2,
                        metadata=self.metadata,
                    ) as writer:
                        writer.write_points(
                            0,
                            point_ids,
                            np.array([0.0, 1.0]),
                            np.array([2.0, 3.0]),
                            np.array([4.0, 5.0]),
                        )
                self.assertFalse(output.exists())

        with self.assertRaisesRegex(ValueError, "include_velocity requires"):
            CanonicalPointWriter(
                self.root / "missing_velocity_metadata.h5",
                self.dates,
                point_count=2,
                metadata=self.metadata,
                include_velocity=True,
            )

    def test_reader_enforces_quality_role_and_flat_name(self) -> None:
        """Require epoch selectors only for temporal fields and reject nested names."""
        output = self.root / "quality.h5"
        self._complete_product(output)
        with CanonicalPointReader(output) as reader:
            with self.assertRaisesRegex(ValueError, "does not accept epoch_index"):
                reader.read_quality("temporal_coherence", 0, 2, epoch_index=0)
            with self.assertRaisesRegex(ValueError, "requires epoch_index"):
                reader.read_quality("residual", 0, 2)
            with self.assertRaisesRegex(ValueError, "invalid quality field name"):
                reader.read_quality("nested/name", 0, 2)

    def test_rejects_out_of_order_and_cross_block_point_ids(self) -> None:
        """Enforce sequential blocks and global identity ordering across boundaries."""
        output = self.root / "cross_block.h5"
        with self.assertRaisesRegex(ValueError, "globally strictly increasing"):
            with CanonicalPointWriter(
                output,
                self.dates,
                point_count=2,
                metadata=self.metadata,
            ) as writer:
                writer.write_points(0, np.array([10]), [0.0], [1.0], [2.0])
                writer.write_points(1, np.array([9]), [3.0], [4.0], [5.0])
        self.assertFalse(output.exists())

        with self.assertRaisesRegex(ValueError, "must be sequential"):
            with CanonicalPointWriter(
                self.root / "out_of_order.h5",
                self.dates,
                point_count=2,
                metadata=self.metadata,
            ) as writer:
                writer.write_points(1, np.array([10]), [0.0], [1.0], [2.0])

    def test_file_validation_detects_corrupted_identity_and_quality_contract(self) -> None:
        """Detect semantic corruption beyond dataset-presence and shape checks."""
        identity = self.root / "bad_identity.h5"
        self._complete_product(identity)
        with h5py.File(identity, "r+") as handle:
            handle["points/point_id"][3] = 15
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            inspect_hdf5(identity, expected_format="standard")

        quality = self.root / "bad_quality.h5"
        self._complete_product(quality)
        with h5py.File(quality, "r+") as handle:
            handle["quality/residual"].attrs["dimensions"] = "point,time"
        with self.assertRaisesRegex(ValueError, "dimensions must be time,point"):
            inspect_hdf5(quality, expected_format="standard")


if __name__ == "__main__":
    unittest.main()
