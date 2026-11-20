from __future__ import annotations

import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from insar_data_adapter.exporters.defsour import DefsourExportMetadata
from insar_data_adapter.workflows.defsour.models import (
    DefsourEpochResult,
    DefsourSnapshotMetadata,
)
from insar_data_adapter import cli


class DefsourCliTests(unittest.TestCase):
    def result(self, source: str) -> DefsourSnapshotMetadata:
        return DefsourSnapshotMetadata(
            source=source,
            epochs=(
                DefsourEpochResult(
                    "20240101",
                    Path("epochs/D20240101.txt"),
                    12,
                    Path("geotiff/D20240101.tif"),
                    epoch_id=("20240101T123456" if source == "geotiff" else None),
                ),
            ),
            metadata=DefsourExportMetadata(
                crs="EPSG:32647",
                deformation_unit="mm",
                deformation_quantity="cumulative_displacement",
                height_unit="m",
                los_positive="toward_satellite",
                nodata_policy="explicit mask",
                temporal_reference="20240101",
                spatial_reference="none",
                source_provenance="synthetic",
            ),
            transformations={"factor": 1},
            additional_products=(
                Path("alignment_template.npz"),
                Path("native/velocity.tif"),
            ),
        )

    def test_commands_require_config(self) -> None:
        for command in (
            "export-gamma-defsour",
            "export-mintpy-defsour",
            "export-licsbas-defsour",
            "export-geotiff-defsour",
        ):
            with self.subTest(command=command), self.assertRaises(SystemExit) as raised:
                cli.main([command])
            self.assertNotEqual(raised.exception.code, 0)

    def test_each_command_loads_dispatches_and_prints_small_summary(self) -> None:
        for source in ("gamma", "mintpy", "licsbas", "geotiff"):
            command = f"export-{source}-defsour"
            config = type("Config", (), {"output_dir": Path("/tmp/export")})()
            output = StringIO()
            with (
                patch.object(cli, f"load_{source}_defsour_config", return_value=config) as loader,
                patch.object(cli, f"export_{source}_defsour", return_value=self.result(source)) as workflow,
                redirect_stdout(output),
            ):
                cli.main([command, "--config", "workflow.cfg"])
            loader.assert_called_once_with("workflow.cfg")
            workflow.assert_called_once_with(config)
            summary = output.getvalue()
            self.assertIn("OUTPUT: /tmp/export", summary)
            self.assertIn("DATES: 20240101", summary)
            if source == "geotiff":
                self.assertIn("EPOCH_IDS: 20240101T123456", summary)
            self.assertIn("POINT_COUNTS: 12", summary)
            self.assertIn("GEOTIFFS: 2", summary)
            self.assertIn("TEMPLATES: 1", summary)
            self.assertIn("MANIFEST: /tmp/export/defsour_manifest.json", summary)

    def test_repository_uses_one_config_tree(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "config_examples").exists())
        expected = {
            "config/data2canonical/gamma2canonical_h5.cfg",
            "config/data2canonical/mintpy2canonical_h5.cfg",
            "config/data2canonical/licsbas2canonical_h5.cfg",
            "config/data2canonical/inspect_h5.cfg",
            "config/data2defsour/gamma2defsour.cfg",
            "config/data2defsour/mintpy2defsour.cfg",
            "config/data2defsour/licsbas2defsour.cfg",
            "config/data2defsour/geotiff2defsour.cfg",
        }
        self.assertEqual(
            expected,
            {
                path.relative_to(root).as_posix()
                for path in (root / "config").glob("*/*.cfg")
            },
        )
        package_data = tomllib.loads((root / "pyproject.toml").read_text())[
            "tool"
        ]["setuptools"]["data-files"]["share/insar-data-adapter/config/data2defsour"]
        self.assertIn("config/data2defsour/geotiff2defsour.cfg", package_data)


if __name__ == "__main__":
    unittest.main()
