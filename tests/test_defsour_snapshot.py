from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from insar_data_adapter.exporters.defsour import DefsourExportMetadata
from insar_data_adapter.workflows.defsour.models import (
    DefsourEpochResult,
    DefsourSnapshotMetadata,
)
from insar_data_adapter.workflows.defsour.publication import publish_defsour_snapshot


class DefsourSnapshotTests(unittest.TestCase):
    def _metadata(self, staging: Path, *, content: str = "new\n") -> DefsourSnapshotMetadata:
        epoch = staging / "epochs/20240101.txt"
        epoch.parent.mkdir(parents=True)
        epoch.write_text(content, encoding="ascii")
        tif = staging / "geotiff/20240101.tif"
        tif.parent.mkdir()
        tif.write_bytes(b"tif")
        template = staging / "alignment_template.npz"
        template.write_bytes(b"template")
        return DefsourSnapshotMetadata(
            source="gamma",
            epochs=(DefsourEpochResult("20240101", Path("epochs/20240101.txt"), 1, Path("geotiff/20240101.tif")),),
            metadata=DefsourExportMetadata(
                crs="EPSG:32647",
                deformation_unit="m",
                deformation_quantity="cumulative_displacement",
                height_unit="m",
                los_positive="toward_satellite",
                nodata_policy="finite mask",
                temporal_reference="first selected epoch",
                spatial_reference="none",
                source_provenance="synthetic test",
            ),
            transformations={"scale": 1.0, "aggregation": "mean"},
            additional_products=(Path("alignment_template.npz"),),
        )

    def test_absent_snapshot_publishes_manifest_last_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            result = publish_defsour_snapshot(output, self._metadata)
            self.assertEqual(result.source, "gamma")
            manifest = json.loads((output / "defsour_manifest.json").read_text())
            self.assertEqual((manifest["schema_version"], manifest["status"]), (1, "complete"))
            self.assertEqual(manifest["dates"], ["20240101"])
            self.assertEqual(manifest["point_counts"], [1])
            self.assertEqual(manifest["metadata"]["deformation_unit"], "m")
            self.assertIn("epochs/20240101.txt", manifest["required_products"])
            self.assertIn("geotiff/20240101.tif", manifest["required_products"])
            self.assertTrue((output / "README_DEFSOUR.txt").is_file())

    def test_complete_snapshot_is_replaced_but_overwrite_false_stops_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            output.mkdir()
            (output / "old.txt").write_text("old")
            publish_defsour_snapshot(output, self._metadata)
            self.assertFalse((output / "old.txt").exists())
            self.assertEqual((output / "epochs/20240101.txt").read_text(), "new\n")
            called = False

            def build(_: Path) -> DefsourSnapshotMetadata:
                nonlocal called
                called = True
                raise AssertionError

            with self.assertRaises(FileExistsError):
                publish_defsour_snapshot(output, build, overwrite=False)
            self.assertFalse(called)

    def test_builder_or_validation_failure_preserves_old_snapshot(self) -> None:
        for mode in ("builder", "missing", "empty"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "snapshot"
                output.mkdir()
                old = output / "old.txt"
                old.write_text("old")

                def build(staging: Path) -> DefsourSnapshotMetadata:
                    metadata = self._metadata(staging)
                    if mode == "builder":
                        (staging / "partial.txt").write_text("partial")
                        raise RuntimeError("late synthetic failure")
                    epoch = staging / metadata.epochs[0].defsour_path
                    if mode == "missing":
                        epoch.unlink()
                    else:
                        epoch.write_bytes(b"")
                    return metadata

                with self.assertRaises((RuntimeError, ValueError)):
                    publish_defsour_snapshot(output, build)
                self.assertEqual(old.read_text(), "old")
                self.assertEqual({item.name for item in Path(directory).iterdir()}, {"snapshot"})

    def test_failed_final_replace_rolls_back_old_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            output.mkdir()
            (output / "old.txt").write_text("old")
            real_replace = os.replace
            failed = False

            def replace(source, destination):
                nonlocal failed
                source_path = Path(source)
                destination_path = Path(destination)
                if destination_path == output and "staging" in source_path.name and not failed:
                    failed = True
                    raise OSError("synthetic publish failure")
                return real_replace(source, destination)

            with patch(
                "insar_data_adapter.workflows.defsour.publication.os.replace",
                side_effect=replace,
            ):
                with self.assertRaisesRegex(OSError, "synthetic"):
                    publish_defsour_snapshot(output, self._metadata)
            self.assertEqual((output / "old.txt").read_text(), "old")
            self.assertEqual({item.name for item in Path(directory).iterdir()}, {"snapshot"})


if __name__ == "__main__":
    unittest.main()
