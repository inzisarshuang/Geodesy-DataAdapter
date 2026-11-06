"""Method-root output defaults for fast Data Adapter products."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.project_layout import AdapterProjectLayout
from insar_data_adapter.config import load_mintpy_conversion_config


class AdapterProjectLayoutTests(unittest.TestCase):
    def test_derives_canonical_and_export_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = AdapterProjectLayout.bind(
                root, "S1/ASCENDING_128", "S1/ASCENDING_128/GAMMA"
            )
            self.assertEqual(
                layout.canonical("timeseries.h5"),
                root / "S1/ASCENDING_128/GAMMA/CANONICAL/timeseries.h5",
            )
            self.assertEqual(
                layout.export("defsour.txt"),
                root / "S1/ASCENDING_128/GAMMA/EXPORT/defsour.txt",
            )
            self.assertEqual(
                layout.defsour("gamma"),
                root / "S1/ASCENDING_128/GAMMA/EXPORT/DEFSOUR/GAMMA",
            )
            self.assertEqual(
                layout.defsour("mintpy"),
                root / "S1/ASCENDING_128/GAMMA/EXPORT/DEFSOUR/MINTPY",
            )

    def test_rejects_wrong_method_root_and_unsafe_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "processing_root"):
                AdapterProjectLayout.bind(
                    root, "S1/ASCENDING_128", "S1/DESCENDING_135/GAMMA"
                )
            layout = AdapterProjectLayout.bind(
                root, "S1/ASCENDING_128", "S1/ASCENDING_128/GAMMA"
            )
            with self.assertRaisesRegex(ValueError, "filename"):
                layout.canonical("../escape.h5")
            with self.assertRaisesRegex(ValueError, "source"):
                layout.defsour("../escape")

    def test_cfg_derives_default_but_explicit_output_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config/3adapter/mintpy.cfg"
            config.parent.mkdir(parents=True)
            common = (
                "timeseries_file = source/timeseries.h5\n"
                "geometry_file = source/geometry.h5\n"
                "mask_file = source/mask.h5\n"
                "los_positive = toward_satellite\n"
                "nodata_policy = explicit mask\n"
                "height_unit = m\n"
                f"project_root = {root}\n"
                "project = S1/ASCENDING_128\n"
                "processing_root = S1/ASCENDING_128/GAMMA\n"
                "output_name = adapted.h5\n"
            )
            config.write_text(common, encoding="utf-8")
            loaded = load_mintpy_conversion_config(config)
            self.assertEqual(
                loaded["output_file"],
                root / "S1/ASCENDING_128/GAMMA/CANONICAL/adapted.h5",
            )
            config.write_text(common + "output_file = manual/result.h5\n", encoding="utf-8")
            loaded = load_mintpy_conversion_config(config)
            self.assertEqual(
                loaded["output_file"], config.parent / "manual/result.h5"
            )


if __name__ == "__main__":
    unittest.main()
