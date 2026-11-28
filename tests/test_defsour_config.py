from __future__ import annotations

import json
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.workflows.defsour.config import (
    GammaDefsourConfig,
    LiCSBASDefsourConfig,
    MintPyDefsourConfig,
    load_gamma_defsour_config,
    load_licsbas_defsour_config,
    load_mintpy_defsour_config,
)


COMMON = """output_dir = output
dates = 20240101, 20240113
prefix = defo_
extension = .txt
source_crs = EPSG:32647
output_crs = EPSG:32647
format = %.3f %.3f %.4f %.6f
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = finite values and explicit mask
temporal_reference = first
spatial_reference = none
source_provenance = synthetic
downsample_mode = factor
factor = 2
aggregation = mean
chunk_rows = 64
write_tif = true
overwrite = true
"""


class DefsourConfigTests(unittest.TestCase):
    def write(self, root: Path, name: str, source: str, extra: str = "") -> Path:
        path = root / "configs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(COMMON + source + extra, encoding="utf-8")
        return path

    def gamma(self, root: Path, extra: str = "") -> Path:
        return self.write(
            root,
            "gamma.cfg",
            """tab_file = ../inputs/epochs.tab
dates_file = ../inputs/dates.txt
source_unit = m
parameter_file = ../inputs/grid.dem_par
height_file = ../inputs/height.bin
mask_file = ../inputs/mask.bin
deformation_dtype = float32
deformation_byte_order = big
height_dtype = float32
height_byte_order = big
mask_dtype = uint8
mask_byte_order = native
grid_registration = pixel_center
mode = native
export_invalid_points = false
""",
            extra,
        )

    def mintpy(self, root: Path, extra: str = "") -> Path:
        return self.write(
            root,
            "mintpy.cfg",
            """timeseries_file = ../inputs/timeseries.h5
geometry_file = ../inputs/geometry.h5
mask_file = ../inputs/mask.h5
timeseries_dataset = timeseries
date_dataset = date
height_dataset = height
mask_dataset = mask
write_native_tif = false
write_velocity_tif = false
write_dem_tif = false
native_only = false
""",
            extra,
        )

    def licsbas(self, root: Path, extra: str = "") -> Path:
        return self.write(
            root,
            "licsbas.cfg",
            """input_file = ../inputs/cum.h5
source_unit = m
deformation_dataset = cum
date_dataset = imdates
height_dataset = hgt
mask_dataset = mask
refarea_dataset = refarea
""",
            extra,
        )

    def test_source_configs_are_frozen_relative_and_source_specific(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gamma = load_gamma_defsour_config(self.gamma(root))
            mintpy = load_mintpy_defsour_config(self.mintpy(root))
            licsbas = load_licsbas_defsour_config(self.licsbas(root))
            self.assertIsInstance(gamma, GammaDefsourConfig)
            self.assertIsInstance(mintpy, MintPyDefsourConfig)
            self.assertIsInstance(licsbas, LiCSBASDefsourConfig)
            self.assertEqual(gamma.tab_file, root / "inputs/epochs.tab")
            self.assertEqual(mintpy.timeseries_file, root / "inputs/timeseries.h5")
            self.assertEqual(licsbas.input_file, root / "inputs/cum.h5")
            self.assertEqual(gamma.output_dir, root / "configs/output")
            self.assertEqual(gamma.dates, ("20240101", "20240113"))
            self.assertEqual((gamma.factor, gamma.output_unit), (2, "mm"))
            with self.assertRaises(Exception):
                gamma.chunk_rows = 1
            self.gamma(root, "velocity_file = wrong-source.h5\n")
            with self.assertRaisesRegex(ValueError, "unknown cfg key"):
                load_gamma_defsour_config(root / "configs/gamma.cfg")

    def test_strict_common_values_and_conditionals(self) -> None:
        replacements = (
            ("dates = 20240101, 20240113", "dates = 20240101, 20240101", "duplicate"),
            ("temporal_reference = first", "temporal_reference = 20240230", "date"),
            ("output_unit = mm", "output_unit = cm", "output_unit"),
            ("downsample_mode = factor", "downsample_mode = target_points", "target_points"),
            ("aggregation = mean", "aggregation = maximum", "aggregation"),
            ("chunk_rows = 64", "chunk_rows = 0", "chunk_rows"),
            ("write_tif = true", "write_tif = maybe", "write_tif"),
            ("format = %.3f %.3f %.4f %.6f", "format = %.3f %.3f", "four columns"),
        )
        for old, new, message in replacements:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cfg = self.gamma(root)
                cfg.write_text(cfg.read_text().replace(old, new))
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_defsour_config(cfg)
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.gamma(Path(directory))
            cfg.write_text(cfg.read_text() + "factor = 3\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_gamma_defsour_config(cfg)

    def test_method_root_default_and_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.gamma(root)
            text = cfg.read_text().replace(
                "output_dir = output\n",
                f"project_root = {root}\nproject = S1/ASCENDING_128\nprocessing_root = S1/ASCENDING_128/GAMMA_mb\n",
            )
            cfg.write_text(text)
            loaded = load_gamma_defsour_config(cfg)
            self.assertEqual(
                loaded.output_dir,
                root / "S1/ASCENDING_128/GAMMA_mb/EXPORT/DEFSOUR/GAMMA",
            )

    def test_source_specific_conditionals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gamma = self.gamma(root)
            gamma.write_text(
                gamma.read_text().replace("mode = native", "mode = aligned")
            )
            with self.assertRaisesRegex(ValueError, "alignment_template"):
                load_gamma_defsour_config(gamma)
            mintpy = self.mintpy(root)
            mintpy.write_text(
                mintpy.read_text().replace("native_only = false", "native_only = true")
            )
            with self.assertRaisesRegex(ValueError, "native_only"):
                load_mintpy_defsour_config(mintpy)
            licsbas = self.licsbas(root, "unknown_gamma_key = value\n")
            with self.assertRaisesRegex(ValueError, "unknown cfg key"):
                load_licsbas_defsour_config(licsbas)

    def test_gamma_accepts_documented_symbolic_modes(self) -> None:
        """Check documented case normalization and the conditional companion keys."""
        with tempfile.TemporaryDirectory() as directory:
            config = self.gamma(Path(directory))
            text = config.read_text(encoding="utf-8")
            variants = (
                ("native", "factor", "factor = 2", "first"),
                ("ALIGNED", "TARGET_POINTS", "target_points = 100", "preserve"),
                ("native", "target_pixel_size", "target_pixel_size = 90", "20240113"),
            )
            for mode, strategy, size_field, reference in variants:
                with self.subTest(mode=mode, strategy=strategy, reference=reference):
                    variant = (
                        text.replace("mode = native", f"mode = {mode}")
                        .replace("downsample_mode = factor", f"downsample_mode = {strategy}")
                        .replace("factor = 2", size_field)
                        .replace("temporal_reference = first", f"temporal_reference = {reference}")
                        .replace("aggregation = mean", "aggregation = MEDIAN")
                        .replace("deformation_byte_order = big", "deformation_byte_order = LITTLE")
                        .replace("write_tif = true", "write_tif = no")
                    )
                    if mode.lower() == "aligned":
                        variant += "alignment_template = output/alignment_template.npz\n"
                    config.write_text(variant, encoding="utf-8")
                    loaded = load_gamma_defsour_config(config)
                    self.assertEqual(loaded.mode, mode.lower())
                    self.assertEqual(loaded.downsample_mode, strategy.lower())
                    self.assertEqual(loaded.temporal_reference, reference)
                    self.assertEqual(loaded.aggregation, "median")
                    self.assertEqual(loaded.deformation_byte_order, "little")
                    self.assertFalse(loaded.write_tif)

    def test_gamma_source_unit_is_required_and_controls_scaling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = self.gamma(root)
            missing.write_text(missing.read_text().replace("source_unit = m\n", ""))
            with self.assertRaisesRegex(ValueError, "source_unit"):
                load_gamma_defsour_config(missing)

            mismatched = self.gamma(root)
            mismatched.write_text(
                mismatched.read_text().replace("source_unit = m", "source_unit = mm")
            )
            with self.assertRaisesRegex(ValueError, "output_unit"):
                load_gamma_defsour_config(mismatched)

    def test_gamma_explicit_coordinates_require_binary_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.gamma(
                root,
                "longitude_file = ../inputs/lon.bin\n"
                "latitude_file = ../inputs/lat.bin\n"
                "longitude_dtype = float64\n"
                "longitude_byte_order = big\n"
                "latitude_dtype = float64\n"
                "latitude_byte_order = little\n",
            )
            loaded = load_gamma_defsour_config(cfg)
            self.assertEqual(loaded.longitude_dtype, "float64")
            self.assertEqual(loaded.latitude_byte_order, "little")

            cfg.write_text(cfg.read_text().replace("longitude_dtype = float64\n", ""))
            with self.assertRaisesRegex(ValueError, "longitude_dtype"):
                load_gamma_defsour_config(cfg)

    def test_optional_analysis_manifest_is_validated_without_overriding_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "inputs/timeseries_manifest.json"
            manifest.parent.mkdir()
            displacement_dir = manifest.parent / "DISPLACEMENT"
            displacement_dir.mkdir()
            product_paths = [
                "DISPLACEMENT/20240101.disp",
                "DISPLACEMENT/20240113.disp",
            ]
            for relative in product_paths:
                (manifest.parent / relative).write_bytes(b"product")
            (manifest.parent / "epochs.tab").write_text(
                "".join(f"{path}\n" for path in product_paths)
            )
            (manifest.parent / "dates.txt").write_text("20240101\n20240113\n")
            payload = {
                "schema_version": 2,
                "status": "complete",
                "method": "gamma_mb",
                "epochs": ["20240101", "20240113"],
                "epoch_count": 2,
                "grid": {"width": 3, "lines": 2},
                "map_grid": {"width": 6, "lines": 4},
                "displacement": {
                    "enabled": True,
                    "geocoded_enabled": False,
                    "quantity": "cumulative_los_displacement",
                    "units": "meter",
                    "paths": product_paths,
                    "geocoded_paths": [],
                },
                "products": {},
            }
            def write_manifest(value: dict[str, object], *, digest: str | None = None) -> None:
                scientific = {
                    key: item
                    for key, item in value.items()
                    if key not in {"scientific_manifest_digest", "required_products", "figures"}
                }
                value["scientific_manifest_digest"] = digest or hashlib.sha256(
                    (json.dumps(scientific, sort_keys=True, indent=2) + "\n").encode()
                ).hexdigest()
                value["required_products"] = list(product_paths)
                value["figures"] = []
                manifest.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

            write_manifest(payload)
            cfg = self.gamma(
                root,
                "source_manifest = ../inputs/timeseries_manifest.json\nsource_width = 3\nsource_lines = 2\n",
            )
            loaded = load_gamma_defsour_config(cfg)
            self.assertEqual(loaded.source_manifest, manifest)
            for key, value, message in (
                ("status", "incomplete", "complete"),
                ("method", "stacking", "method"),
                ("epochs", ["20240101"], "dates"),
            ):
                with self.subTest(key=key):
                    changed = copy.deepcopy(payload)
                    changed[key] = value
                    if key == "epochs":
                        changed["epoch_count"] = 1
                    write_manifest(changed)
                    with self.assertRaisesRegex(ValueError, message):
                        load_gamma_defsour_config(cfg)
            write_manifest(copy.deepcopy(payload), digest="bad")
            with self.assertRaisesRegex(ValueError, "digest"):
                load_gamma_defsour_config(cfg)
            changed = copy.deepcopy(payload)
            changed["grid"]["width"] = 4
            write_manifest(changed)
            with self.assertRaisesRegex(ValueError, "grid width"):
                load_gamma_defsour_config(cfg)
            changed = copy.deepcopy(payload)
            changed["displacement"]["units"] = "centimeter"
            write_manifest(changed)
            with self.assertRaisesRegex(ValueError, "source_unit"):
                load_gamma_defsour_config(cfg)
            changed = copy.deepcopy(payload)
            changed["displacement"]["paths"][0] = "../escape.bin"
            write_manifest(changed)
            with self.assertRaisesRegex(ValueError, "traversal"):
                load_gamma_defsour_config(cfg)


if __name__ == "__main__":
    unittest.main()
