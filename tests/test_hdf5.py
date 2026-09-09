"""Synthetic regression tests for read-only HDF5 detection and validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py

from insar_data_adapter import detect_hdf5_format, inspect_hdf5


class HDF5InspectionTests(unittest.TestCase):
    """Exercise supported signatures without allocating large arrays."""

    def setUp(self) -> None:
        """Create one isolated directory for synthetic HDF5 products."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_inspects_mintpy_without_reading_cube(self) -> None:
        """Recognize MintPy datasets and return their shape and metadata."""
        source = self.root / "mintpy.h5"
        with h5py.File(source, "w") as handle:
            handle.create_dataset("timeseries", shape=(2, 3, 4), dtype="float32")
            handle.create_dataset("date", data=[b"20200101", b"20200113"])
            handle.attrs["UNIT"] = "m"
            handle.attrs["EPSG"] = "32605"
            handle.attrs["REF_DATE"] = "20200101"
        self.assertEqual(detect_hdf5_format(source), "mintpy")
        summary = inspect_hdf5(source)
        self.assertEqual(summary.deformation_shape, (2, 3, 4))
        self.assertEqual(summary.dates, ("20200101", "20200113"))
        self.assertEqual(summary.deformation_unit, "m")
        self.assertEqual(summary.crs, "EPSG:32605")

    def test_inspects_canonical_grid_signature(self) -> None:
        """Recognize the documented canonical grid schema and nested datasets."""
        source = self.root / "canonical.h5"
        with h5py.File(source, "w") as handle:
            handle.attrs["insar_schema"] = "insar_grid_timeseries/1.0"
            handle.attrs["deformation_unit"] = "mm"
            handle.attrs["crs"] = "EPSG:4326"
            handle.create_dataset("data/displacement", shape=(2, 3, 4), dtype="float32")
            handle.create_dataset(
                "time/date_yyyymmdd", data=[b"20200101", b"20200113"]
            )
        self.assertEqual(detect_hdf5_format(source), "standard")
        summary = inspect_hdf5(source, expected_format="standard")
        self.assertEqual(summary.schema, "insar_grid_timeseries/1.0")
        self.assertEqual(summary.layout, "grid")

    def test_inspects_licsbas_signature(self) -> None:
        """Recognize LiCSBAS and apply its documented millimetre unit."""
        source = self.root / "licsbas.h5"
        with h5py.File(source, "w") as handle:
            handle.create_dataset("cum", shape=(2, 3, 4), dtype="float32")
            handle.create_dataset("imdates", data=[20200101, 20200113])
            handle.create_dataset("hgt", shape=(3, 4), dtype="float32")
            handle.create_dataset("mask", shape=(3, 4), dtype="uint8")
        summary = inspect_hdf5(source, expected_format="licsbas")
        self.assertEqual(summary.deformation_unit, "mm")
        self.assertEqual(summary.crs, "EPSG:4326")

    def test_rejects_dimension_mismatch_and_wrong_expected_format(self) -> None:
        """Fail early for inconsistent time dimensions and format expectations."""
        source = self.root / "bad.h5"
        with h5py.File(source, "w") as handle:
            handle.create_dataset("timeseries", shape=(2, 3, 4), dtype="float32")
            handle.create_dataset("date", data=[b"20200101"])
            handle.attrs["UNIT"] = "m"
        with self.assertRaisesRegex(ValueError, "dimensions are inconsistent"):
            inspect_hdf5(source)
        with self.assertRaisesRegex(ValueError, "expected licsbas"):
            inspect_hdf5(source, expected_format="licsbas")


if __name__ == "__main__":
    unittest.main()
