"""Tests for explicit phase/radian and LOS-displacement conversions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from insar_data_adapter import (
    GeoTiffValueMetadata,
    convert_los_displacement_binary_raster,
    convert_los_displacement_geotiff_to_phase,
    convert_phase_binary_raster,
    convert_phase_geotiff_to_los_displacement,
    los_displacement_to_phase,
    phase_to_los_displacement,
)


class PhaseConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def _metadata(
        self, input_unit: str, output_unit: str
    ) -> GeoTiffValueMetadata:
        return GeoTiffValueMetadata(
            input_unit=input_unit,
            output_unit=output_unit,
            value_quantity="cumulative_los_displacement",
            los_positive="toward_satellite",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="source interferogram",
            spatial_reference="source raster grid",
            source_provenance="synthetic phase conversion test",
        )

    def test_array_conversion_uses_explicit_los_sign_and_round_trips(self) -> None:
        phase = np.array([0.0, np.pi, 2.0 * np.pi, np.nan])
        displacement = phase_to_los_displacement(phase, 0.056, "mm")
        np.testing.assert_allclose(
            displacement[:3], [0.0, -14.0, -28.0], rtol=0.0, atol=1e-12
        )
        self.assertTrue(np.isnan(displacement[3]))
        restored = los_displacement_to_phase(displacement, 0.056, "mm")
        np.testing.assert_allclose(restored[:3], phase[:3], rtol=0.0, atol=1e-12)
        self.assertTrue(np.isnan(restored[3]))

    def test_array_conversion_rejects_invalid_wavelength_and_units(self) -> None:
        for wavelength in (0.0, -0.056, np.inf, np.nan):
            with self.subTest(wavelength=wavelength):
                with self.assertRaisesRegex(ValueError, "wavelength_m"):
                    phase_to_los_displacement(1.0, wavelength)
        with self.assertRaisesRegex(ValueError, "unit"):
            phase_to_los_displacement(1.0, 0.056, "degrees")

    def test_big_endian_float_raster_converts_in_blocks_and_round_trips(self) -> None:
        source = self.root / "phase.unw"
        displacement_path = self.root / "displacement.mm"
        restored_path = self.root / "phase.restored.unw"
        source_values = np.array(
            [[0.0, np.pi, 2.0 * np.pi], [-np.pi, np.nan, 0.5]],
            dtype=">f4",
        )
        source_values.tofile(source)

        convert_phase_binary_raster(
            source,
            displacement_path,
            source_values.shape,
            0.056,
            output_unit="mm",
            byte_order="big",
            block_rows=1,
        )
        displacement = np.fromfile(displacement_path, dtype=">f4").reshape(2, 3)
        np.testing.assert_allclose(
            displacement[0], [0.0, -14.0, -28.0], rtol=1e-6, atol=1e-6
        )
        self.assertTrue(np.isnan(displacement[1, 1]))

        convert_los_displacement_binary_raster(
            displacement_path,
            restored_path,
            source_values.shape,
            0.056,
            input_unit="mm",
            byte_order="big",
            block_rows=2,
        )
        restored = np.fromfile(restored_path, dtype=">f4").reshape(2, 3)
        np.testing.assert_allclose(
            restored, source_values, rtol=1e-6, atol=1e-6, equal_nan=True
        )
        self.assertEqual(restored_path.stat().st_size, source.stat().st_size)

    def test_little_endian_float_raster_conversion(self) -> None:
        source = self.root / "phase-little.unw"
        output = self.root / "displacement-little.mm"
        np.array([[2.0 * np.pi]], dtype="<f4").tofile(source)
        convert_phase_binary_raster(
            source,
            output,
            (1, 1),
            0.056,
            byte_order="little",
        )
        result = np.fromfile(output, dtype="<f4")
        np.testing.assert_allclose(result, [-28.0], rtol=1e-6, atol=1e-6)

    def test_binary_conversion_rejects_bad_size_and_preserves_existing_output(self) -> None:
        source = self.root / "source.unw"
        output = self.root / "existing.mm"
        np.ones(3, dtype=">f4").tofile(source)
        output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "input raster size mismatch"):
            convert_phase_binary_raster(
                source,
                output,
                (2, 2),
                0.056,
                byte_order="big",
            )
        self.assertEqual(output.read_bytes(), b"keep")
        self.assertEqual(list(self.root.glob(".existing.mm.*.tmp")), [])

    def test_binary_conversion_replaces_existing_output_by_default(self) -> None:
        source = self.root / "phase.unw"
        output = self.root / "existing.mm"
        np.ones(2, dtype="<f4").tofile(source)
        output.write_bytes(b"keep")
        convert_phase_binary_raster(
            source,
            output,
            (1, 2),
            0.056,
            byte_order="little",
        )
        self.assertNotEqual(output.read_bytes(), b"keep")
        np.testing.assert_allclose(
            np.fromfile(output, dtype="<f4"),
            [-0.056 * 1000.0 / (4.0 * np.pi)] * 2,
        )

    def _write_geotiff(self, path: Path, values: np.ndarray) -> None:
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=3,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(102.0, 36.0, 0.01, 0.01),
            nodata=-9999.0,
        ) as dataset:
            dataset.write(values.astype(np.float32), 1)

    def test_geotiff_conversion_preserves_georeferencing_and_nodata(self) -> None:
        phase_path = self.root / "phase.tif"
        displacement_path = self.root / "displacement.tif"
        restored_path = self.root / "phase.restored.tif"
        source_values = np.array(
            [[0.0, np.pi, 2.0 * np.pi], [-np.pi, -9999.0, 0.5]],
            dtype=np.float32,
        )
        self._write_geotiff(phase_path, source_values)

        convert_phase_geotiff_to_los_displacement(
            phase_path,
            displacement_path,
            0.056,
            self._metadata("rad", "mm"),
        )
        with rasterio.open(phase_path) as source, rasterio.open(
            displacement_path
        ) as converted:
            self.assertEqual(converted.crs, source.crs)
            self.assertEqual(converted.transform, source.transform)
            self.assertEqual((converted.width, converted.height), (3, 2))
            self.assertTrue(np.isnan(converted.read(1)[1, 1]))
            self.assertEqual(converted.tags()["input_unit"], "rad")
            self.assertEqual(converted.tags()["output_unit"], "mm")
            np.testing.assert_allclose(
                converted.read(1)[0], [0.0, -14.0, -28.0], atol=1e-5
            )

        convert_los_displacement_geotiff_to_phase(
            displacement_path,
            restored_path,
            0.056,
            self._metadata("mm", "rad"),
        )
        with rasterio.open(restored_path) as restored:
            np.testing.assert_allclose(
                restored.read(1),
                np.where(source_values == -9999.0, np.nan, source_values),
                rtol=1e-6,
                atol=1e-5,
                equal_nan=True,
            )

    def test_geotiff_conversion_requires_metadata_units_to_match_direction(self) -> None:
        source = self.root / "source.tif"
        output = self.root / "output.tif"
        self._write_geotiff(source, np.ones((2, 3), dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "input_unit"):
            convert_phase_geotiff_to_los_displacement(
                source,
                output,
                0.056,
                self._metadata("mm", "mm"),
            )
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
