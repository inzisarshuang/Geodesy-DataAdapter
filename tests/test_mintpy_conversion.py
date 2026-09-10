"""Regression tests for bounded-memory MintPy grid conversion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from insar_data_adapter import CanonicalGridReader, MintPyGridSource
from insar_data_adapter.config import load_mintpy_conversion_config
from insar_data_adapter.converters import convert_mintpy_grid


class MintPyConversionTests(unittest.TestCase):
    """Verify value preservation, metadata, cfg strictness, and safe failures."""

    def setUp(self) -> None:
        """Create one small geocoded MintPy product with separate geometry and mask."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.timeseries = self.root / "timeseries.h5"
        self.geometry = self.root / "geometry.h5"
        self.mask = self.root / "mask.h5"
        self.output = self.root / "canonical.h5"
        self.values = np.arange(40, dtype=np.float32).reshape(2, 4, 5)
        self.values[0, 0, 0] = 0.0
        with h5py.File(self.timeseries, "w") as handle:
            dataset = handle.create_dataset("timeseries", data=self.values)
            dataset.attrs["UNIT"] = "m"
            handle.create_dataset("date", data=np.asarray([b"20200101", b"20200113"]))
            handle.attrs.update(
                {
                    "LENGTH": 4,
                    "WIDTH": 5,
                    "X_FIRST": 500000.0,
                    "X_STEP": 20.0,
                    "Y_FIRST": 2200000.0,
                    "Y_STEP": -20.0,
                    "EPSG": 32605,
                    "REF_DATE": "20200101",
                    "REF_X": 2,
                    "REF_Y": 1,
                    "NO_DATA_VALUE": 0.0,
                }
            )
        self.height = np.arange(20, dtype=np.float32).reshape(4, 5) + 1000
        self.height[3, 4] = np.nan
        with h5py.File(self.geometry, "w") as handle:
            handle.create_dataset("height", data=self.height)
        self.valid = np.ones((4, 5), dtype=np.uint8)
        self.valid[1, 3] = 0
        self.valid[3, 4] = 0
        with h5py.File(self.mask, "w") as handle:
            handle.create_dataset("mask", data=self.valid)

    def _write_config(self, extra: str = "") -> Path:
        """Write a complete cfg using relative paths to exercise path resolution."""
        config = self.root / "mintpy.cfg"
        config.write_text(
            "timeseries_file = timeseries.h5\n"
            "geometry_file = geometry.h5\n"
            "mask_file = mask.h5\n"
            "output_file = canonical.h5\n"
            "los_positive = toward_satellite\n"
            "nodata_policy = external mask defines validity; source zero is preserved\n"
            "height_unit = m\n"
            "chunk_rows = 2\n"
            "compression = gzip\n"
            "compression_level = 1\n"
            f"{extra}",
            encoding="utf-8",
        )
        return config

    def test_source_reads_axes_and_requested_rows(self) -> None:
        """Treat X_FIRST/Y_FIRST as centers and read only the selected row slice."""
        with MintPyGridSource(self.timeseries) as source:
            np.testing.assert_allclose(source.x, [500000, 500020, 500040, 500060, 500080])
            np.testing.assert_allclose(source.y, [2200000, 2199980, 2199960, 2199940])
            np.testing.assert_array_equal(
                source.read_deformation_rows(1, 1, 3), self.values[1, 1:3, :]
            )
            self.assertEqual(source.deformation_unit, "m")
            self.assertEqual(source.crs, "EPSG:32605")

    def test_cfg_conversion_preserves_values_and_explicit_metadata(self) -> None:
        """Copy every epoch, DEM, and explicit static mask without changing values."""
        config = load_mintpy_conversion_config(self._write_config())
        convert_mintpy_grid(config)
        with CanonicalGridReader(self.output) as reader:
            for epoch in range(2):
                np.testing.assert_array_equal(reader.read_epoch(epoch), self.values[epoch])
            np.testing.assert_array_equal(
                reader.read_geometry_rows("valid_mask"),
                self.valid.astype(bool),
            )
        with h5py.File(self.output, "r") as handle:
            self.assertEqual(handle.attrs["source_format"], "mintpy")
            self.assertEqual(handle.attrs["deformation_unit"], "m")
            self.assertEqual(handle.attrs["los_positive"], "toward_satellite")
            self.assertEqual(handle.attrs["temporal_reference"], "mintpy_REF_DATE=20200101")
            self.assertEqual(
                handle.attrs["spatial_reference"], "mintpy_REF_Y=1,REF_X=2"
            )
            self.assertEqual(float(handle["data/displacement"][0, 0, 0]), 0.0)

    def test_missing_mask_and_unknown_cfg_key_fail_without_output(self) -> None:
        """Reject implicit validity and typos before publishing a destination."""
        incomplete = self.root / "missing-mask.cfg"
        incomplete.write_text(
            "timeseries_file = timeseries.h5\n"
            "geometry_file = geometry.h5\n"
            "output_file = canonical.h5\n"
            "los_positive = toward_satellite\n"
            "nodata_policy = explicit mask\n"
            "height_unit = m\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "mask_file"):
            load_mintpy_conversion_config(incomplete)
        with self.assertRaisesRegex(ValueError, "unknown cfg key"):
            load_mintpy_conversion_config(self._write_config("typo_option = true\n"))
        self.assertFalse(self.output.exists())

    def test_shape_failure_preserves_existing_output(self) -> None:
        """Validate all input shapes before opening the atomic output writer."""
        with h5py.File(self.mask, "w") as handle:
            handle.create_dataset("mask", data=np.ones((3, 5), dtype=np.uint8))
        self.output.write_bytes(b"old product")
        config = load_mintpy_conversion_config(self._write_config("overwrite = true\n"))
        with self.assertRaisesRegex(ValueError, "mask shape"):
            convert_mintpy_grid(config)
        self.assertEqual(self.output.read_bytes(), b"old product")
        self.assertEqual(list(self.root.glob(".canonical.h5.*.tmp")), [])

    def test_mask_cannot_mark_nonfinite_height_as_valid(self) -> None:
        """Reject a scientifically inconsistent mask instead of silently changing it."""
        with h5py.File(self.mask, "r+") as handle:
            handle["mask"][3, 4] = 1
        config = load_mintpy_conversion_config(self._write_config())
        with self.assertRaisesRegex(ValueError, "non-finite height"):
            convert_mintpy_grid(config)
        self.assertFalse(self.output.exists())

    def test_geometry_geocoding_mismatch_is_rejected(self) -> None:
        """Reject a same-size DEM that declares a different map grid."""
        with h5py.File(self.geometry, "r+") as handle:
            handle.attrs["X_FIRST"] = 499000.0
        config = load_mintpy_conversion_config(self._write_config())
        with self.assertRaisesRegex(ValueError, "X_FIRST"):
            convert_mintpy_grid(config)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
