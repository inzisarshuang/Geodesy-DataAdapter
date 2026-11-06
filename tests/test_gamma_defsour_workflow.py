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


if __name__ == "__main__":
    unittest.main()
