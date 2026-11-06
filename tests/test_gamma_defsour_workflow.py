from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from insar_data_adapter.workflows.defsour.config import load_gamma_defsour_config
from insar_data_adapter.workflows.defsour.gamma import export_gamma_defsour


class GammaDefsourWorkflowTests(unittest.TestCase):
    def fixture(self, root: Path, *, output: str = "export", mode: str = "native", template: str | None = None) -> Path:
        values = (
            np.array([[0, 1, 2], [3, 4, 5]], dtype=np.float32),
            np.array([[0, 2, -9999], [6, 8, 10]], dtype=np.float32),
        )
        for index, value in enumerate(values, 1):
            value.astype(">f4").tofile(root / f"D{index}.bin")
        np.array([[0, 11, 12], [13, 14, 15]], dtype=">f4").tofile(root / "height.bin")
        np.array([[1, 1, 1], [1, 0, 1]], dtype=np.uint8).tofile(root / "mask.bin")
        (root / "epochs.tab").write_text("D1.bin\nD2.bin\n")
        (root / "dates.txt").write_text("20240101\n20240113\n")
        (root / "grid.dem_par").write_text(
            "width: 3\nnlines: 2\nEPSG: 32647\n"
            "corner_lon: 100\ncorner_lat: 500\npost_lon: 10\npost_lat: -10\n"
        )
        template_line = "" if template is None else f"alignment_template = {template}\n"
        cfg = root / f"{output}.cfg"
        cfg.write_text(
            f"""output_dir = {output}
dates = 20240101, 20240113
prefix = defo_
extension = .txt
source_crs = EPSG:32647
output_crs = EPSG:32647
source_unit = m
format = %.2f %.2f %.2f %.3f
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = -9999 and explicit mask
temporal_reference = first
spatial_reference = none
source_provenance = synthetic GAMMA
downsample_mode = factor
factor = 1
aggregation = mean
chunk_rows = 1
write_tif = true
overwrite = true
tab_file = epochs.tab
dates_file = dates.txt
parameter_file = grid.dem_par
height_file = height.bin
mask_file = mask.bin
deformation_dtype = float32
deformation_byte_order = big
height_dtype = float32
height_byte_order = big
mask_dtype = uint8
mask_byte_order = native
deformation_nodata = -9999
grid_registration = pixel_center
mode = {mode}
{template_line}export_invalid_points = false
"""
        )
        return cfg

    def test_native_export_scales_references_preserves_zero_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.glob("*.bin")}
            result = export_gamma_defsour(load_gamma_defsour_config(cfg))
            self.assertEqual([epoch.date for epoch in result.epochs], ["20240101", "20240113"])
            self.assertEqual([epoch.point_count for epoch in result.epochs], [5, 4])
            first = np.loadtxt(root / "export/epochs/defo_20240101.txt")
            self.assertTrue(np.all(first[:, 3] == 0.0))
            self.assertEqual(first[0, 2], 0.0)
            second = np.loadtxt(root / "export/epochs/defo_20240113.txt")
            self.assertIn(1000.0, second[:, 3])
            self.assertTrue((root / "export/geotiff/defo_20240113.tif").is_file())
            manifest = json.loads((root / "export/defsour_manifest.json").read_text())
            self.assertEqual(manifest["transformations"]["deformation_scale"], 1000.0)
            self.assertEqual(manifest["metadata"]["temporal_reference"], "20240101")
            after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.glob("*.bin")}
            self.assertEqual(after, before)

    def test_output_directory_must_not_contain_cfg_or_source_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            cfg.write_text(cfg.read_text().replace("output_dir = export", "output_dir = ."))
            protected = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.iterdir()
                if path.is_file()
            }

            with self.assertRaisesRegex(ValueError, "overlaps.*input"):
                export_gamma_defsour(load_gamma_defsour_config(cfg))

            self.assertEqual(
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.iterdir()
                    if path.is_file()
                },
                protected,
            )

    def test_aligned_mode_creates_and_reuses_snapshot_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_cfg = self.fixture(
                root,
                output="aligned1",
                mode="aligned",
                template="aligned1/alignment_template.npz",
            )
            export_gamma_defsour(load_gamma_defsour_config(first_cfg))
            template = root / "aligned1/alignment_template.npz"
            self.assertTrue(template.is_file())
            second_cfg = self.fixture(
                root,
                output="aligned2",
                mode="aligned",
                template=str(template),
            )
            export_gamma_defsour(load_gamma_defsour_config(second_cfg))
            self.assertTrue((root / "aligned2/defsour_manifest.json").is_file())

            conflicting_cfg = self.fixture(
                root,
                output="aligned3",
                mode="aligned",
                template=str(template),
            )
            conflicting_cfg.write_text(
                conflicting_cfg.read_text().replace(
                    "output_crs = EPSG:32647", "output_crs = EPSG:4326"
                )
            )
            with self.assertRaisesRegex(ValueError, "template.*CRS"):
                export_gamma_defsour(load_gamma_defsour_config(conflicting_cfg))

    def test_aligned_output_keeps_the_requested_downsampled_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(
                root,
                output="aligned",
                mode="aligned",
                template="aligned/alignment_template.npz",
            )
            cfg.write_text(cfg.read_text().replace("factor = 1", "factor = 2"))

            result = export_gamma_defsour(load_gamma_defsour_config(cfg))

            self.assertEqual([epoch.point_count for epoch in result.epochs], [1, 1])
            with np.load(root / "aligned/alignment_template.npz", allow_pickle=False) as archive:
                self.assertEqual(archive["x"].shape, (1, 1))

    def test_late_invalid_epoch_preserves_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            export_gamma_defsour(load_gamma_defsour_config(cfg))
            manifest = root / "export/defsour_manifest.json"
            before = manifest.read_bytes()
            (root / "D2.bin").write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                export_gamma_defsour(load_gamma_defsour_config(cfg))
            self.assertEqual(manifest.read_bytes(), before)

    def test_export_invalid_points_writes_nan_skeleton_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            cfg.write_text(
                cfg.read_text()
                .replace("export_invalid_points = false", "export_invalid_points = true")
                .replace("write_tif = true", "write_tif = false")
            )

            export_gamma_defsour(load_gamma_defsour_config(cfg))

            first = np.loadtxt(root / "export/epochs/defo_20240101.txt")
            second = np.loadtxt(root / "export/epochs/defo_20240113.txt")
            self.assertEqual(first.shape, (6, 4))
            self.assertTrue(np.isnan(first[4, 2:]).all())
            self.assertTrue(np.isnan(second[2, 2:]).all())
            self.assertTrue(np.isnan(second[4, 2:]).all())

    def test_radar_grid_uses_explicit_longitude_latitude_in_native_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            np.array([[0, 1, 2], [3, 4, 5]], dtype=">f4").tofile(root / "D1.bin")
            np.array([[0, 2, 4], [6, 8, 10]], dtype=">f4").tofile(root / "D2.bin")
            np.array([[10, 11, 12], [13, 14, 15]], dtype=">f4").tofile(root / "height.bin")
            np.ones((2, 3), dtype=np.uint8).tofile(root / "mask.bin")
            longitude = np.array([[100.0, 100.1, 100.2], [100.01, 100.11, 100.21]])
            latitude = np.array([[35.0, 35.0, 35.0], [34.9, 34.9, 34.9]])
            longitude.astype(">f8").tofile(root / "longitude.bin")
            latitude.astype(">f8").tofile(root / "latitude.bin")
            (root / "epochs.tab").write_text("D1.bin\nD2.bin\n")
            (root / "dates.txt").write_text("20240101\n20240113\n")
            (root / "radar.par").write_text("range_samples: 3\nazimuth_lines: 2\n")
            cfg = root / "radar.cfg"
            cfg.write_text(
                """output_dir = export
dates = all
source_crs = EPSG:4326
output_crs = EPSG:4326
source_unit = m
deformation_scale = 1000
output_unit = mm
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = explicit mask
temporal_reference = first
spatial_reference = none
source_provenance = synthetic radar GAMMA
downsample_mode = factor
factor = 1
write_tif = false
overwrite = true
tab_file = epochs.tab
dates_file = dates.txt
parameter_file = radar.par
height_file = height.bin
mask_file = mask.bin
longitude_file = longitude.bin
latitude_file = latitude.bin
longitude_dtype = float64
longitude_byte_order = big
latitude_dtype = float64
latitude_byte_order = big
deformation_dtype = float32
deformation_byte_order = big
height_dtype = float32
height_byte_order = big
mask_dtype = uint8
mask_byte_order = native
grid_registration = pixel_center
mode = native
"""
            )

            export_gamma_defsour(load_gamma_defsour_config(cfg))

            exported = np.loadtxt(root / "export/epochs/defsour_20240113.txt")
            np.testing.assert_allclose(exported[:, 0], longitude.reshape(-1), atol=1e-6)
            np.testing.assert_allclose(exported[:, 1], latitude.reshape(-1), atol=1e-6)
            np.testing.assert_allclose(exported[:, 3], np.array([0, 1000, 2000, 3000, 4000, 5000]))

            unsafe_tif = root / "radar-tif.cfg"
            unsafe_tif.write_text(
                cfg.read_text()
                .replace("output_dir = export", "output_dir = export-tif")
                .replace("write_tif = false", "write_tif = true")
            )
            with self.assertRaisesRegex(ValueError, "irregular.*aligned"):
                export_gamma_defsour(load_gamma_defsour_config(unsafe_tif))
            self.assertFalse((root / "export-tif").exists())

    def test_radar_grid_aligned_mode_creates_regular_reusable_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shape = (3, 3)
            np.arange(9, dtype=">f4").reshape(shape).tofile(root / "D1.bin")
            (np.arange(9, dtype=np.float32) * 2).astype(">f4").reshape(shape).tofile(root / "D2.bin")
            np.arange(10, 19, dtype=">f4").reshape(shape).tofile(root / "height.bin")
            np.ones(shape, dtype=np.uint8).tofile(root / "mask.bin")
            rows, columns = np.indices(shape)
            longitude = 100.0 + columns * 0.1 + rows * 0.01
            latitude = 35.0 - rows * 0.1 + columns * 0.002
            longitude.astype(">f8").tofile(root / "longitude.bin")
            latitude.astype(">f8").tofile(root / "latitude.bin")
            (root / "epochs.tab").write_text("D1.bin\nD2.bin\n")
            (root / "dates.txt").write_text("20240101\n20240113\n")
            (root / "radar.par").write_text("range_samples: 3\nazimuth_lines: 3\n")

            def write_cfg(name: str, output: str, template: str) -> Path:
                cfg = root / name
                cfg.write_text(
                    f"""output_dir = {output}
dates = all
source_crs = EPSG:4326
output_crs = EPSG:4326
source_unit = m
deformation_scale = 1
output_unit = m
deformation_quantity = cumulative_displacement
height_unit = m
los_positive = toward_satellite
nodata_policy = explicit mask
temporal_reference = preserve
spatial_reference = none
source_provenance = synthetic radar GAMMA
downsample_mode = factor
factor = 1
write_tif = true
overwrite = true
tab_file = epochs.tab
dates_file = dates.txt
parameter_file = radar.par
height_file = height.bin
mask_file = mask.bin
longitude_file = longitude.bin
latitude_file = latitude.bin
longitude_dtype = float64
longitude_byte_order = big
latitude_dtype = float64
latitude_byte_order = big
deformation_dtype = float32
deformation_byte_order = big
height_dtype = float32
height_byte_order = big
mask_dtype = uint8
mask_byte_order = native
grid_registration = pixel_center
mode = aligned
alignment_template = {template}
"""
                )
                return cfg

            first = write_cfg("first.cfg", "aligned1", "aligned1/alignment_template.npz")
            export_gamma_defsour(load_gamma_defsour_config(first))
            template = root / "aligned1/alignment_template.npz"
            self.assertTrue(template.is_file())
            self.assertTrue((root / "aligned1/geotiff/defsour_20240113.tif").is_file())

            longitude += 0.02
            longitude.astype(">f8").tofile(root / "longitude.bin")
            second = write_cfg("second.cfg", "aligned2", str(template))
            result = export_gamma_defsour(load_gamma_defsour_config(second))
            self.assertTrue(result.transformations["template_reused"])

    def test_regular_grid_is_reprojected_to_explicit_output_crs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = self.fixture(root)
            cfg.write_text(
                cfg.read_text()
                .replace("source_crs = EPSG:32647", "source_crs = EPSG:4326")
                .replace("output_crs = EPSG:32647", "output_crs = EPSG:3857")
            )
            parameter = root / "grid.dem_par"
            parameter.write_text(
                parameter.read_text()
                .replace("EPSG: 32647", "EPSG: 4326")
                .replace("corner_lon: 100", "corner_lon: 10")
                .replace("corner_lat: 500", "corner_lat: 40")
                .replace("post_lon: 10", "post_lon: 0.1")
                .replace("post_lat: -10", "post_lat: -0.1")
            )
            export_gamma_defsour(load_gamma_defsour_config(cfg))
            exported = np.loadtxt(root / "export/epochs/defo_20240101.txt")
            self.assertGreater(exported[0, 0], 1_000_000)


if __name__ == "__main__":
    unittest.main()
