from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.sources.geotiff_series import (
    GeoTIFFSeriesEpoch,
    read_geotiff_series_index,
)


class GeoTIFFSeriesSourceTests(unittest.TestCase):
    def test_reads_two_columns_in_order_and_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "rasters/first.tif"
            second = root / "second.tif"
            first.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            index = root / "series.txt"
            index.write_text(
                "# exact epoch and raster\n"
                "\n"
                "20240101T123456 rasters/first.tif\n"
                f"20240113T234501 {second}\n",
                encoding="utf-8",
            )

            epochs = read_geotiff_series_index(index)

            self.assertEqual(
                epochs,
                (
                    GeoTIFFSeriesEpoch("20240101T123456", "20240101", first),
                    GeoTIFFSeriesEpoch("20240113T234501", "20240113", second),
                ),
            )

    def test_rejects_duplicate_epoch_or_path(self) -> None:
        for rows, message in (
            (
                "20240101T000000 first.tif\n20240101T000000 second.tif\n",
                "duplicate epoch",
            ),
            (
                "20240101T000000 first.tif\n20240102T000000 first.tif\n",
                "duplicate TIFF",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "first.tif").write_bytes(b"first")
                (root / "second.tif").write_bytes(b"second")
                index = root / "series.txt"
                index.write_text(rows, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    read_geotiff_series_index(index)

    def test_rejects_malformed_rows_and_invalid_epochs(self) -> None:
        cases = (
            ("20240101T000000\n", "exactly two columns"),
            ("20240101T000000 one.tif extra\n", "exactly two columns"),
            ("20240101 one.tif\n", "epoch_id"),
            ("20240230T120000 one.tif\n", "epoch_id"),
            ("# comments only\n\n", "at least one epoch"),
        )
        for text, message in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "one.tif").write_bytes(b"one")
                index = root / "series.txt"
                index.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    read_geotiff_series_index(index)

    def test_rejects_missing_index_missing_tiff_and_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileNotFoundError):
                read_geotiff_series_index(root / "missing.txt")

            index = root / "series.txt"
            index.write_text("20240101T000000 missing.tif\n", encoding="utf-8")
            with self.assertRaisesRegex(FileNotFoundError, "TIFF"):
                read_geotiff_series_index(index)

            folder = root / "folder.tif"
            folder.mkdir()
            index.write_text("20240101T000000 folder.tif\n", encoding="utf-8")
            with self.assertRaisesRegex(FileNotFoundError, "TIFF"):
                read_geotiff_series_index(index)


if __name__ == "__main__":
    unittest.main()
