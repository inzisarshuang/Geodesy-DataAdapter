"""Regression tests for bounded-memory LiCSBAS grid conversion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from insar_data_adapter import CanonicalGridReader, LiCSBASGridSource
from insar_data_adapter.config import load_licsbas_conversion_config
from insar_data_adapter.converters import convert_licsbas_grid


class LiCSBASConversionTests(unittest.TestCase):
    """Verify native-grid preservation and explicit scientific metadata handling."""

    def setUp(self) -> None:
        """Create a small LiCSBAS-style file with embedded DEM, mask, and reference."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source_file = self.root / "licsbas.h5"
        self.output = self.root / "canonical.h5"
        self.values = np.arange(48, dtype=np.float32).reshape(2, 4, 6)
        self.values[0, 0, 0] = 0.0
        self.height = np.arange(24, dtype=np.float32).reshape(4, 6) + 500.0
        self.height[3, 5] = np.nan
        self.mask = np.ones((4, 6), dtype=np.float32)
        self.mask[1, 4] = 0.0
        self.mask[3, 5] = np.nan
        with h5py.File(self.source_file, "w") as handle:
            handle.create_dataset("cum", data=self.values, chunks=(1, 2, 3))
            handle.create_dataset("imdates", data=np.asarray([20200101, 20200113]))
            handle.create_dataset("hgt", data=self.height)
            handle.create_dataset("mask", data=self.mask)
            handle.create_dataset("corner_lon", data=-156.0)
            handle.create_dataset("corner_lat", data=20.0)
            handle.create_dataset("post_lon", data=0.001)
            handle.create_dataset("post_lat", data=-0.001)
            handle.create_dataset(
                "refarea", data="1:2/1:2", dtype=h5py.string_dtype("utf-8")
            )

    def _write_config(self, extra: str = "") -> Path:
        """Write a complete strict cfg using paths relative to the cfg directory."""
        config = self.root / "licsbas.cfg"
        config.write_text(
            "input_file = licsbas.h5\n"
            "output_file = canonical.h5\n"
            "deformation_unit = mm\n"
            "height_unit = m\n"
            "crs = 4326\n"
            "los_positive = toward_satellite\n"
            "nodata_policy = finite mask > 0 is valid; zero displacement is valid\n"
            "temporal_reference = preserve\n"
            "source_temporal_reference = licsbas_native_solution\n"
            "grid_registration = pixel\n"
            "chunk_rows = 2\n"
            "compression = gzip\n"
            "compression_level = 1\n"
            f"{extra}",
            encoding="utf-8",
        )
        return config

    def test_source_reads_pixel_centres_and_selected_rows(self) -> None:
        """Build native longitude/latitude axes and read only the requested HDF5 slice."""
        with LiCSBASGridSource(self.source_file) as source:
            np.testing.assert_allclose(
                source.x, [-156.0, -155.999, -155.998, -155.997, -155.996, -155.995]
            )
            np.testing.assert_allclose(source.y, [20.0, 19.999, 19.998, 19.997])
            np.testing.assert_array_equal(
                source.read_deformation_rows(1, 1, 3), self.values[1, 1:3, :]
            )
            self.assertEqual(source.spatial_reference, "licsbas_refarea=1:2/1:2")
            self.assertIsNone(source.declared_unit)

    def test_cfg_conversion_preserves_native_values_and_mask(self) -> None:
        """Copy native values and convert LiCSBAS NaN/positive mask semantics explicitly."""
        convert_licsbas_grid(load_licsbas_conversion_config(self._write_config()))
        with CanonicalGridReader(self.output) as reader:
            for epoch in range(2):
                np.testing.assert_array_equal(reader.read_epoch(epoch), self.values[epoch])
            expected_mask = np.isfinite(self.mask) & (self.mask > 0)
            np.testing.assert_array_equal(
                reader.read_geometry_rows("valid_mask"), expected_mask
            )
            np.testing.assert_allclose(
                reader.read_geometry_rows("height"), self.height, equal_nan=True
            )
        with h5py.File(self.output, "r") as handle:
            self.assertEqual(handle.attrs["source_format"], "licsbas")
            self.assertEqual(handle.attrs["deformation_unit"], "mm")
            self.assertEqual(handle.attrs["crs"], "EPSG:4326")
            self.assertIn(
                "LiCSBAS /mask: finite and >0 is valid",
                handle.attrs["nodata_policy"],
            )
            self.assertEqual(
                handle.attrs["temporal_reference"], "licsbas_native_solution"
            )
            self.assertEqual(handle.attrs["spatial_reference"], "licsbas_refarea=1:2/1:2")
            self.assertEqual(float(handle["data/displacement"][0, 0, 0]), 0.0)

    def test_missing_science_metadata_and_gridline_registration_are_rejected(self) -> None:
        """Require explicit units/references and prevent a false grid registration label."""
        incomplete = self.root / "incomplete.cfg"
        incomplete.write_text(
            "input_file = licsbas.h5\noutput_file = canonical.h5\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "deformation_unit"):
            load_licsbas_conversion_config(incomplete)
        registration_cfg = self._write_config()
        registration_cfg.write_text(
            registration_cfg.read_text(encoding="utf-8").replace(
                "grid_registration = pixel", "grid_registration = gridline"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "grid_registration = pixel"):
            load_licsbas_conversion_config(registration_cfg)
        self.assertFalse(self.output.exists())

    def test_declared_unit_conflict_preserves_existing_output(self) -> None:
        """Reject a cfg/source unit conflict before opening the atomic writer."""
        with h5py.File(self.source_file, "r+") as handle:
            handle["cum"].attrs["UNIT"] = "m"
        self.output.write_bytes(b"old product")
        config = load_licsbas_conversion_config(self._write_config("overwrite = true\n"))
        with self.assertRaisesRegex(ValueError, "deformation_unit conflicts"):
            convert_licsbas_grid(config)
        self.assertEqual(self.output.read_bytes(), b"old product")
        self.assertEqual(list(self.root.glob(".canonical.h5.*.tmp")), [])

    def test_invalid_crs_and_temporal_reference_date_are_rejected(self) -> None:
        """Prevent native longitude/latitude coordinates from receiving false metadata."""
        crs_cfg = self._write_config()
        crs_cfg.write_text(
            crs_cfg.read_text(encoding="utf-8").replace("crs = 4326", "crs = 32605"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "require crs = EPSG:4326"):
            convert_licsbas_grid(load_licsbas_conversion_config(crs_cfg))
        time_cfg = self._write_config()
        time_cfg.write_text(
            time_cfg.read_text(encoding="utf-8")
            .replace("temporal_reference = preserve", "temporal_reference = date")
            .replace(
                "source_temporal_reference = licsbas_native_solution",
                "temporal_reference_date = 20191231",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "not present in LiCSBAS imdates"):
            convert_licsbas_grid(load_licsbas_conversion_config(time_cfg))
        self.assertFalse(self.output.exists())

    def test_date_reference_is_applied_by_bounded_row_block(self) -> None:
        """Subtract one configured epoch and record the applied temporal transform."""
        config_path = self._write_config()
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            .replace("temporal_reference = preserve", "temporal_reference = date")
            .replace(
                "source_temporal_reference = licsbas_native_solution",
                "temporal_reference_date = 20200101",
            ),
            encoding="utf-8",
        )
        convert_licsbas_grid(load_licsbas_conversion_config(config_path))
        with CanonicalGridReader(self.output) as reader:
            np.testing.assert_array_equal(reader.read_epoch(0), np.zeros((4, 6)))
            np.testing.assert_array_equal(
                reader.read_epoch(1), self.values[1] - self.values[0]
            )
        with h5py.File(self.output, "r") as handle:
            self.assertEqual(handle.attrs["temporal_reference"], "20200101")
            self.assertIn(
                "temporal_transform=subtract_epoch=20200101",
                handle.attrs["source_provenance"],
            )

    def test_invalid_reference_area_is_rejected(self) -> None:
        """Reject an out-of-bounds LiCSBAS spatial reference before conversion."""
        with h5py.File(self.source_file, "r+") as handle:
            handle["refarea"][()] = "5:7/1:2"
        with self.assertRaisesRegex(ValueError, "refarea is outside"):
            with LiCSBASGridSource(self.source_file):
                pass


if __name__ == "__main__":
    unittest.main()
