from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.workflows.defsour.config import (
    GeoTIFFDefsourConfig,
    load_geotiff_defsour_config,
)


BASE = """output_dir = output
epochs = all
prefix = D
extension = .txt
source_crs = EPSG:4326
output_crs = EPSG:32605
format = %.3f %.3f %.3f %.6f
source_unit = m
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = source_values_preserved_direction_unknown
nodata_policy = finite deformation and height plus positive static mask; zero is valid
temporal_reference = preserve
spatial_reference = preserve upstream spatial reference
source_provenance = synthetic indexed GeoTIFF series
downsample_mode = factor
factor = 2
aggregation = mean
chunk_rows = 8
write_tif = false
overwrite = true
index_file = ../inputs/series.txt
height_file = ../inputs/dem.tif
mask_file = ../inputs/mask.tif
mask_mode = positive
"""


class GeoTIFFDefsourConfigTests(unittest.TestCase):
    def write(self, root: Path, text: str = BASE) -> Path:
        inputs = root / "inputs"
        inputs.mkdir()
        for name in ("series.txt", "dem.tif", "mask.tif"):
            (inputs / name).write_bytes(b"input")
        config = root / "config/geotiff.cfg"
        config.parent.mkdir()
        config.write_text(text, encoding="utf-8")
        return config

    def test_loads_frozen_paths_units_and_exact_epoch_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write(
                root,
                BASE.replace(
                    "epochs = all",
                    "epochs = 20240101T123456, 20240113T234501",
                ),
            )

            loaded = load_geotiff_defsour_config(config)

            self.assertIsInstance(loaded, GeoTIFFDefsourConfig)
            self.assertEqual(loaded.output_dir, root / "config/output")
            self.assertEqual(loaded.index_file, root / "inputs/series.txt")
            self.assertEqual(loaded.height_file, root / "inputs/dem.tif")
            self.assertEqual(loaded.mask_file, root / "inputs/mask.tif")
            self.assertEqual(
                loaded.epoch_ids,
                ("20240101T123456", "20240113T234501"),
            )
            self.assertEqual((loaded.source_unit, loaded.mask_mode), ("m", "positive"))
            self.assertEqual((loaded.factor, loaded.output_unit), (2, "mm"))
            with self.assertRaises(Exception):
                loaded.chunk_rows = 1

    def test_supports_all_downsampling_modes(self) -> None:
        cases = (
            ("downsample_mode = factor\nfactor = 2", (2, None, None)),
            ("downsample_mode = target_points\ntarget_points = 100", (None, 100, None)),
            (
                "downsample_mode = target_pixel_size\ntarget_pixel_size = 0.01",
                (None, None, 0.01),
            ),
        )
        for replacement, expected in cases:
            with self.subTest(mode=replacement), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                text = BASE.replace("downsample_mode = factor\nfactor = 2", replacement)
                loaded = load_geotiff_defsour_config(self.write(root, text))
                self.assertEqual(
                    (loaded.factor, loaded.target_points, loaded.target_pixel_size),
                    expected,
                )

    def test_rejects_unknown_missing_or_ambiguous_scientific_metadata(self) -> None:
        replacements = (
            ("source_crs = EPSG:4326\n", "", "source_crs"),
            ("source_unit = m\n", "", "source_unit"),
            ("mask_mode = positive", "mask_mode = nonzero", "mask_mode"),
            ("output_unit = mm", "output_unit = m", "output_unit"),
            ("epochs = all", "epochs = 20240230T120000", "epochs"),
            (
                "los_positive = source_values_preserved_direction_unknown",
                "los_positive = toward_satellite",
                "los_positive",
            ),
            (
                "deformation_quantity = cumulative_displacement",
                "deformation_quantity = velocity",
                "deformation_quantity",
            ),
            (
                "temporal_reference = preserve",
                "temporal_reference = first",
                "temporal_reference",
            ),
        )
        for old, new, message in replacements:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = self.write(root, BASE.replace(old, new))
                with self.assertRaisesRegex(ValueError, message):
                    load_geotiff_defsour_config(config)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write(root, BASE + "unknown_key = value\n")
            with self.assertRaisesRegex(ValueError, "unknown cfg key"):
                load_geotiff_defsour_config(config)


if __name__ == "__main__":
    unittest.main()
