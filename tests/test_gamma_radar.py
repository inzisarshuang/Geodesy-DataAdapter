"""Tests for strict read-only GAMMA radar-coordinate source primitives."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from insar_data_adapter.sources.gamma_radar import (
    gamma_par_shape,
    radar_indices_from_lookup,
    read_binary_raster,
    read_complex_binary_raster,
    read_gamma_par_value,
)


class GammaParameterTests(unittest.TestCase):
    """Verify supported GAMMA parameter conventions."""

    def test_reads_radar_shape_and_numeric_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parameter_file = Path(temporary_directory) / "scene.mli.par"
            parameter_file.write_text(
                "range_samples: 3\nazimuth_lines: 2\n"
                "radar_frequency: 5.405e9 Hz\n",
                encoding="utf-8",
            )

            self.assertEqual(gamma_par_shape(parameter_file), (2, 3))
            self.assertEqual(
                read_gamma_par_value(parameter_file, "radar_frequency:"), 5.405e9
            )

    def test_reads_geographic_shape_and_rejects_missing_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            geographic = root / "scene.dem.par"
            geographic.write_text("width: 4\nnlines: 5\n", encoding="utf-8")
            invalid = root / "invalid.par"
            invalid.write_text("width: 4\n", encoding="utf-8")

            self.assertEqual(gamma_par_shape(geographic), (5, 4))
            with self.assertRaisesRegex(ValueError, "cannot infer raster shape"):
                gamma_par_shape(invalid)


class GammaBinaryRasterTests(unittest.TestCase):
    """Verify explicit byte order, size checking, and memory mapping."""

    def test_reads_real_big_endian_array_and_read_only_memmap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "real.bin"
            expected = np.arange(6, dtype=np.float32).reshape(2, 3)
            expected.astype(">f4").tofile(path)

            array = read_binary_raster(path, (2, 3), endian="big")
            mapped = read_binary_raster(path, (2, 3), endian="big", memmap=True)

            np.testing.assert_array_equal(array, expected)
            np.testing.assert_array_equal(mapped, expected)
            self.assertIsInstance(mapped, np.memmap)
            self.assertFalse(mapped.flags.writeable)

    def test_reads_complex_little_endian_memmap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "lookup.bin"
            expected = np.array(
                [[1.25 + 2.5j, -3.0 + 4.0j], [5.0 - 6.5j, 7.0 + 8.0j]],
                dtype=np.complex64,
            )
            expected.astype("<c8").tofile(path)

            mapped = read_complex_binary_raster(
                path, (2, 2), endian="little", memmap=True
            )

            np.testing.assert_array_equal(mapped, expected)
            self.assertIsInstance(mapped, np.memmap)
            self.assertFalse(mapped.flags.writeable)

    def test_rejects_invalid_endian_and_exact_size_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "short.bin"
            np.array([1.0], dtype=">f4").tofile(path)

            with self.assertRaisesRegex(ValueError, "endian"):
                read_binary_raster(path, (1, 1), endian="native")
            with self.assertRaisesRegex(ValueError, "read size mismatch"):
                read_binary_raster(path, (2, 2), endian="big")
            with self.assertRaisesRegex(ValueError, "read size mismatch"):
                read_complex_binary_raster(path, (1, 1), endian="big")


class GammaLookupTests(unittest.TestCase):
    """Verify geographic bounds map deterministically to radar indices."""

    def _parameter_file(self, root: Path) -> Path:
        path = root / "lookup.dem.par"
        path.write_text(
            "width: 3\nnlines: 3\n"
            "corner_lon: 10\ncorner_lat: 2\n"
            "post_lon: 1\npost_lat: -1\n",
            encoding="utf-8",
        )
        return path

    def _lookup(self) -> np.ndarray:
        rows, columns = np.indices((3, 3))
        return (columns + 1j * rows).astype(np.complex64)

    def test_rectangle_ellipse_mask_and_negative_latitude_spacing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parameter_file = self._parameter_file(Path(temporary_directory))
            lookup = self._lookup()

            rectangle = radar_indices_from_lookup(
                lookup,
                parameter_file,
                (10, 12, 0, 2),
                (3, 3),
                region_shape="rectangle",
            )
            ellipse = radar_indices_from_lookup(
                lookup,
                parameter_file,
                (10, 12, 0, 2),
                (3, 3),
                region_shape="ellipse",
            )
            mask = np.ones((3, 3), dtype=np.uint8)
            mask.reshape(-1)[4] = 0
            masked = radar_indices_from_lookup(
                lookup,
                parameter_file,
                (10, 12, 0, 2),
                (3, 3),
                radar_mask=mask,
                region_shape="rectangle",
            )

            np.testing.assert_array_equal(rectangle, np.arange(9))
            np.testing.assert_array_equal(ellipse, np.array([1, 3, 4, 5, 7]))
            np.testing.assert_array_equal(masked, np.array([0, 1, 2, 3, 5, 6, 7, 8]))

    def test_deduplicates_and_applies_deterministic_pixel_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parameter_file = self._parameter_file(Path(temporary_directory))
            lookup = self._lookup()
            lookup[0, 1] = lookup[0, 0]

            result = radar_indices_from_lookup(
                lookup,
                parameter_file,
                (10, 12, 0, 2),
                (3, 3),
                region_shape="rectangle",
                max_pixels=3,
            )

            np.testing.assert_array_equal(result, np.array([0, 4, 8]))

    def test_rejects_invalid_lookup_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            parameter_file = self._parameter_file(Path(temporary_directory))
            lookup = self._lookup()

            with self.assertRaisesRegex(ValueError, "lookup shape"):
                radar_indices_from_lookup(
                    lookup[:2], parameter_file, (10, 12, 0, 2), (3, 3)
                )
            with self.assertRaisesRegex(ValueError, "west < east"):
                radar_indices_from_lookup(
                    lookup, parameter_file, (12, 10, 0, 2), (3, 3)
                )
            with self.assertRaisesRegex(ValueError, "region_shape"):
                radar_indices_from_lookup(
                    lookup,
                    parameter_file,
                    (10, 12, 0, 2),
                    (3, 3),
                    region_shape="polygon",
                )
            with self.assertRaisesRegex(ValueError, "max_pixels"):
                radar_indices_from_lookup(
                    lookup,
                    parameter_file,
                    (10, 12, 0, 2),
                    (3, 3),
                    max_pixels=0,
                )


if __name__ == "__main__":
    unittest.main()
