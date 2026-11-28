"""Regression tests for GAMMA memmap grid conversion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from insar_data_adapter import CanonicalGridReader, GammaGeoGridSource
from insar_data_adapter.config import load_gamma_conversion_config
from insar_data_adapter.converters import convert_gamma_grid


class GammaConversionTests(unittest.TestCase):
    """Verify binary representation, manifests, nodata, references, and atomic output."""

    def setUp(self) -> None:
        """Create two tiny GAMMA epochs with explicit mixed binary representations."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "canonical.h5"
        self.values = np.arange(40, dtype=np.float32).reshape(2, 4, 5)
        self.values[0, 0, 0] = -9999.0
        for epoch in range(2):
            self.values[epoch].astype(">f4").tofile(self.root / f"D{epoch + 1}.bin")
        self.height = np.arange(20, dtype=np.float32).reshape(4, 5) + 1000.0
        self.height[3, 4] = -32768.0
        self.height.astype("<f4").tofile(self.root / "dem.bin")
        self.mask = np.ones((4, 5), dtype=np.uint8)
        self.mask[1, 3] = 0
        self.mask.tofile(self.root / "mask.bin")
        (self.root / "stack.tab").write_text(
            "D1.bin\nD2.bin\n", encoding="utf-8"
        )
        (self.root / "dates.txt").write_text(
            "20200101\n20200113\n", encoding="utf-8"
        )
        (self.root / "grid.par").write_text(
            "Gamma DIFF&GEO DEM/MAP parameter file\n"
            "DEM_projection: EQA\n"
            "EPSG: 4326\n"
            "width: 5\n"
            "nlines: 4\n"
            "corner_lon: -156.0 decimal degrees\n"
            "corner_lat: 20.0 decimal degrees\n"
            "post_lon: 0.001 decimal degrees\n"
            "post_lat: -0.001 decimal degrees\n",
            encoding="utf-8",
        )

    def _write_config(self, extra: str = "") -> Path:
        """Write a complete GAMMA cfg using paths relative to the cfg directory."""
        config = self.root / "gamma.cfg"
        config.write_text(
            "tab_file = stack.tab\n"
            "dates_file = dates.txt\n"
            "parameter_file = grid.par\n"
            "height_file = dem.bin\n"
            "mask_file = mask.bin\n"
            "output_file = canonical.h5\n"
            "deformation_dtype = float32\n"
            "deformation_byte_order = big\n"
            "height_dtype = float32\n"
            "height_byte_order = little\n"
            "mask_dtype = uint8\n"
            "mask_byte_order = little\n"
            "deformation_unit = m\n"
            "height_unit = m\n"
            "crs = EPSG:4326\n"
            "los_positive = toward_satellite\n"
            "nodata_policy = zero displacement is valid\n"
            "deformation_nodata = -9999\n"
            "height_nodata = -32768\n"
            "spatial_reference = upstream_reference_area=documented_elsewhere\n"
            "temporal_reference = preserve\n"
            "source_temporal_reference = gamma_native_solution\n"
            "grid_registration = pixel\n"
            "chunk_rows = 2\n"
            "compression = gzip\n"
            "compression_level = 1\n"
            f"{extra}",
            encoding="utf-8",
        )
        return config

    def test_source_reads_explicit_endian_row_slices(self) -> None:
        """Read only selected rows and construct pixel-centre coordinate axes."""
        config = load_gamma_conversion_config(self._write_config())
        with GammaGeoGridSource(
            config["tab_file"],
            config["dates_file"],
            config["parameter_file"],
            config["height_file"],
            config["mask_file"],
            deformation_dtype=str(config["deformation_dtype"]),
            deformation_byte_order=str(config["deformation_byte_order"]),
            height_dtype=str(config["height_dtype"]),
            height_byte_order=str(config["height_byte_order"]),
            mask_dtype=str(config["mask_dtype"]),
            mask_byte_order=str(config["mask_byte_order"]),
        ) as source:
            np.testing.assert_array_equal(
                source.read_deformation_rows(1, 1, 3), self.values[1, 1:3]
            )
            np.testing.assert_array_equal(source.read_height_rows(2, 4), self.height[2:4])
            np.testing.assert_allclose(source.x, [-156, -155.999, -155.998, -155.997, -155.996])
            np.testing.assert_allclose(source.y, [20, 19.999, 19.998, 19.997])
            self.assertEqual(source.declared_crs, "EPSG:4326")

    def test_conversion_applies_only_explicit_nodata_actions(self) -> None:
        """Convert sentinels to NaN, preserve zero, and invalidate explicit DEM nodata."""
        convert_gamma_grid(load_gamma_conversion_config(self._write_config()))
        with CanonicalGridReader(self.output) as reader:
            expected = self.values.copy()
            expected[expected == -9999] = np.nan
            for epoch in range(2):
                np.testing.assert_allclose(
                    reader.read_epoch(epoch), expected[epoch], equal_nan=True
                )
            height = reader.read_geometry_rows("height")
            self.assertTrue(np.isnan(height[3, 4]))
            valid = reader.read_geometry_rows("valid_mask")
            self.assertFalse(valid[1, 3])
            self.assertFalse(valid[3, 4])
        with h5py.File(self.output, "r") as handle:
            self.assertEqual(handle.attrs["source_format"], "gamma")
            self.assertEqual(handle.attrs["deformation_unit"], "m")
            self.assertEqual(handle.attrs["temporal_reference"], "gamma_native_solution")
            self.assertIn("deformation -9999 converted to NaN", handle.attrs["nodata_policy"])
            self.assertIn("zero displacement is valid", handle.attrs["nodata_policy"])
            self.assertEqual(
                handle.attrs["spatial_reference"],
                "upstream_reference_area=documented_elsewhere",
            )
            self.assertIn("deformation_binary=>f4", handle.attrs["source_provenance"])

    def test_conversion_records_metadata_without_free_text_settings(self) -> None:
        """Generate nodata metadata and record an unknown spatial reference."""
        self.values[0, 0, 1] = 0
        self.values[0].astype(">f4").tofile(self.root / "D1.bin")
        path = self._write_config()
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(
            "\n".join(
                line for line in lines
                if not line.startswith(("nodata_policy =", "spatial_reference ="))
            ) + "\n",
            encoding="utf-8",
        )

        convert_gamma_grid(load_gamma_conversion_config(path))

        with h5py.File(self.output, "r") as handle:
            self.assertEqual(handle.attrs["spatial_reference"], "unknown")
            policy = handle.attrs["nodata_policy"]
            self.assertIn("mask: finite and >0 is valid", policy)
            self.assertIn("deformation -9999 converted to NaN", policy)
            self.assertIn("zero is not a deformation nodata sentinel", policy)
            self.assertEqual(handle["data/displacement"][0, 0, 1], 0)

    def test_date_reference_subtracts_selected_epoch(self) -> None:
        """Apply a configured temporal reference while keeping memory bounded by rows."""
        config_path = self._write_config()
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            .replace("temporal_reference = preserve", "temporal_reference = date")
            .replace(
                "source_temporal_reference = gamma_native_solution",
                "temporal_reference_date = 20200113",
            ),
            encoding="utf-8",
        )
        convert_gamma_grid(load_gamma_conversion_config(config_path))
        expected_first = self.values[0] - self.values[1]
        expected_first[0, 0] = np.nan
        with CanonicalGridReader(self.output) as reader:
            np.testing.assert_allclose(
                reader.read_epoch(0), expected_first, equal_nan=True
            )
            np.testing.assert_array_equal(reader.read_epoch(1), np.zeros((4, 5)))

    def test_size_mismatch_preserves_existing_output(self) -> None:
        """Validate every binary size before opening an overwrite destination."""
        (self.root / "D2.bin").write_bytes(b"short")
        self.output.write_bytes(b"old product")
        config = load_gamma_conversion_config(self._write_config("overwrite = true\n"))
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            convert_gamma_grid(config)
        self.assertEqual(self.output.read_bytes(), b"old product")
        self.assertEqual(list(self.root.glob(".canonical.h5.*.tmp")), [])

    def test_parameter_crs_conflict_is_rejected(self) -> None:
        """Prevent longitude/latitude axes from receiving a contradictory par EPSG."""
        parameter = self.root / "grid.par"
        parameter.write_text(
            parameter.read_text(encoding="utf-8").replace("EPSG: 4326", "EPSG: 32605"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "conflicts with the GAMMA parameter EPSG"):
            convert_gamma_grid(load_gamma_conversion_config(self._write_config()))
        self.assertFalse(self.output.exists())

    def test_cfg_requires_binary_and_reference_conventions(self) -> None:
        """Reject missing representations, false registration, and ambiguous references."""
        incomplete = self.root / "incomplete.cfg"
        incomplete.write_text(
            "tab_file = stack.tab\noutput_file = canonical.h5\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "deformation_byte_order"):
            load_gamma_conversion_config(incomplete)
        registration = self._write_config()
        registration.write_text(
            registration.read_text(encoding="utf-8").replace(
                "grid_registration = pixel", "grid_registration = gridline"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "grid_registration = pixel"):
            load_gamma_conversion_config(registration)


if __name__ == "__main__":
    unittest.main()
